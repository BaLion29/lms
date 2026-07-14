"""Tests for ingestd.pipeline — no network, mock TdbClient.

Covers the generic pipeline: index from produces, ensure_entity batching,
one insert_documents per captured item, idempotency via derived_from,
status flip after success, empty-text guard.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ingestd.extraction import (
    ExtractionResult,
    build_extraction_context,
)
from ingestd.sources import CapturedAudioSource, CapturedTextSource
from ingestd.pipeline import Pipeline
from ingestd.settings import Settings
from firnline_core.tdb import TdbError

# Try importing extension plugins; skip tests if they're broken
try:
    from firnline_ext_planning.extract import (
        EventProposal,
        PersonProposal,
        PlanningPlugin,
        TaskProposal,
    )
    _planning_ok = True
except ImportError:
    _planning_ok = False

try:
    from firnline_ext_people.extract import PeopleLinkingPlugin
    _people_ok = True
except ImportError:
    _people_ok = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Shared extraction context for all pipeline tests
if _planning_ok and _people_ok:
    _PLANNING_PLUGIN = PlanningPlugin()
    _PEOPLE_PLUGIN = PeopleLinkingPlugin()
    _EXTRACTION_CTX = build_extraction_context([_PLANNING_PLUGIN, _PEOPLE_PLUGIN])
else:
    _EXTRACTION_CTX = None

_SOURCES = [CapturedTextSource(), CapturedAudioSource()]


def _settings(**overrides) -> Settings:
    return Settings(
        tdb_db="test",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
        **overrides,
    )


def _fake_tdb(
    *,
    captured_docs: list[dict] | None = None,
    documents: dict[str, list[dict]] | None = None,
    people: list[dict] | None = None,
    locations: list[dict] | None = None,
    tasks: list[dict] | None = None,
    events: list[dict] | None = None,
    reminders: list[dict] | None = None,
    graphql_entity_by_source: dict[str, list[dict]] | None = None,
    graphql_error: bool = False,
    graphql_error_first_call: bool = False,
    graphql_entity_null: bool = False,
) -> AsyncMock:
    """Build an AsyncMock TdbClient pre-configured to return the given docs."""
    tdb = AsyncMock()
    tdb.get_documents = AsyncMock()
    tdb.get_documents_by_status = AsyncMock()
    tdb.insert_documents = AsyncMock()
    tdb.replace_document = AsyncMock()
    tdb.graphql = AsyncMock()

    doc_map: dict[str, list[dict]] = dict(documents or {})
    if people:
        doc_map["Person"] = people
    if locations:
        doc_map["Location"] = locations
    if tasks:
        doc_map["Task"] = tasks
    if events:
        doc_map["Event"] = events
    if reminders:
        doc_map["Reminder"] = reminders

    async def _get_docs(type_: str, branch: str = "main"):
        return doc_map.get(type_, [])

    tdb.get_documents.side_effect = _get_docs

    async def _get_by_status(type_: str, status: str, branch: str = "main"):
        if type_ == "Captured":
            return [d for d in (captured_docs or []) if d.get("status") == status]
        return []

    tdb.get_documents_by_status.side_effect = _get_by_status

    _graphql_error_used = False

    async def _graphql(query: str, variables=None, branch=None):
        nonlocal _graphql_error_used
        if graphql_error:
            raise TdbError(500, "GraphQL error")
        if graphql_error_first_call and not _graphql_error_used:
            _graphql_error_used = True
            raise TdbError(500, "GraphQL error")
        if graphql_entity_null:
            return {"Entity": None}
        if graphql_entity_by_source is not None and variables and "src" in (variables or {}):
            src_key = variables["src"]
            return {"Entity": graphql_entity_by_source.get(src_key, [])}
        return {"Entity": []}

    tdb.graphql.side_effect = _graphql

    return tdb


def _captured_text(iri: str, content: str, status: str = "new") -> dict:
    return {
        "@id": iri,
        "@type": "Captured",
        "content": content,
        "content_type": "text/plain",
        "status": status,
        "captured_at": "2026-07-05T14:00:00Z",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }


def _captured_audio(iri: str, transcription: str, status: str = "transcribed") -> dict:
    return {
        "@id": iri,
        "@type": "Captured",
        "content_type": "audio/wav",
        "file_name": "rec.wav",
        "transcription": transcription,
        "captured_at": "2026-07-05T14:00:00Z",
        "status": status,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }


def _make_pipeline(tdb, agent=None, settings=None, extract_fn=None) -> Pipeline:
    return Pipeline(
        tdb=tdb,
        agent=agent,
        settings=settings or _settings(),
        source_plugins=_SOURCES,
        extraction_ctx=_EXTRACTION_CTX,
        extract_fn=extract_fn,
    )

# ---------------------------------------------------------------------------
# Core tests — use requires_all helper
# ---------------------------------------------------------------------------

requires_extensions = pytest.mark.skipif(
    _EXTRACTION_CTX is None,
    reason="extension pending kernel migration",
)


class TestCorePipeline:
    requires_extensions = pytest.mark.skipif(
        _EXTRACTION_CTX is None,
        reason="extension pending kernel migration",
    )

# ---------------------------------------------------------------------------
# Test 1 — Happy path: Captured text → Task
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_happy_path_inserts_task_and_flips_status():
    """One Captured text doc → extract returns TaskProposal → insert + status flip."""
    note = _captured_text("Captured/abc", "Buy milk tomorrow")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Buy milk",
                    description=None,
                    priority=None,
                    estimated_duration=None,
                    due_date=None,
                )
            ],
            reasoning="Simple task.",
            confidence=0.95,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    call_args = tdb.insert_documents.call_args
    docs = call_args[0][0]
    assert len(docs) == 1
    task = docs[0]
    assert task["@type"] == "Task"
    assert task["name"] == "Buy milk"

    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "Captured/abc"
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2 — Idempotency via derived_from per-item GraphQL point lookup
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_per_item_graphql_skip():
    """Per-item GraphQL query returns matching Entity → skip extraction."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(
        captured_docs=[note],
        graphql_entity_by_source={
            "Captured/abc": [
                {"_id": "Task/existing"},
            ],
        },
    )

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert not extract_called
    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"
    assert replaced["@id"] == "Captured/abc"

    tdb.graphql.assert_called()
    call_kwargs = tdb.graphql.call_args.kwargs
    assert call_kwargs["variables"] == {"src": "Captured/abc"}
    assert "derived_from" in tdb.graphql.call_args[0][0]


