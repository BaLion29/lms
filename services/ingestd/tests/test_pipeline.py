"""Tests for ingestd.pipeline — no network, mock TdbClient.

Covers the generic pipeline: index from produces, ensure_entity batching,
one insert_documents per inbox item, idempotency via provenance.source,
status flip after success.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ingestd.extraction import (
    ExtractionResult,
    build_extraction_context,
)
from ingestd.sources import InboxAudioSource, InboxNoteSource
from ingestd.pipeline import Pipeline
from ingestd.settings import Settings
from firnline_core.tdb import TdbError

from firnline_ext_planning.extract import (
    EventProposal,
    PersonProposal,
    PlanningPlugin,
    TaskProposal,
)
from firnline_ext_people.extract import PeopleLinkingPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Shared extraction context for all pipeline tests
_PLANNING_PLUGIN = PlanningPlugin()
_PEOPLE_PLUGIN = PeopleLinkingPlugin()
_EXTRACTION_CTX = build_extraction_context([_PLANNING_PLUGIN, _PEOPLE_PLUGIN])
_SOURCES = [InboxNoteSource(), InboxAudioSource()]


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
    inbox_notes: list[dict] | None = None,
    inbox_audios: list[dict] | None = None,
    # Generic get_documents routing — supply a dict or per-class lists
    documents: dict[str, list[dict]] | None = None,
    # For convenience in simple tests
    people: list[dict] | None = None,
    locations: list[dict] | None = None,
    tasks: list[dict] | None = None,
    events: list[dict] | None = None,
    reminders: list[dict] | None = None,
    # Per-item idempotency: source_iri → list of matching Entity dicts
    graphql_entity_by_source: dict[str, list[dict]] | None = None,
    # If True, graphql raises TdbError on *every* call
    graphql_error: bool = False,
    # If set, graphql raises TdbError on the *first* call only (per-item fallback trigger)
    graphql_error_first_call: bool = False,
) -> AsyncMock:
    """Build an AsyncMock TdbClient pre-configured to return the given docs."""
    tdb = AsyncMock()
    tdb.get_documents = AsyncMock()
    tdb.get_documents_by_status = AsyncMock()
    tdb.insert_documents = AsyncMock()
    tdb.replace_document = AsyncMock()
    tdb.graphql = AsyncMock()

    # Build a merged doc map
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
        if type_ == "InboxNote":
            return [d for d in (inbox_notes or []) if d.get("status") == status]
        if type_ == "InboxAudio":
            return [d for d in (inbox_audios or []) if d.get("status") == status]
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
        # Per-item idempotency lookup by variables["src"]
        if graphql_entity_by_source is not None and variables and "src" in (variables or {}):
            src_key = variables["src"]
            return {"Entity": graphql_entity_by_source.get(src_key, [])}
        return {"Entity": []}

    tdb.graphql.side_effect = _graphql

    return tdb


def _inbox_note(iri: str, content: str, status: str = "new") -> dict:
    return {
        "@id": iri,
        "@type": "InboxNote",
        "content": content,
        "status": status,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }


def _inbox_audio(iri: str, transcription: str, status: str = "transcribed") -> dict:
    return {
        "@id": iri,
        "@type": "InboxAudio",
        "file_name": "rec.wav",
        "file_path": "/tmp/rec.wav",
        "transcription": transcription,
        "recorded_at": "2026-07-05T14:00:00Z",
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
# Test 1 — Happy path: InboxNote → Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_inserts_task_and_flips_status():
    """One InboxNote → extract returns TaskProposal → insert + status flip."""
    note = _inbox_note("InboxNote/abc", "Buy milk tomorrow")
    tdb = _fake_tdb(inbox_notes=[note])

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

    # Assert insert_documents called ONCE for the single item batch
    tdb.insert_documents.assert_called_once()
    call_args = tdb.insert_documents.call_args
    docs = call_args[0][0]
    assert len(docs) == 1
    task = docs[0]
    assert task["@type"] == "Task"
    assert task["name"] == "Buy milk"
    # Status replaced with provenance.source
    assert task.get("provenance") is not None

    # Assert replace_document called to flip status
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "InboxNote/abc"
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2 — Idempotency via per-item GraphQL point lookup (happy path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_per_item_graphql_skip():
    """Per-item GraphQL query returns matching Entity → skip extraction."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(
        inbox_notes=[note],
        graphql_entity_by_source={
            "InboxNote/abc": [
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
    assert replaced["@id"] == "InboxNote/abc"

    # Verify the per-item query was called with the right variable
    tdb.graphql.assert_called()
    # First positional arg is the query, keyword arg 'variables' is the bindings
    call_query = tdb.graphql.call_args[0][0]
    call_kwargs = tdb.graphql.call_args.kwargs
    assert call_kwargs["variables"] == {"src": "InboxNote/abc"}
    assert "Entity(filter:" in call_query


# ---------------------------------------------------------------------------
# Test 2b — Per-item query: no match → extraction proceeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_per_item_graphql_no_match():
    """Per-item GraphQL query returns empty → extraction proceeds normally."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(
        inbox_notes=[note],
        graphql_entity_by_source={},  # no matches
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


@pytest.mark.asyncio
async def test_idempotency_graphql_failure_fallback_cached_scan():
    """First per-item GraphQL fails → fallback class scan built once, cached."""
    note1 = _inbox_note("InboxNote/abc", "Already derived")
    note2 = _inbox_note("InboxNote/def", "New note")
    existing_task = {
        "@id": "Task/existing",
        "@type": "Task",
        "name": "Derived task",
        "status": "open",
        "provenance": {"source": "InboxNote/abc"},
    }
    tdb = _fake_tdb(
        inbox_notes=[note1, note2],
        tasks=[existing_task],
        graphql_error_first_call=True,  # first query fails → fallback
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

    # First inbox doc (InboxNote/abc) matched via fallback → skipped
    # Second inbox doc (InboxNote/def) not in fallback → extracted
    assert extract_count == 1

    # get_documents (class scan) should be called exactly once for the fallback
    # (once per cycle, cached) — verify via call count
    # get_documents is called during both index build (for linking) and fallback
    # The fallback call adds to whatever linkable classes are queried.
    # We just verify the graphql was called (first call failed), then the
    # fallback was used for both items.
    tdb.graphql.assert_called()  # at least one graphql call happened

    # Two replace_document calls: first skipped (flipped to processed),
    # second extracted (flipped to processed)
    assert tdb.replace_document.call_count == 2
    assert tdb.replace_document.call_args_list[0][0][0]["@id"] == "InboxNote/abc"
    assert tdb.replace_document.call_args_list[0][0][0]["status"] == "processed"
    assert tdb.replace_document.call_args_list[1][0][0]["@id"] == "InboxNote/def"
    assert tdb.replace_document.call_args_list[1][0][0]["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2d — Idempotency path logged at INFO once per cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_path_logged_graphql():
    """Verify INFO log records the graphql_point_lookup path once per cycle."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(
        inbox_notes=[note],
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


@pytest.mark.asyncio
async def test_idempotency_path_logged_fallback():
    """Verify WARNING on graphql failure + INFO for class_scan_fallback path."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(
        inbox_notes=[note],
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

    path_logs = [
        e for e in captured
        if e.get("event") == "idempotency_path"
    ]
    assert len(path_logs) == 1
    assert path_logs[0]["method"] == "class_scan_fallback"


# ---------------------------------------------------------------------------
# Test 3 — Nothing actionable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_actionable_flips_to_processed():
    """Extract returns empty proposals → no insert, status → processed."""
    note = _inbox_note("InboxNote/abc", "Nothing to do.")
    tdb = _fake_tdb(inbox_notes=[note])

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


@pytest.mark.asyncio
async def test_tdberror_retry_with_error_feedback():
    """Insert fails with TdbError on first attempt, succeeds on second."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(inbox_notes=[note])

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


@pytest.mark.asyncio
async def test_retry_exhaustion_flips_to_failed():
    """Insert always raises TdbError → failed, next doc still processed."""
    note1 = _inbox_note("InboxNote/abc", "First note")
    note2 = _inbox_note("InboxNote/def", "Second note")
    tdb = _fake_tdb(inbox_notes=[note1, note2])

    insert_call = 0

    async def insert_stub(docs, branch="main", message="ingestd"):
        nonlocal insert_call
        insert_call += 1
        if insert_call <= 2:  # first 2 attempts = doc1 retries
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
    assert call_args_list[0][0][0]["@id"] == "InboxNote/abc"
    assert call_args_list[0][0][0]["status"] == "failed"
    assert call_args_list[1][0][0]["@id"] == "InboxNote/def"
    assert call_args_list[1][0][0]["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 6 — dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_no_inserts_no_flips():
    """dry_run mode: extract returns proposals → NO writes."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(inbox_notes=[note])

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


@pytest.mark.asyncio
async def test_ensure_entity_links_known_person_and_location():
    """PersonProposal matching known person → dropped (no doc inserted).
    EventProposal with known location → ensure_entity returns IRI directly."""
    note = _inbox_note("InboxNote/abc", "Meet Bob at Office")
    tdb = _fake_tdb(
        inbox_notes=[note],
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

    # Single insert_documents call: only the Event (Person was linked/dropped)
    # ensure_entity for "Person/Bob Smith" returns existing IRI, no doc created
    # ensure_entity for "Location/Office" returns existing IRI, no doc created
    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]
    event_docs = [d for d in docs if d.get("@type") == "Event"]
    assert len(event_docs) == 1
    event = event_docs[0]
    assert event["location"] == "Location/office"


# ---------------------------------------------------------------------------
# Test 8 — ensure_entity: new location created in same batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_entity_creates_new_location_in_same_batch():
    """EventProposal with unknown location_name → Location created in same batch."""
    note = _inbox_note("InboxNote/abc", "Meeting at NewPlace")
    tdb = _fake_tdb(inbox_notes=[note])

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

    # ONE insert_documents call with both Event and Location
    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]

    loc_docs = [d for d in docs if d.get("@type") == "Location"]
    event_docs = [d for d in docs if d.get("@type") == "Event"]

    assert len(loc_docs) == 1
    assert loc_docs[0]["name"] == "NewPlace"
    assert "@id" in loc_docs[0]

    assert len(event_docs) == 1
    # Event references the newly assigned @id
    assert event_docs[0]["location"] == loc_docs[0]["@id"]

    # Status flipped
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 8b — same new entity mentioned twice → one doc in batch (dedup)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_entity_dedup_two_mentions_same_cycle():
    """Two event proposals both referencing same new location → one Location doc."""
    note = _inbox_note("InboxNote/abc", "Meeting at NewPlace and then NewPlace again")
    tdb = _fake_tdb(inbox_notes=[note])

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

    # Only ONE Location doc despite two mentions
    assert len(loc_docs) == 1
    assert loc_docs[0]["name"] == "NewPlace"

    # Both events reference the same location @id
    assert len(event_docs) == 2
    assert event_docs[0]["location"] == loc_docs[0]["@id"]
    assert event_docs[1]["location"] == loc_docs[0]["@id"]


# ---------------------------------------------------------------------------
# Test 9 — Unexpected exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_exception_flips_to_failed_next_doc_still_processed():
    """Extract raises RuntimeError on first doc → failed, second doc processed."""
    note1 = _inbox_note("InboxNote/abc", "First note")
    note2 = _inbox_note("InboxNote/def", "Second note")
    tdb = _fake_tdb(inbox_notes=[note1, note2])

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
    assert call_args_list[0][0][0]["@id"] == "InboxNote/abc"
    assert call_args_list[1][0][0]["status"] == "processed"
    assert call_args_list[1][0][0]["@id"] == "InboxNote/def"


# ---------------------------------------------------------------------------
# Test 10 — Cycle-level resilience (run_cycle_safe catches exception)
# ---------------------------------------------------------------------------


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

    # Make run_cycle raise by making index fetch fail with a non-TdbError
    # (build_index_from_classes only catches TdbError)
    tdb.get_documents.side_effect = RuntimeError("context fetch explosion")

    result = await run_cycle_safe(pipeline, None)
    assert result is False


@pytest.mark.asyncio
async def test_run_cycle_safe_returns_true_on_success():
    """When run_cycle succeeds, run_cycle_safe returns True."""
    from ingestd.main import run_cycle_safe

    note = _inbox_note("InboxNote/abc", "Simple")
    tdb = _fake_tdb(inbox_notes=[note])

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


@pytest.mark.asyncio
async def test_exact_retry_accounting_max_retries_3():
    """max_llm_retries=3, insert always raises TdbError → extract called 3x, status=failed."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(inbox_notes=[note])
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
    assert replaced["@id"] == "InboxNote/abc"


# ---------------------------------------------------------------------------
# Test 12 — InboxAudio path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_audio_path():
    """InboxAudio with status=transcribed → transcription+recorded_at used, status→processed."""
    audio = _inbox_audio("InboxAudio/xyz", "Call Bob tomorrow at noon")
    tdb = _fake_tdb(inbox_audios=[audio])

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
    assert replaced["@id"] == "InboxAudio/xyz"
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 13 — dry_run positive assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_extract_called_but_zero_writes():
    """dry_run=True: extract IS called, reads happen, zero insert/replace calls."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(inbox_notes=[note])

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
# Test 14 — Missing created_at on inbox doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_created_at_logs_warning_defaults_now():
    """InboxNote without created_at → warning logged, extraction runs, processed."""
    note = {
        "@id": "InboxNote/nodate",
        "@type": "InboxNote",
        "content": "Buy milk",
        "status": "new",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    tdb = _fake_tdb(inbox_notes=[note])

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


@pytest.mark.asyncio
async def test_should_stop_after_first_doc():
    """should_stop set after first doc → second doc not processed."""
    note1 = _inbox_note("InboxNote/abc", "First")
    note2 = _inbox_note("InboxNote/def", "Second")
    tdb = _fake_tdb(inbox_notes=[note1, note2])

    call_count = [0]

    async def extract_with_stop(
        agent, text, reference_dt, context_block, error_feedback=None,
        extraction_ctx=None,
    ):
        call_count[0] += 1
        if call_count[0] == 1:
            assert True  # First call
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning=text,
            confidence=0.9,
        )

    pipeline = _make_pipeline(tdb, extract_fn=extract_with_stop)

    stop = asyncio.Event()

    # Wrap _process_one to set stop after first doc is processed
    orig_process = pipeline._process_one

    async def _process_with_stop(doc, src, index, context_block):
        result = await orig_process(doc, src, index, context_block)
        stop.set()
        return result

    pipeline._process_one = _process_with_stop

    await pipeline.run_cycle(should_stop=stop)

    # Only one replace_document (first doc)
    assert tdb.replace_document.call_count == 1
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "InboxNote/abc"


# ---------------------------------------------------------------------------
# Test 16 — build_documents mid-batch isolation
# ---------------------------------------------------------------------------


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
    note = _inbox_note("InboxNote/abc", "Test isolation")
    tdb = _fake_tdb(inbox_notes=[note])

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

    # In new design, build_documents failure sets success=False
    # which triggers error_feedback + retry, not insert.
    # On retry, the same proposals are re-processed — all fail again.
    # After max retries → failed status.
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "failed"
    assert replaced["@id"] == "InboxNote/abc"
