"""Tests for ingestd.pipeline — no network, mock TdbClient."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ingestd.extraction import (
    EventProposal,
    ExtractionResult,
    PersonProposal,
    TaskProposal,
)
from ingestd.pipeline import Pipeline
from ingestd.settings import Settings
from lms_core.tdb import TdbError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    people: list[dict] | None = None,
    locations: list[dict] | None = None,
    tasks: list[dict] | None = None,
    events: list[dict] | None = None,
    reminders: list[dict] | None = None,
) -> AsyncMock:
    """Build an AsyncMock TdbClient pre-configured to return the given docs."""
    tdb = AsyncMock()
    tdb.get_documents = AsyncMock()
    tdb.get_documents_by_status = AsyncMock()
    tdb.insert_documents = AsyncMock()
    tdb.replace_document = AsyncMock()

    # Route get_documents by type
    async def _get_docs(type_: str, branch: str = "main"):
        if type_ == "Person":
            return people or []
        if type_ == "Location":
            return locations or []
        if type_ == "Task":
            return tasks or []
        if type_ == "Event":
            return events or []
        if type_ == "Reminder":
            return reminders or []
        return []

    tdb.get_documents.side_effect = _get_docs

    async def _get_by_status(type_: str, status: str, branch: str = "main"):
        if type_ == "InboxNote":
            return [d for d in (inbox_notes or []) if d.get("status") == status]
        if type_ == "InboxAudio":
            return [d for d in (inbox_audios or []) if d.get("status") == status]
        return []

    tdb.get_documents_by_status.side_effect = _get_by_status
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


# ---------------------------------------------------------------------------
# Test 1 — Happy path: InboxNote → Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_inserts_task_and_flips_status():
    """One InboxNote → extract returns TaskProposal → insert + status flip."""
    note = _inbox_note("InboxNote/abc", "Buy milk tomorrow")
    tdb = _fake_tdb(inbox_notes=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
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

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    # Assert insert_documents called ONCE
    tdb.insert_documents.assert_called_once()
    call_args = tdb.insert_documents.call_args
    docs = call_args[0][0]
    assert len(docs) == 1
    task = docs[0]
    assert task["@type"] == "Task"
    assert task["name"] == "Buy milk"
    assert task["status"] == "open"
    assert task["derived_from"] == "InboxNote/abc"

    # Assert replace_document called to flip status
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "InboxNote/abc"
    assert replaced["status"] == "processed"


# ---------------------------------------------------------------------------
# Test 2 — Idempotency / crash recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_skips_already_derived():
    """Existing Task with derived_from == inbox IRI → skip extraction."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    existing_task = {
        "@id": "Task/existing",
        "@type": "Task",
        "name": "Buy milk",
        "status": "open",
        "derived_from": "InboxNote/abc",
    }
    tdb = _fake_tdb(inbox_notes=[note], tasks=[existing_task])

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert not extract_called
    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_called_once()
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["status"] == "processed"
    assert replaced["@id"] == "InboxNote/abc"