# ---------------------------------------------------------------------------
# Test 2b — Per-item query: no match → extraction proceeds
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_per_item_graphql_no_match():
    """Per-item GraphQL query returns empty → extraction proceeds normally."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(
        captured_docs=[note],
        graphql_entity_by_source={},
    )

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="new task",
            confidence=0.95,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2c — GraphQL failure → fallback to cached class scan
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_graphql_failure_fallback_cached_scan():
    """First per-item GraphQL fails → fallback class scan built once, cached."""
    note1 = _captured_text("Captured/abc", "Already derived")
    note2 = _captured_text("Captured/def", "New note")
    existing_task = {
        "@id": "Task/existing",
        "@type": "Task",
        "name": "Derived task",
        "status": "open",
        "derived_from": ["Captured/abc"],
    }
    tdb = _fake_tdb(
        captured_docs=[note1, note2],
        tasks=[existing_task],
        graphql_error_first_call=True,
    )

    extract_count = 0

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_count
        extract_count += 1
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert extract_count == 1

    tdb.graphql.assert_called()

    assert tdb.replace_document.call_count == 2
    assert tdb.replace_document.call_args_list[0][0][0]["@id"] == "Captured/abc"
    assert tdb.replace_document.call_args_list[0][0][0]["status"] == "processed"
    assert tdb.replace_document.call_args_list[1][0][0]["@id"] == "Captured/def"
    assert tdb.replace_document.call_args_list[1][0][0]["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2d — Idempotency path logged at INFO once per cycle
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_path_logged_graphql():
    """Verify INFO log records the graphql_point_lookup path once per cycle."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(
        captured_docs=[note],
        graphql_entity_by_source={},
    )

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    from structlog.testing import capture_logs
    with capture_logs() as captured:
        await pipeline.run_cycle()

    path_logs = [
        e for e in captured
        if e.get("event") == "idempotency_path"
    ]
    assert len(path_logs) == 1
    assert path_logs[0]["method"] == "graphql_point_lookup"


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_path_logged_fallback():
    """Verify WARNING on graphql failure + INFO for class_scan_fallback path."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(
        captured_docs=[note],
        graphql_error=True,
        documents={"Task": []},
    )

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    from structlog.testing import capture_logs
    with capture_logs() as captured:
        await pipeline.run_cycle()

    warning_logs = [
        e for e in captured
        if e.get("event") == "idempotency_graphql_failed"
    ]
    assert len(warning_logs) == 1
    assert warning_logs[0]["fallback"] == "class_scan"
    assert warning_logs[0]["error"] == "GraphQL error"
    assert warning_logs[0]["status"] == 500

    path_logs = [
        e for e in captured
        if e.get("event") == "idempotency_path"
    ]
    assert len(path_logs) == 1
    assert path_logs[0]["method"] == "class_scan_fallback"


@requires_extensions
@pytest.mark.asyncio
async def test_idempotency_graphql_null_entity_falls_back():
    """GraphQL returns ``{"Entity": null}`` → fallback to class scan, not reprocessed forever."""
    note = _captured_text("Captured/abc", "Buy milk")
    existing_task = {
        "@id": "Task/existing",
        "@type": "Task",
        "name": "Derived task",
        "status": "open",
        "derived_from": ["Captured/abc"],
    }
    tdb = _fake_tdb(
        captured_docs=[note],
        tasks=[existing_task],
        graphql_entity_null=True,
    )

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    from structlog.testing import capture_logs
    with capture_logs() as captured:
        await pipeline.run_cycle()

    # Extraction should NOT be called (idempotency via class-scan fallback found it)
    assert not extract_called

    # Status should be flipped to processed (already extracted)
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"
    assert replaced["@id"] == "Captured/abc"

    # Warning about null entity should be logged
    null_warnings = [
        e for e in captured
        if e.get("event") == "idempotency_graphql_null_entity"
    ]
    assert len(null_warnings) == 1

    # Path should be logged as class_scan_fallback
    path_logs = [
        e for e in captured
        if e.get("event") == "idempotency_path"
    ]
    assert len(path_logs) == 1
    assert path_logs[0]["method"] == "class_scan_fallback"


# ---------------------------------------------------------------------------
# Test 3 — Nothing actionable
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_nothing_actionable_flips_to_processed():
    """Extract returns empty proposals → no insert, status → processed."""
    note = _captured_text("Captured/abc", "Nothing to do.")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[],
            reasoning="Nothing actionable.",
            confidence=0.99,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 4 — TdbError retry
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_tdberror_retry_with_error_feedback():
    """Insert fails with TdbError on first attempt, succeeds on second."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(captured_docs=[note])

    error_body = "SchemaCheckFailure: bad field"
    call_count = 0

    async def insert_stub(docs, branch="main", message="ingestd"):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TdbError(400, error_body)
        return ["terminusdb:///data/Task/new1"]

    tdb.insert_documents.side_effect = insert_stub

    extract_calls = []

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        extract_calls.append(error_feedback)
        return ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Buy milk",
                    description=None,
                    priority=None,
                    estimated_duration=None,
                    due_date=None,
                )
            ],
            reasoning="retry",
            confidence=0.9,
        )

    settings = _settings(max_llm_retries=3)
    pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert len(extract_calls) == 2
    assert extract_calls[0] is None
    assert extract_calls[1] == error_body

    tdb.replace_document.assert_called()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 5 — Retry exhaustion
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_retry_exhaustion_flips_to_failed():
    """Insert always raises TdbError → failed, next doc still processed."""
    note1 = _captured_text("Captured/abc", "First note")
    note2 = _captured_text("Captured/def", "Second note")
    tdb = _fake_tdb(captured_docs=[note1, note2])

    insert_call = 0

    async def insert_stub(docs, branch="main", message="ingestd"):
        nonlocal insert_call
        insert_call += 1
        if insert_call <= 2:
            raise TdbError(400, "persistent failure")
        return ["terminusdb:///data/Task/ok"]

    tdb.insert_documents.side_effect = insert_stub

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Task",
                    description=None,
                    priority=None,
                    estimated_duration=None,
                    due_date=None,
                )
            ],
            reasoning="trying",
            confidence=0.5,
        )

    settings = _settings(max_llm_retries=2)
    pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert tdb.replace_document.call_count == 2
    call_args_list = tdb.replace_document.call_args_list
    assert call_args_list[0][0][0]["@id"] == "Captured/abc"
    assert call_args_list[0][0][0]["status"] == "failed"
    assert call_args_list[1][0][0]["@id"] == "Captured/def"
    assert call_args_list[1][0][0]["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 6 — dry_run
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_dry_run_no_inserts_no_flips():
    """dry_run mode: extract returns proposals → NO writes."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Buy milk",
                    description=None,
                    priority=None,
                    estimated_duration=None,
                    due_date=None,
                )
            ],
            reasoning="task",
            confidence=0.9,
        )

    settings = _settings(dry_run=True)
    pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7 — ensure_entity: person linked (known), known location
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_ensure_entity_links_known_person_and_location():
    """PersonProposal matching known person → dropped. EventProposal → ensure_entity."""
    note = _captured_text("Captured/abc", "Meet Bob at Office")
    tdb = _fake_tdb(
        captured_docs=[note],
        people=[{"@id": "Person/bob", "name": "Bob Smith"}],
        locations=[{"@id": "Location/office", "name": "Office"}],
    )

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                PersonProposal(name="Bob Smith", email=None, phone=None),
                EventProposal(
                    name="Meeting",
                    description=None,
                    start_datetime=None,
                    end_datetime=None,
                    location_name="Office",
                ),
            ],
            reasoning="person + event",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]
    event_docs = [d for d in docs if d.get("@type") == "Event"]
    assert len(event_docs) == 1
    event = event_docs[0]
    assert event["location"] == "Location/office"


# ---------------------------------------------------------------------------
# Test 8 — ensure_entity: new location created in same batch
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_ensure_entity_creates_new_location_in_same_batch():
    """EventProposal with unknown location_name → Location created in same batch."""
    note = _captured_text("Captured/abc", "Meeting at NewPlace")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                EventProposal(
                    name="Meeting",
                    description=None,
                    start_datetime=None,
                    end_datetime=None,
                    location_name="NewPlace",
                ),
            ],
            reasoning="event with new location",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]

    loc_docs = [d for d in docs if d.get("@type") == "Location"]
    event_docs = [d for d in docs if d.get("@type") == "Event"]

    assert len(loc_docs) == 1
    assert loc_docs[0]["name"] == "NewPlace"
    assert "@id" in loc_docs[0]

    assert len(event_docs) == 1
    assert event_docs[0]["location"] == loc_docs[0]["@id"]

    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 8b — same new entity mentioned twice → one doc in batch (dedup)
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_ensure_entity_dedup_two_mentions_same_cycle():
    """Two event proposals both referencing same new location → one Location doc."""
    note = _captured_text("Captured/abc", "Meeting at NewPlace and then NewPlace again")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                EventProposal(
                    name="Meeting A",
                    description=None,
                    start_datetime=None,
                    end_datetime=None,
                    location_name="NewPlace",
                ),
                EventProposal(
                    name="Meeting B",
                    description=None,
                    start_datetime=None,
                    end_datetime=None,
                    location_name="NewPlace",
                ),
            ],
            reasoning="two events, same new location",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]

    loc_docs = [d for d in docs if d.get("@type") == "Location"]
    event_docs = [d for d in docs if d.get("@type") == "Event"]

    assert len(loc_docs) == 1
    assert loc_docs[0]["name"] == "NewPlace"

    assert len(event_docs) == 2
    assert event_docs[0]["location"] == loc_docs[0]["@id"]
    assert event_docs[1]["location"] == loc_docs[0]["@id"]


# ---------------------------------------------------------------------------
# Test 9 — Unexpected exception
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_unexpected_exception_flips_to_failed_next_doc_still_processed():
    """Extract raises RuntimeError on first doc → failed, second doc processed."""
    note1 = _captured_text("Captured/abc", "First note")
    note2 = _captured_text("Captured/def", "Second note")
    tdb = _fake_tdb(captured_docs=[note1, note2])

    call_count = 0

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM crash")
        return ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Task",
                    description=None,
                    priority=None,
                    estimated_duration=None,
                    due_date=None,
                )
            ],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert tdb.replace_document.call_count == 2
    call_args_list = tdb.replace_document.call_args_list
    assert call_args_list[0][0][0]["status"] == "failed"
    assert call_args_list[0][0][0]["@id"] == "Captured/abc"
    assert call_args_list[1][0][0]["status"] == "processed"
    assert call_args_list[1][0][0]["@id"] == "Captured/def"


# ---------------------------------------------------------------------------
# Test 10 — Cycle-level resilience (run_cycle_safe catches exception)
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_run_cycle_safe_catches_exception():
    """When run_cycle raises, run_cycle_safe logs and returns False."""
    from ingestd.main import run_cycle_safe

    tdb = _fake_tdb()

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    tdb.get_documents.side_effect = RuntimeError("context fetch explosion")

    result = await run_cycle_safe(pipeline, None)
    assert result is False


@requires_extensions
@pytest.mark.asyncio
async def test_run_cycle_safe_returns_true_on_success():
    """When run_cycle succeeds, run_cycle_safe returns True."""
    from ingestd.main import run_cycle_safe

    note = _captured_text("Captured/abc", "Simple")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    result = await run_cycle_safe(pipeline, None)
    assert result is True


# ---------------------------------------------------------------------------
# Test 11 — Exact retry accounting
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_exact_retry_accounting_max_retries_3():
    """max_llm_retries=3, insert always raises TdbError → extract called 3x, status=failed."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(captured_docs=[note])
    tdb.insert_documents.side_effect = TdbError(400, "boom")

    extract_calls = []

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        extract_calls.append(error_feedback)
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="trying",
            confidence=0.5,
        )

    settings = _settings(max_llm_retries=3)
    pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert len(extract_calls) == 3
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "failed"
    assert replaced["@id"] == "Captured/abc"


