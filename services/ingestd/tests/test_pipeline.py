"""Tests for ingestd.pipeline — no network, mock TdbClient.

Covers the generic pipeline: index from produces, ensure_entity batching,
one insert_documents per captured item, idempotency via derived_from,
status flip after success, empty-text guard.
"""

from __future__ import annotations

import asyncio
from typing import Any
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
    from firnline_ext_time_management.extract import (
        EventProposal,
        PersonProposal,
        TaskProposal,
        TimeManagementPlugin,
    )
    _planning_ok = True
except ImportError:
    _planning_ok = False

try:
    from firnline_ext_address_book.extract import AddressBookLinkingPlugin
    _ab_ok = True
except ImportError:
    _ab_ok = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Shared extraction context for all pipeline tests
if _planning_ok and _ab_ok:
    _PLANNING_PLUGIN = TimeManagementPlugin()
    _AB_PLUGIN = AddressBookLinkingPlugin()
    _EXTRACTION_CTX = build_extraction_context([_PLANNING_PLUGIN, _AB_PLUGIN])
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
    tdb.replace_documents = AsyncMock()
    tdb.graphql = AsyncMock()
    tdb.get_document = AsyncMock()

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

    # Flat IRI→doc lookup for get_document (merges all document types)
    _all_docs: dict[str, dict] = {}
    for docs in doc_map.values():
        for d in docs:
            _all_docs[d.get("@id", "")] = d

    async def _get_document(iri: str, branch: str = "main"):
        # Try the short IRI directly, and also with and without the prefix
        from firnline_core.tdb import short_iri
        key = short_iri(iri)
        doc = _all_docs.get(key)
        if doc is None:
            raise TdbError(404, f"Document not found: {iri}")
        return doc

    tdb.get_document.side_effect = _get_document

    # Track inserted/replaced docs so merge-update can find them
    async def _replace_docs(docs, branch="main", message="ingestd", *, create=False):
        for d in docs:
            _all_docs[d.get("@id", "")] = d
        return [f"terminusdb:///data/{d.get('@type', 'Unknown')}/{d.get('@id', 'new')}" for d in docs]

    tdb.replace_documents.side_effect = _replace_docs

    # Keep insert_documents for backward compat in tests that mock it directly
    async def _insert_docs(docs, branch="main", message="ingestd"):
        for d in docs:
            _all_docs[d.get("@id", "")] = d
        return [f"terminusdb:///data/{d.get('@type', 'Unknown')}/{d.get('@id', 'new')}" for d in docs]

    tdb.insert_documents.side_effect = _insert_docs

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

    tdb.replace_documents.assert_called_once()
    call_args = tdb.replace_documents.call_args
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
    tdb.replace_documents.assert_not_called()
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"
    assert replaced["@id"] == "Captured/abc"

    tdb.graphql.assert_called()
    call_kwargs = tdb.graphql.call_args.kwargs
    assert call_kwargs["variables"] == {"src": "Captured/abc"}
    assert "derived_from" in tdb.graphql.call_args[0][0]
    assert "someHave" not in tdb.graphql.call_args[0][0]
    assert "derived_from: { eq: $src }" in tdb.graphql.call_args[0][0]


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

    tdb.replace_documents.assert_called_once()
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

    tdb.replace_documents.assert_not_called()
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

    async def replace_stub(docs, branch="main", message="ingestd", *, create=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TdbError(400, error_body)
        return ["terminusdb:///data/Task/new1"]

    tdb.replace_documents.side_effect = replace_stub

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

    async def replace_stub(docs, branch="main", message="ingestd", *, create=False):
        nonlocal insert_call
        insert_call += 1
        if insert_call <= 2:
            raise TdbError(400, "persistent failure")
        return ["terminusdb:///data/Task/ok"]

    tdb.replace_documents.side_effect = replace_stub

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

    tdb.replace_documents.assert_not_called()
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

    tdb.replace_documents.assert_called_once()
    docs = tdb.replace_documents.call_args[0][0]
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

    tdb.replace_documents.assert_called_once()
    docs = tdb.replace_documents.call_args[0][0]

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

    tdb.replace_documents.assert_called_once()
    docs = tdb.replace_documents.call_args[0][0]

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
    tdb.replace_documents.side_effect = TdbError(400, "boom")

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
    tdb.replace_documents.assert_not_called()
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

    async def replace_stub(docs, branch="main", message="ingestd", *, create=False):
        return [f"terminusdb:///data/{d['@type']}/new" for d in docs]

    tdb.replace_documents.side_effect = replace_stub

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


@pytest.mark.asyncio
async def test_empty_text_capture_rejected():
    """Plain-text Captured doc with empty content → terminal "rejected" status."""
    empty_note = {
        "@id": "Captured/empty",
        "@type": "Captured",
        "content": "   ",
        "content_type": "text/plain",
        "captured_at": "2026-07-05T14:00:00Z",
        "status": "new",
    }
    tdb = _fake_tdb(captured_docs=[empty_note])

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    if _EXTRACTION_CTX is None:
        pytest.skip("extension pending kernel migration")
    pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

    from structlog.testing import capture_logs
    with capture_logs() as captured:
        await pipeline.run_cycle()

    # Extraction should NOT be called (empty text guard)
    assert not extract_called
    # Status should be flipped to "rejected"
    tdb.replace_document.assert_called_once()
    rejected = tdb.replace_document.call_args[0][0]
    assert rejected["@id"] == "Captured/empty"
    assert rejected["status"] == "rejected"
    assert "Empty or whitespace-only text content" in rejected.get("result_detail", "")

    # Verify the rejected log event
    rejected_logs = [e for e in captured if e.get("event") == "empty_text_rejected"]
    assert len(rejected_logs) == 1


@pytest.mark.asyncio
async def test_audio_awaiting_transcription_still_skipped():
    """Audio capture with no transcription → skipped, NOT rejected (preserves waiting behavior)."""
    audio_new = {
        "@id": "Captured/aud_waiting",
        "@type": "Captured",
        "content_type": "audio/wav",
        "file_name": "rec.wav",
        "transcription": None,
        "captured_at": "2026-07-05T14:00:00Z",
        "status": "new",
    }
    tdb = _fake_tdb(captured_docs=[audio_new])

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    # Use CapturedTextSource (which picks up status="new" docs)
    from ingestd.sources import CapturedTextSource
    src = CapturedTextSource()
    assert src.text(audio_new) == ""  # no content field → empty text

    if _EXTRACTION_CTX is None:
        pytest.skip("extension pending kernel migration")
    pipeline = Pipeline(
        tdb=tdb, agent=None, settings=_settings(),
        source_plugins=[src],
        extraction_ctx=_EXTRACTION_CTX,
        extract_fn=fake_extract,
    )

    from structlog.testing import capture_logs
    with capture_logs() as captured:
        await pipeline.run_cycle()

    # Extraction should NOT be called (empty text guard)
    assert not extract_called
    # Status should NOT be flipped — audio awaiting transcription stays
    tdb.replace_document.assert_not_called()

    # Verify the skip log event
    skip_logs = [e for e in captured if e.get("event") == "empty_text_skipped"]
    assert len(skip_logs) >= 1
    assert any(e.get("reason") == "audio_awaiting_transcription" for e in skip_logs)


# ---------------------------------------------------------------------------
# Entity-update ("fetch+merge") path tests
# ---------------------------------------------------------------------------


class TestEnsureEntityUpdatePath:
    """Tests for the new entity-update behaviour in _make_ensure_entity."""

    @pytest.mark.asyncio
    async def test_existing_entity_runs_factory_and_appends_to_batch(self):
        """Index hit now calls factory, stamps @id, and appends to batch + existing_ids."""
        from ingestd.linking import EntityIndex

        tdb = _fake_tdb(people=[{"@id": "Person/bob", "name": "Bob Smith"}])
        pipeline = _make_pipeline(tdb)

        index = EntityIndex()
        index.register("Person", "Bob Smith", "Person/bob")

        batch: list[dict[str, Any]] = []
        existing_ids: set[str] = set()
        ensure = pipeline._make_ensure_entity(index, batch, existing_ids)

        factory_called = False

        def factory():
            nonlocal factory_called
            factory_called = True
            return {
                "@type": "Person",
                "name": "Bob Smith",
                "derived_from": ["Captured/new"],
                "provenance": {"agent": "test"},
            }

        iri = await ensure("Person", "Bob Smith", factory)

        assert factory_called
        assert iri == "Person/bob"
        assert len(batch) == 1
        assert batch[0]["@id"] == "Person/bob"
        assert batch[0]["@type"] == "Person"
        assert "Person/bob" in existing_ids

    @pytest.mark.asyncio
    async def test_existing_entity_lambda_none_returns_iri_without_batch(self):
        """Lookup-only pattern (lambda: None) still works — no update triggered."""
        from ingestd.linking import EntityIndex

        tdb = _fake_tdb(people=[{"@id": "Person/bob", "name": "Bob Smith"}])
        pipeline = _make_pipeline(tdb)

        index = EntityIndex()
        index.register("Person", "Bob Smith", "Person/bob")

        batch: list[dict[str, Any]] = []
        existing_ids: set[str] = set()
        ensure = pipeline._make_ensure_entity(index, batch, existing_ids)

        iri = await ensure("Person", "Bob Smith", lambda: None)

        assert iri == "Person/bob"
        assert len(batch) == 0
        assert "Person/bob" not in existing_ids

    @pytest.mark.asyncio
    async def test_miss_still_creates_regression(self):
        """Unknown entity still goes through the create path."""
        from ingestd.linking import EntityIndex

        tdb = _fake_tdb()
        pipeline = _make_pipeline(tdb)

        index = EntityIndex()
        batch: list[dict[str, Any]] = []
        existing_ids: set[str] = set()
        ensure = pipeline._make_ensure_entity(index, batch, existing_ids)

        iri = await ensure(
            "Location",
            "NewPlace",
            lambda: {"@type": "Location", "name": "NewPlace"},
        )

        assert iri is not None
        assert iri.startswith("Location/")
        assert len(batch) == 1
        assert batch[0]["@type"] == "Location"
        assert batch[0]["name"] == "NewPlace"
        assert iri not in existing_ids  # create path does NOT add to existing_ids

    @pytest.mark.asyncio
    async def test_existing_entity_dedup_two_references(self):
        """Two proposals referencing same existing entity → one batch entry, merged."""
        from ingestd.linking import EntityIndex

        tdb = _fake_tdb(people=[{"@id": "Person/bob", "name": "Bob Smith"}])
        pipeline = _make_pipeline(tdb)

        index = EntityIndex()
        index.register("Person", "Bob Smith", "Person/bob")

        batch: list[dict[str, Any]] = []
        existing_ids: set[str] = set()
        ensure = pipeline._make_ensure_entity(index, batch, existing_ids)

        # First reference
        iri1 = await ensure(
            "Person", "Bob Smith",
            lambda: {"@type": "Person", "name": "Bob Smith", "email": "bob@example.com", "derived_from": ["Captured/src1"]},
        )
        # Second reference — should merge
        iri2 = await ensure(
            "Person", "Bob Smith",
            lambda: {"@type": "Person", "name": "Bob Smith", "phone": "555-1234", "derived_from": ["Captured/src2"]},
        )

        assert iri1 == "Person/bob"
        assert iri2 == "Person/bob"
        assert len(batch) == 1  # deduplicated
        merged = batch[0]
        assert merged["email"] == "bob@example.com"
        assert merged["phone"] == "555-1234"
        assert "Captured/src1" in merged["derived_from"]
        assert "Captured/src2" in merged["derived_from"]
        assert "Person/bob" in existing_ids


class TestMergeUpdate:
    """Tests for _merge_update fetch+merge+replace logic."""

    @pytest.mark.asyncio
    async def test_merge_update_preserves_provenance(self):
        """_merge_update keeps the existing doc's provenance."""
        tdb = _fake_tdb(people=[{
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob Old",
            "provenance": {"agent": "initial", "at": "2020-01-01T00:00:00Z", "method": "manual"},
        }])
        pipeline = _make_pipeline(tdb)

        new_doc = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob New",
            "provenance": {"agent": "ingestd"},  # should be ignored
            "email": "bob@example.com",
        }

        merged = await pipeline._merge_update(new_doc, "main", "Captured/src")

        tdb.get_document.assert_called_once_with("Person/bob", branch="main")
        assert merged["provenance"] == {"agent": "initial", "at": "2020-01-01T00:00:00Z", "method": "manual"}  # preserved
        assert merged["name"] == "Bob New"  # overwritten
        assert merged["email"] == "bob@example.com"  # added

    @pytest.mark.asyncio
    async def test_merge_update_unions_derived_from_and_aliases(self):
        """_merge_update unions derived_from and aliases lists."""
        tdb = _fake_tdb(people=[{
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "derived_from": ["Captured/old1"],
            "aliases": ["Bobby"],
            "provenance": {"agent": "test"},
        }])
        pipeline = _make_pipeline(tdb)

        new_doc = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "derived_from": ["Captured/old1", "Captured/new1"],
            "aliases": ["Bobby", "Robert"],
        }

        merged = await pipeline._merge_update(new_doc, "main", "Captured/src")

        assert merged["derived_from"] == ["Captured/old1", "Captured/new1"]
        assert merged["aliases"] == ["Bobby", "Robert"]

    @pytest.mark.asyncio
    async def test_merge_update_skips_none_and_empty_values(self):
        """_merge_update does not clobber existing data with None or empty list."""
        tdb = _fake_tdb(people=[{
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "email": "old@example.com",
            "phone": "555-0000",
            "provenance": {"agent": "test"},
        }])
        pipeline = _make_pipeline(tdb)

        new_doc = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "email": None,  # should be skipped
            "phone": [],  # should be skipped
        }

        merged = await pipeline._merge_update(new_doc, "main", "Captured/src")

        assert merged["email"] == "old@example.com"  # preserved
        assert merged["phone"] == "555-0000"  # preserved

    @pytest.mark.asyncio
    async def test_merge_update_404_falls_back_to_create(self):
        """_merge_update returns new_doc as-is when get_document 404s (stale index)."""
        tdb = _fake_tdb()  # no docs → get_document will 404
        pipeline = _make_pipeline(tdb)

        new_doc = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
        }

        merged = await pipeline._merge_update(new_doc, "main", "Captured/inbox42")

        # Returns new_doc as-is — no merge, no exception
        assert merged is new_doc
        tdb.get_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_update_deep_merges_subdocuments(self):
        """Sub-documents are deep-merged: existing keys survive if absent from factory."""
        tdb = _fake_tdb(people=[{
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "contact": {"email": "a@b.c", "phone": "123"},
            "provenance": {"agent": "test"},
        }])
        pipeline = _make_pipeline(tdb)

        new_doc = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob",
            "contact": {"email": "new@b.c", "domicile": "Location/x"},
        }

        merged = await pipeline._merge_update(new_doc, "main", "Captured/src")

        assert merged["contact"]["email"] == "new@b.c"  # overridden
        assert merged["contact"]["phone"] == "123"      # preserved
        assert merged["contact"]["domicile"] == "Location/x"  # added