# ---------------------------------------------------------------------------
# Test 3 — Nothing actionable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_actionable_flips_to_processed():
    """Extract returns empty proposals → no insert, status → processed."""
    note = _inbox_note("InboxNote/abc", "Nothing to do.")
    tdb = _fake_tdb(inbox_notes=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        return ExtractionResult(
            proposals=[],
            reasoning="Nothing actionable.",
            confidence=0.99,
        )

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

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
        agent, text, reference_dt, context_block, error_feedback=None
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
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    # Extract called twice
    assert len(extract_calls) == 2
    # First call: error_feedback is None
    assert extract_calls[0] is None
    # Second call: error_feedback contains the verbatim body
    assert extract_calls[1] == error_body

    # Final status is processed
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
        # Fail the first batch (doc1), succeed on the second batch (doc2)
        if insert_call <= 3:  # 2 attempts for doc1 + first attempt for doc2
            if insert_call <= 2:  # doc1: always fail
                raise TdbError(400, "persistent failure")
        return ["terminusdb:///data/Task/ok"]

    tdb.insert_documents.side_effect = insert_stub

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
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
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    # Both docs should trigger replace_document (one failed, one processed)
    assert tdb.replace_document.call_count == 2
    call_args_list = tdb.replace_document.call_args_list
    # First doc → failed
    assert call_args_list[0][0][0]["@id"] == "InboxNote/abc"
    assert call_args_list[0][0][0]["status"] == "failed"
    # Second doc → processed normally (insert succeeded)
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
        agent, text, reference_dt, context_block, error_feedback=None
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
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_not_called()
    tdb.replace_document.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7 — Person linking + known location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_linked_and_known_location_no_duplicates():
    """PersonProposal matching known person → dropped.
    EventProposal with known location → location IRI set directly."""
    note = _inbox_note("InboxNote/abc", "Meet Bob at Office")
    tdb = _fake_tdb(
        inbox_notes=[note],
        people=[{"@id": "Person/bob", "name": "Bob Smith"}],
        locations=[{"@id": "Location/office", "name": "Office"}],
    )

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
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

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    tdb.insert_documents.assert_called_once()
    docs = tdb.insert_documents.call_args[0][0]
    # Only one doc: the Event (Person was linked/dropped)
    assert len(docs) == 1
    event = docs[0]
    assert event["@type"] == "Event"
    assert event["location"] == "Location/office"


# ---------------------------------------------------------------------------
# Test 8 — New location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_location_inserted_before_event():
    """EventProposal with unknown location_name → Location inserted first."""
    note = _inbox_note("InboxNote/abc", "Meeting at NewPlace")
    tdb = _fake_tdb(inbox_notes=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
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

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    # Two insert calls: locations first, then main docs
    assert tdb.insert_documents.call_count == 2

    # First call: Location
    loc_call = tdb.insert_documents.call_args_list[0]
    loc_docs = loc_call[0][0]
    assert len(loc_docs) == 1
    assert loc_docs[0]["@type"] == "Location"
    assert loc_docs[0]["name"] == "NewPlace"

    # Second call: Event referencing the location IRI
    event_call = tdb.insert_documents.call_args_list[1]
    event_docs = event_call[0][0]
    assert len(event_docs) == 1
    assert event_docs[0]["@type"] == "Event"
    # IRI comes from the mocked insert; mock returns None by default, so location stays None
    # That's fine — we just test the split between location and event inserts.


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
        agent, text, reference_dt, context_block, error_feedback=None
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

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

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
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        return ExtractionResult(proposals=[], reasoning="", confidence=1.0)

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    # Make run_cycle raise by making context fetch fail
    tdb.get_documents.side_effect = TdbError(500, "context fetch explosion")

    result = await run_cycle_safe(pipeline, None)
    assert result is False


@pytest.mark.asyncio
async def test_run_cycle_safe_returns_true_on_success():
    """When run_cycle succeeds, run_cycle_safe returns True."""
    from ingestd.main import run_cycle_safe

    note = _inbox_note("InboxNote/abc", "Simple")
    tdb = _fake_tdb(inbox_notes=[note])

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning="ok",
            confidence=0.9,
        )

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    result = await run_cycle_safe(pipeline, None)
    assert result is True


# ---------------------------------------------------------------------------
# Test 11 — Exact retry accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_retry_accounting_max_retries_3():
    """max_llm_retries=3, insert always raises TdbError → extract called exactly 3×, status=failed."""
    note = _inbox_note("InboxNote/abc", "Buy milk")
    tdb = _fake_tdb(inbox_notes=[note])
    tdb.insert_documents.side_effect = TdbError(400, "boom")

    extract_calls = []

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        extract_calls.append(error_feedback)
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="trying",
            confidence=0.5,
        )

    settings = _settings(max_llm_retries=3)
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

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
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        received_args["text"] = text
        received_args["reference_dt"] = reference_dt
        received_args["context_block"] = context_block
        return ExtractionResult(
            proposals=[TaskProposal(name="Call Bob")],
            reasoning="call",
            confidence=0.9,
        )

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    # Extract received the transcription text
    assert received_args["text"] == "Call Bob tomorrow at noon"
    # Extract received the recorded_at datetime
    from datetime import datetime, timezone

    expected_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=timezone.utc)
    assert received_args["reference_dt"] == expected_dt
    # Status flipped to processed
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

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        nonlocal extract_called
        extract_called = True
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="task",
            confidence=0.9,
        )

    settings = _settings(dry_run=True)
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    await pipeline.run_cycle()

    assert extract_called is True
    # Reads happened (context + idempotency + inbox)
    tdb.get_documents.assert_called()
    tdb.get_documents_by_status.assert_called()
    # Zero writes
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
        # created_at intentionally missing
    }
    tdb = _fake_tdb(inbox_notes=[note])

    extract_called = False

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        nonlocal extract_called
        extract_called = True
        # reference_dt should be a valid datetime (now-like)
        from datetime import datetime

        assert isinstance(reference_dt, datetime)
        return ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="ok",
            confidence=0.9,
        )

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    # Capture structlog events via a processor
    import structlog

    captured_events: list[dict] = []

    def _capture(_logger, _method, event_dict):
        captured_events.append(dict(event_dict))
        return event_dict

    structlog.configure(
        processors=[_capture, structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    try:
        await pipeline.run_cycle()

        assert extract_called is True
        tdb.replace_document.assert_called_once()
        replaced = tdb.replace_document.call_args[0][0]
        assert replaced["status"] == "processed"
        assert replaced["@id"] == "InboxNote/nodate"

        # Check that a warning was logged about the missing field
        warning_events = [
            e for e in captured_events if e.get("event") == "reference_datetime_missing"
        ]
        assert len(warning_events) >= 1, (
            f"No reference_datetime_missing warning in: {captured_events}"
        )
    finally:
        structlog.reset_defaults()


# ---------------------------------------------------------------------------
# Test 15 — should_stop set after first doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_stop_after_first_doc():
    """should_stop set after first doc → second doc not processed."""
    note1 = _inbox_note("InboxNote/abc", "First")
    note2 = _inbox_note("InboxNote/def", "Second")
    tdb = _fake_tdb(inbox_notes=[note1, note2])

    processed_docs = []

    async def fake_extract(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        processed_docs.append(text)
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning=text,
            confidence=0.9,
        )

    settings = _settings()
    pipeline = Pipeline(tdb=tdb, agent=None, settings=settings, extract_fn=fake_extract)

    stop = asyncio.Event()

    # We need to set stop after the first doc is extracted but before the second.
    # Use a wrapper extract that sets stop on first call
    call_count = [0]

    async def extract_with_stop(
        agent, text, reference_dt, context_block, error_feedback=None
    ):
        processed_docs.append(text)
        call_count[0] += 1
        if call_count[0] == 1:
            stop.set()
        return ExtractionResult(
            proposals=[TaskProposal(name="Task")],
            reasoning=text,
            confidence=0.9,
        )

    pipeline._extract = extract_with_stop

    await pipeline.run_cycle(should_stop=stop)

    # Only the first doc was processed
    assert len(processed_docs) == 1
    assert processed_docs[0] == "First"

    # Only first doc got a status flip
    assert tdb.replace_document.call_count == 1
    replaced = tdb.replace_document.call_args[0][0]
    assert replaced["@id"] == "InboxNote/abc"