# ---------------------------------------------------------------------------
# Test 12 — Captured audio path
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_captured_audio_path():
    """Captured audio with status=transcribed → transcription+reference_dt used, status→processed."""
    audio = _captured_audio("Captured/xyz", "Call Bob tomorrow at noon")
    tdb = _fake_tdb(captured_docs=[audio])

    received_args = {}

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        received_args["text"] = text
        received_args["reference_dt"] = reference_dt
        received_args["context_block"] = context_block
        return ExtractionResult(
            proposals=[TaskProposal(name="Call Bob")],
            reasoning="call",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert received_args["text"] == "Call Bob tomorrow at noon"

    from datetime import datetime, timezone
    expected_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
    assert received_args["reference_dt"] == expected_dt

    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "Captured/xyz"
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 13 — dry_run positive assertions
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_dry_run_extract_called_but_zero_writes():
    """dry_run=True: extract IS called, reads happen, zero insert/replace calls."""
    note = _captured_text("Captured/abc", "Buy milk")
    tdb = _fake_tdb(captured_docs=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="task",
            confidence=0.9,
        )

    settings = _settings(dry_run=True)
    pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.get_documents.assert_called()
    tdb.get_documents_by_status.assert_called()
    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_not_called()


# ---------------------------------------------------------------------------
# Test 14 — Missing captured_at on captured doc
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_missing_captured_at_logs_warning_defaults_now():
    """Captured text doc without captured_at → warning logged, extraction runs, processed."""
    note = {
        "@id": "Captured/nodate",
        "@type": "Captured",
        "content": "Buy milk",
        "content_type": "text/plain",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    tdb = _fake_tdb(captured_docs=[note])

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        from datetime import datetime
        assert isinstance(reference_dt, datetime)
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="ok",
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    from structlog.testing import capture_logs
    with capture_logs() as captured_events:
        await pipeline.run_cycle()

    assert extract_called is True
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"

    warning_events = [
        e for e in captured_events if e.get("event") == "reference_datetime_missing"
    ]
    assert len(warning_events) >= 1


# ---------------------------------------------------------------------------
# Test 15 — should_stop set after first doc
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_should_stop_after_first_doc():
    """should_stop set after first doc → second doc not processed."""
    note1 = _captured_text("Captured/abc", "First")
    note2 = _captured_text("Captured/def", "Second")
    tdb = _fake_tdb(captured_docs=[note1, note2])

    call_count = [0]

    async def extract_with_stop(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        call_count[0] += 1
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning=text,
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=extract_with_stop)

    stop = asyncio.Event()

    orig_process = pipeline._process_one

    async def _process_with_stop(doc, src, index, context_block):
        result = await orig_process(doc, src, index, context_block)
        stop.set()
        return result

    pipeline._process_one = _process_with_stop

    await pipeline.run_cycle(should_stop=stop)

    assert tdb.replace_document.call_count == 1
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "Captured/abc"


# ---------------------------------------------------------------------------
# Test 16 — build_documents mid-batch isolation
# ---------------------------------------------------------------------------


@requires_extensions
@pytest.mark.asyncio
async def test_build_documents_mid_batch_isolation():
    """One plugin proposal raises during build → batch partial, process fails retry."""
    from pydantic import BaseModel

    class _GoodProposal(BaseModel):
        kind: str = "good"
        name: str

    class _BadProposal(BaseModel):
        kind: str = "bad"
        name: str

    class _IsolationPlugin:
        name = "isolation_test"
        requires: list = []
        produces: list[str] = []

        def proposal_models(self):
            return [_GoodProposal, _BadProposal]

        def prompt_snippet(self):
            return ""

        async def linking_context(self, tdb, *, index=None, branch=""):
            return ""

        async def build_documents(self, proposal, ctx):
            if proposal.kind == "bad":
                raise RuntimeError("build explosion")
            return [{"@type": "Good", "name": proposal.name}]

    isolation_ctx = build_extraction_context([_IsolationPlugin()])
    note = _captured_text("Captured/abc", "Test isolation")
    tdb = _fake_tdb(captured_docs=[note])

    async def insert_stub(docs, branch="main", message="ingestd"):
        return [f"terminusdb:///data/{d['@type']}/new" for d in docs]

    tdb.insert_documents.side_effect = insert_stub

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        return ExtractionResult(
            proposals=[
                _GoodProposal(kind="good", name="Keep me"),
                _BadProposal(kind="bad", name="Drop me"),
                _GoodProposal(kind="good", name="Also keep"),
            ],
            reasoning="isolation test",
            confidence=0.9,
        )

    settings = _settings(max_llm_retries=2)
    pipeline = Pipeline(
        tdb=tdb, agent=None, settings=settings,
        source_plugins=_SOURCES,
        extraction_ctx=isolation_ctx,
        extract_fn=fake_extract,
    )

    await pipeline.run_cycle()

    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "failed"
    assert replaced["@id"] == "Captured/abc"


# ---------------------------------------------------------------------------
# Test 17 — Empty text is skipped (audio capture at status=new not yet transcribed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_text_skipped_no_status_flip():
    """Captured doc with no content at status=new → empty text → skipped, no status flip."""
    from unittest.mock import AsyncMock

    # An audio capture at "new" status (not yet transcribed, transcription is None)
    audio_new = {
        "@id": "Captured/aud_new",
        "@type": "Captured",
        "content_type": "audio/wav",
        "file_name": "rec.wav",
        "transcription": None,
        "captured_at": "2026-07-05T14:00:00Z",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    tdb = AsyncMock()
    tdb.get_documents = AsyncMock(return_value=[])
    tdb.get_documents_by_status = AsyncMock(return_value=[audio_new])
    tdb.insert_documents = AsyncMock()
    tdb.replace_document = AsyncMock()
    tdb.graphql = AsyncMock(return_value={"Entity": []})

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    from ingestd.sources import CapturedTextSource
    src = CapturedTextSource()

    # The text source's text() returns empty string for audio at "new"
    assert src.text(audio_new) == ""

    # Create pipeline with this single source
    if _EXTRACTION_CTX is None:
        pytest.skip("extension pending kernel migration")
    pipeline = Pipeline(
        tdb=tdb, agent=None, settings=_settings(),
        source_plugins=[src],
        extraction_ctx=_EXTRACTION_CTX,
        extract_fn=fake_extract,
    )

    await pipeline.run_cycle()

    # Extraction should NOT be called (empty text guard)
    assert not extract_called
    # Status should NOT be flipped
    tdb.replace_document.assert_not_called()