class TestProcessOneSplit:
    """Tests for the create-vs-update split in _process_one."""

    @requires_extensions
    @pytest.mark.asyncio
    async def test_mixed_create_and_update_routes_correctly(self):
        """Batch with one new + one existing doc: insert for new, merge for existing."""
        note = _captured_text("Captured/abc", "Bob works at NewOffice")
        existing_person = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob Smith",
            "provenance": {"agent": "manual", "at": "2020-01-01T00:00:00Z", "method": "manual"},
        }
        tdb = _fake_tdb(
            captured_docs=[note],
            people=[existing_person],
        )

        async def fake_extract(
            agent, text, reference_dt, context_block, error_feedback=None,
            extraction_ctx=None,
        ):
            return ExtractionResult(
                proposals=[
                    # Event with NEW location → should create Location + Event
                    EventProposal(
                        name="Meeting",
                        description=None,
                        start_datetime=None,
                        end_datetime=None,
                        location_name="NewOffice",
                    ),
                ],
                reasoning="event with new location",
                confidence=0.9,
            )

        pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

        await pipeline.run_cycle()

        # replace_documents should be called atomically with create=True
        tdb.replace_documents.assert_called_once()
        docs = tdb.replace_documents.call_args[0][0]
        call_kwargs = tdb.replace_documents.call_args.kwargs
        assert call_kwargs.get("create") is True
        doc_types = [d.get("@type") for d in docs]
        assert "Event" in doc_types
        assert "Location" in doc_types

        # replace_document called for: status flip (1x)
        # Verify the status flip has processed status
        status_flips = [
            call for call in tdb.replace_document.call_args_list
            if call[0][0].get("status") == "processed"
        ]
        assert len(status_flips) == 1

    @requires_extensions
    @pytest.mark.asyncio
    async def test_existing_person_gets_merged_update(self):
        """PersonProposal for known Person → factory runs, doc goes to update path."""
        note = _captured_text("Captured/abc", "Bob Smith has new email bob@test.com")
        existing_person = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob Smith",
            "provenance": {"agent": "manual", "at": "2020-01-01T00:00:00Z", "method": "manual"},
        }
        tdb = _fake_tdb(
            captured_docs=[note],
            people=[existing_person],
        )

        async def fake_extract(
            agent, text, reference_dt, context_block, error_feedback=None,
            extraction_ctx=None,
        ):
            return ExtractionResult(
                proposals=[
                    PersonProposal(name="Bob Smith", email="bob@test.com", phone=None),
                ],
                reasoning="person update",
                confidence=0.9,
            )

        pipeline = _make_pipeline(tdb, extract_fn=fake_extract)

        await pipeline.run_cycle()

        # The Person doc should be merged+updated atomically via replace_documents
        tdb.get_document.assert_called()  # called by _merge_update
        # replace_documents should have been called with all docs + create=True
        tdb.replace_documents.assert_called_once()
        call_kwargs = tdb.replace_documents.call_args.kwargs
        assert call_kwargs.get("create") is True

    @requires_extensions
    @pytest.mark.asyncio
    async def test_dry_run_reports_creates_and_updates(self):
        """dry_run logs both creates= and updates= counts."""
        note = _captured_text("Captured/abc", "Bob works at Office")
        existing_person = {
            "@id": "Person/bob",
            "@type": "Person",
            "name": "Bob Smith",
            "provenance": {"agent": "manual", "at": "2020-01-01T00:00:00Z", "method": "manual"},
        }
        existing_location = {
            "@id": "Location/office",
            "@type": "Location",
            "name": "Office",
            "provenance": {"agent": "manual", "at": "2020-01-01T00:00:00Z", "method": "manual"},
        }
        tdb = _fake_tdb(
            captured_docs=[note],
            people=[existing_person],
            locations=[existing_location],
        )

        async def fake_extract(
            agent, text, reference_dt, context_block, error_feedback=None,
            extraction_ctx=None,
        ):
            return ExtractionResult(
                proposals=[
                    PersonProposal(name="Bob Smith", email="bob@test.com", phone=None),
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

        settings = _settings(dry_run=True)
        pipeline = _make_pipeline(tdb, settings=settings, extract_fn=fake_extract)

        from structlog.testing import capture_logs
        with capture_logs() as captured:
            await pipeline.run_cycle()

        dry_run_logs = [e for e in captured if e.get("event") == "dry_run_would_insert"]
        assert len(dry_run_logs) == 1
        log_entry = dry_run_logs[0]
        assert "creates" in log_entry
        assert "updates" in log_entry
        # Person and Location are existing → updates; Event is new → create
        assert log_entry["updates"] >= 2  # Person + Location
        assert log_entry["creates"] >= 1  # Event
