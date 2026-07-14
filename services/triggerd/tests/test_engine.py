"""Tests for triggerd.engine — no network, AsyncMock TdbClient."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import structlog

from triggerd.engine import Engine
from triggerd.evaluators import (
    CompositeEvaluator,
    EventTriggerEvaluator,
    OneShotEvaluator,
    ScheduleEvaluator,
)
from firnline_core.plugins import ModuleRequirement
from firnline_core.repository import Repository
from firnline_core.tdb import StaleCommitError, TdbError

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers — minimal evaluators for edge-case tests
# ---------------------------------------------------------------------------


class _BrokenEvaluator:
    """Evaluator that always raises."""

    name = "broken"
    trigger_types = ("BrokenTrigger",)
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# fake TdbClient builder
# ---------------------------------------------------------------------------


def _make_engine(
    *,
    trigger_docs: list[dict] | None = None,
    schema_entries: list[dict] | None = None,
    insert_side_effect=None,
    graphql_side_effect=None,
    now=None,
    dry_run=False,
    evaluators=None,
) -> Engine:
    """Build an Engine backed by an AsyncMock TdbClient with side-effect routing."""
    tdb = AsyncMock()
    tdb.get_documents = AsyncMock()
    tdb.get_schema = AsyncMock()
    tdb.graphql = AsyncMock()
    tdb.insert_documents = AsyncMock()
    tdb.changes_since = AsyncMock()

    async def _get_docs(type_: str, branch: str = "main"):
        if trigger_docs:
            return [d for d in trigger_docs if d.get("@type") == type_]
        return []

    tdb.get_documents.side_effect = _get_docs

    async def _get_schema(branch: str = "main"):
        return schema_entries or _default_schema()

    tdb.get_schema.side_effect = _get_schema
    tdb.changes_since.return_value = ([], "head")

    if insert_side_effect:
        tdb.insert_documents.side_effect = insert_side_effect
    else:
        tdb.insert_documents.return_value = ["fake-iri"]

    if graphql_side_effect:
        tdb.graphql.side_effect = graphql_side_effect
    else:
        tdb.graphql.return_value = {}

    from triggerd.settings import Settings

    settings = Settings(tdb_db="test", tdb_password="pw")
    if dry_run:
        settings = settings.model_copy(update={"dry_run": True})

    if evaluators is None:
        evaluators = [OneShotEvaluator(), ScheduleEvaluator(), CompositeEvaluator()]

    return Engine(repo=Repository(tdb), settings=settings, evaluators=evaluators, now=now)


def _default_schema() -> list[dict]:
    """Minimal schema with Trigger hierarchy."""
    return [
        {"@id": "Trigger", "@type": "Class", "@abstract": True},
        {"@id": "OneShotTrigger", "@type": "Class", "@inherits": "Trigger"},
        {"@id": "ScheduleTrigger", "@type": "Class", "@inherits": "Trigger"},
        {"@id": "CompositeTrigger", "@type": "Class", "@inherits": "Trigger"},
        {"@id": "EventTrigger", "@type": "Class", "@inherits": "Trigger"},
        {"@id": "AbstractMid", "@type": "Class", "@abstract": True, "@inherits": "Trigger"},
        {"@id": "ConcreteMid", "@type": "Class", "@inherits": "AbstractMid"},
    ]


# ── useful datetime helpers ───────────────────────────────────────────


def _utc_iso(dt: datetime) -> str:
    """Return UTC ISO-8601 (TDB canonical form)."""
    return dt.astimezone(timezone.utc).isoformat()


def _frozen_now_2026() -> datetime:
    """Frozen clock: 2026-07-06T12:00:00Z."""
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


def _frozen_now_plus(seconds: int) -> datetime:
    return _frozen_now_2026() + timedelta(seconds=seconds)


# ===================================================================
# Tests
# ===================================================================


class TestSchemaScan:
    """Concrete subclass enumeration with inheritance, abstract exclusion, cache."""

    @pytest.mark.asyncio
    async def test_concrete_subclasses_enumerated(self):
        """Engine discovers all non-abstract Trigger subclasses."""
        engine = _make_engine()
        types = await engine._get_concrete_trigger_types("main")
        assert "OneShotTrigger" in types
        assert "ScheduleTrigger" in types
        assert "CompositeTrigger" in types
        assert "EventTrigger" in types
        assert "AbstractMid" not in types  # abstract
        assert "Trigger" not in types  # abstract
        # Transitive inheritance
        assert "ConcreteMid" in types

    @pytest.mark.asyncio
    async def test_schema_fetched_once_per_cycle(self):
        """_build_ctx fetches schema; _get_concrete_trigger_types and
        _get_triggerable_subclasses reuse it without extra round-trips."""
        engine = _make_engine()
        await engine._build_ctx("main")
        assert engine.tdb.get_schema.call_count == 1
        await engine._get_concrete_trigger_types("main")
        await engine._get_triggerable_subclasses("main")
        assert engine.tdb.get_schema.call_count == 1


class TestValidityFilter:
    """Enabled / valid_from / valid_until filtering."""

    @pytest.mark.asyncio
    async def test_disabled_trigger_not_evaluated(self):
        """Trigger with enabled=False is skipped."""
        now = _frozen_now_2026()
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": False,
                    "fire_at": _utc_iso(now - timedelta(seconds=60)),
                },
            ],
        )
        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert len(summary) == 1
        assert summary[0]["evaluated"] == 0
        assert summary[0]["triggers_scanned"] == 1

    @pytest.mark.asyncio
    async def test_valid_until_in_past_excluded(self):
        """Trigger with valid_until before window_end is skipped."""
        now = _frozen_now_2026()
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": _utc_iso(now - timedelta(seconds=60)),
                    "valid_until": _utc_iso(now - timedelta(hours=1)),
                },
            ],
        )
        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert summary[0]["evaluated"] == 0

    @pytest.mark.asyncio
    async def test_valid_from_in_future_excluded(self):
        """Trigger with valid_from after window_end is skipped."""
        now = _frozen_now_2026()
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": _utc_iso(now - timedelta(seconds=60)),
                    "valid_from": _utc_iso(now + timedelta(hours=1)),
                },
            ],
        )
        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert summary[0]["evaluated"] == 0


class TestUnsupportedType:
    """Unsupported @type → logged once per type per cycle, not per doc."""

    @pytest.mark.asyncio
    async def test_unsupported_type_logged_once_per_type(self):
        """Two UnknownTrigger + two FoobarTrigger docs → one log event per type."""
        now = _frozen_now_2026()
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {"@id": "UnknownTrigger/u1", "@type": "UnknownTrigger", "enabled": True},
                {"@id": "UnknownTrigger/u2", "@type": "UnknownTrigger", "enabled": True},
                {"@id": "FoobarTrigger/f1", "@type": "FoobarTrigger", "enabled": True},
                {"@id": "FoobarTrigger/f2", "@type": "FoobarTrigger", "enabled": True},
            ],
            schema_entries=[
                {"@id": "Trigger", "@type": "Class", "@abstract": True},
                {"@id": "UnknownTrigger", "@type": "Class", "@inherits": "Trigger"},
                {"@id": "FoobarTrigger", "@type": "Class", "@inherits": "Trigger"},
            ],
        )
        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        unsupported = [e for e in captured if e.get("event") == "trigger_type_unsupported"]
        # One warning per unique unsupported type
        assert len(unsupported) == 2
        types_logged = {e["type"] for e in unsupported}
        assert types_logged == {"UnknownTrigger", "FoobarTrigger"}
        # Summary dict populated
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert summary[0]["skipped_by_type"] == {"UnknownTrigger": 2, "FoobarTrigger": 2}


class TestSubjectResolution:
    """GraphQL subject resolution — one/none/ambiguous/error-tolerated."""

    @pytest.mark.asyncio
    async def test_exactly_one_triggerable_returns_subject(self):
        """One Triggerable referencing the trigger → subject set."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
        )
        engine.tdb.graphql = AsyncMock(
            return_value={"Triggerable": [{"_id": "Reminder/r1"}]}
        )
        subject = await engine._resolve_subject("OneShotTrigger/t1", "main")
        assert subject == "Reminder/r1"

    @pytest.mark.asyncio
    async def test_no_referrer_returns_none(self):
        """No referrer → subject is None."""
        engine = _make_engine()
        engine.tdb.graphql = AsyncMock(return_value={})
        subject = await engine._resolve_subject("OneShotTrigger/t1", "main")
        assert subject is None

    @pytest.mark.asyncio
    async def test_ambiguous_referrers_returns_none(self):
        """Two referrers → None + subject_ambiguous logged."""
        engine = _make_engine()
        engine.tdb.graphql = AsyncMock(
            return_value={"Triggerable": [{"_id": "Reminder/r1"}, {"_id": "Reminder/r2"}]}
        )
        with structlog.testing.capture_logs() as captured:
            subject = await engine._resolve_subject("OneShotTrigger/t1", "main")
        assert subject is None
        ambiguous = [e for e in captured if e.get("event") == "subject_ambiguous"]
        assert len(ambiguous) == 1
        assert ambiguous[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_graphql_unknown_type_tolerated(self):
        """GraphQL error → fallback to triggerable subclasses, then no subject, no crash."""
        engine = _make_engine()
        engine.tdb.graphql = AsyncMock(side_effect=TdbError(400, '{"errors":[{"message":"Cannot query field"}]}'))
        with structlog.testing.capture_logs() as captured:
            subject = await engine._resolve_subject("OneShotTrigger/t1", "main")
        assert subject is None
        # Old path logged subject_query_failed; now the fallback path logs
        # triggerable_abstract_query_failed (since the abstract query fails).
        warn_events = [e for e in captured if e.get("event") == "triggerable_abstract_query_failed"]
        assert len(warn_events) == 1


class TestDryRun:
    """dry_run=True skips inserts, logs firing_dry_run."""

    @pytest.mark.asyncio
    async def test_dry_run_no_insert_logs_firing(self):
        """No insert_documents call, firing_dry_run logged at INFO."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        engine = _make_engine(
            now=lambda: now,
            dry_run=True,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
        )
        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        engine.tdb.insert_documents.assert_not_called()
        dry_run_events = [e for e in captured if e.get("event") == "firing_dry_run"]
        assert len(dry_run_events) == 1
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert summary[0]["firings_written"] == 0


class TestEvaluatorExceptionIsolation:
    """A broken evaluator does not kill the cycle; other triggers still fire."""

    @pytest.mark.asyncio
    async def test_broken_evaluator_isolated(self):
        """One BrokenTrigger raises, another OneShotTrigger still fires."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        engine = _make_engine(
            now=lambda: now,
            evaluators=[_BrokenEvaluator(), OneShotEvaluator()],
            trigger_docs=[
                {
                    "@id": "BrokenTrigger/b1",
                    "@type": "BrokenTrigger",
                    "enabled": True,
                },
                {
                    "@id": "OneShotTrigger/ok",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
            schema_entries=[
                {"@id": "Trigger", "@type": "Class", "@abstract": True},
                {"@id": "OneShotTrigger", "@type": "Class", "@inherits": "Trigger"},
                {"@id": "BrokenTrigger", "@type": "Class", "@inherits": "Trigger"},
            ],
        )
        inserted_docs = []

        async def _record_insert(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        engine.tdb.insert_documents.side_effect = _record_insert

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()
        errors = [e for e in captured if e.get("event") == "evaluator_error"]
        assert len(errors) == 1
        # The OK trigger still got a firing
        summary = [e for e in captured if e.get("event") == "cycle_complete"]
        assert summary[0]["errors"] == 1
        assert summary[0]["firings_written"] == 1


class TestIdempotency:
    """Duplicate firings suppressed across overlapping cycles."""

    @pytest.mark.asyncio
    async def test_idempotent_firings_across_cycles(self):
        """Two cycles with overlapping windows → only one net insert."""
        frozen_time = _frozen_now_2026()
        fire_at = frozen_time - timedelta(seconds=60)  # 11:59
        fire_at_str = _utc_iso(fire_at)

        inserted_docs: list[dict] = []
        insert_call_count = 0

        async def _insert(docs, branch="main", message="", author=""):
            nonlocal insert_call_count
            insert_call_count += 1
            if insert_call_count == 1:
                inserted_docs.extend(docs)
                return ["fake"]
            else:
                raise TdbError(400, "api:DocumentIdAlreadyExists")

        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "enabled": True,
            "fire_at": fire_at_str,
        }

        eng = _make_engine(
            now=lambda: frozen_time,
            trigger_docs=[trigger_doc],
            schema_entries=_default_schema(),
        )
        eng.tdb.insert_documents.side_effect = _insert
        eng.tdb.graphql = AsyncMock(
            return_value={"Triggerable": [{"_id": "Reminder/r1"}]}
        )

        # Cycle 1
        with structlog.testing.capture_logs() as cap1:
            await eng.run_cycle()
        summary1 = [e for e in cap1 if e.get("event") == "cycle_complete"][0]
        assert summary1["firings_written"] == 1
        assert summary1["duplicates_suppressed"] == 0
        assert insert_call_count == 1
        assert len(inserted_docs) == 1

        # Cycle 2 — advance frozen time by less than lookback, so window still
        # covers the same fire_at. occurrence_key is identical.
        frozen_time2 = frozen_time + timedelta(seconds=300)  # 5 min later
        eng2 = _make_engine(
            now=lambda: frozen_time2,
            trigger_docs=[trigger_doc],
            schema_entries=_default_schema(),
        )
        eng2.tdb.insert_documents.side_effect = _insert
        eng2.tdb.graphql = AsyncMock(
            return_value={"Triggerable": [{"_id": "Reminder/r1"}]}
        )

        with structlog.testing.capture_logs() as cap2:
            await eng2.run_cycle()
        summary2 = [e for e in cap2 if e.get("event") == "cycle_complete"][0]
        assert summary2["firings_written"] == 0
        assert summary2["duplicates_suppressed"] == 1
        # Only the first insert actually went through
        assert len(inserted_docs) == 1


class TestOccurrenceKeyStability:
    """occurrence_key is stable for the same scheduled instant."""

    def test_canonical_form_stable(self):
        """Same instant → same isoformat key, using canonical Z suffix."""
        from firnline_core.base import _format_datetime

        dt = datetime(2026, 7, 6, 11, 59, 0, tzinfo=timezone.utc)
        key1 = _format_datetime(dt)
        key2 = _format_datetime(dt)
        assert key1 == key2
        assert key1.endswith("Z")
        assert "+00:00" not in key1

    @pytest.mark.asyncio
    async def test_same_instant_two_cycles_same_key(self):
        """Two cycles capturing the same scheduled instant produce the same occurrence_key."""
        frozen_time = _frozen_now_2026()
        fire_at = frozen_time - timedelta(seconds=60)
        fire_at_str = _utc_iso(fire_at)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "enabled": True,
            "fire_at": fire_at_str,
        }

        inserted_docs: list[dict] = []

        async def _record(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        eng1 = _make_engine(
            now=lambda: frozen_time,
            trigger_docs=[trigger_doc],
            schema_entries=_default_schema(),
        )
        eng1.tdb.insert_documents.side_effect = _record

        await eng1.run_cycle()
        key1 = inserted_docs[0]["occurrence_key"]

        inserted_docs.clear()
        frozen_time2 = frozen_time + timedelta(seconds=300)
        eng2 = _make_engine(
            now=lambda: frozen_time2,
            trigger_docs=[trigger_doc],
            schema_entries=_default_schema(),
        )
        eng2.tdb.insert_documents.side_effect = _record
        await eng2.run_cycle()
        key2 = inserted_docs[0]["occurrence_key"]

        assert key1 == key2


class TestCompositePath:
    """Composite triggers recurse through the engine's get_occurrences dispatch."""

    @pytest.mark.asyncio
    async def test_composite_any_operand_fires(self):
        """Composite(any) over a OneShot fires via full engine cycle."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))

        one_shot_doc = {
            "@id": "OneShotTrigger/inner",
            "@type": "OneShotTrigger",
            "enabled": True,
            "fire_at": fire_at,
        }
        composite_doc = {
            "@id": "CompositeTrigger/outer",
            "@type": "CompositeTrigger",
            "enabled": True,
            "mode": "any",
            "operands": ["OneShotTrigger/inner"],
        }

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[composite_doc],
            evaluators=[OneShotEvaluator(), CompositeEvaluator()],
        )
        # Override get_document for operand fetch
        engine.tdb.get_document = AsyncMock(return_value=one_shot_doc)

        inserted_docs = []

        async def _record(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        engine.tdb.insert_documents.side_effect = _record

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        summary = [e for e in captured if e.get("event") == "cycle_complete"][0]
        assert summary["firings_written"] == 1
        assert summary["evaluated"] == 1
        assert len(inserted_docs) == 1

    @pytest.mark.asyncio
    async def test_composite_operand_disabled_not_fired(self):
        """Disabled operand inside composite → no firing."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))

        one_shot_doc = {
            "@id": "OneShotTrigger/inner",
            "@type": "OneShotTrigger",
            "enabled": False,  # disabled
            "fire_at": fire_at,
        }
        composite_doc = {
            "@id": "CompositeTrigger/outer",
            "@type": "CompositeTrigger",
            "enabled": True,
            "mode": "any",
            "operands": ["OneShotTrigger/inner"],
        }

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[composite_doc],
            evaluators=[OneShotEvaluator(), CompositeEvaluator()],
        )
        engine.tdb.get_document = AsyncMock(return_value=one_shot_doc)

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        summary = [e for e in captured if e.get("event") == "cycle_complete"][0]
        assert summary["firings_written"] == 0
        # The composite itself was evaluated (scanned and dispatched),
        # but the operand was filtered inactive in _dispatch_occurrences
        assert summary["evaluated"] == 1


class TestCycleCompleteSummary:
    """cycle_complete summary fields present with correct counts."""

    @pytest.mark.asyncio
    async def test_summary_mixed_scenario(self):
        """Mixed scenario: one active OneShot, one disabled, one unsupported (UnknownTrigger)."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/active",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
                {
                    "@id": "OneShotTrigger/disabled",
                    "@type": "OneShotTrigger",
                    "enabled": False,
                    "fire_at": fire_at,
                },
                {
                    "@id": "UnknownTrigger/unsupported",
                    "@type": "UnknownTrigger",
                    "enabled": True,
                },
            ],
            schema_entries=_default_schema()
            + [{"@id": "UnknownTrigger", "@type": "Class", "@inherits": "Trigger"}],
        )
        inserted_docs = []

        async def _record(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        engine.tdb.insert_documents.side_effect = _record

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        summary = [e for e in captured if e.get("event") == "cycle_complete"][0]
        assert summary["triggers_scanned"] == 3
        assert summary["triggers_dispatched"] == 1
        # 1 active evaluated, 1 disabled not dispatched, 1 unsupported
        assert summary["evaluated"] == 1
        assert summary["skipped_by_type"] == {"UnknownTrigger": 1}
        assert summary["firings_written"] == 1
        assert summary["duplicates_suppressed"] == 0
        assert summary["errors"] == 0


class TestDatetimeSerialization:
    """Inserted firing documents contain string datetimes in canonical Z format."""

    @pytest.mark.asyncio
    async def test_firing_doc_datetimes_are_strings(self):
        """scheduled_for and fired_at are TDB-canonical strings, JSON-safe."""
        import json

        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        inserted: list[dict] = []

        async def _record(docs, branch="main", message="", author=""):
            inserted.extend(docs)
            return ["fake"]

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
        )
        engine.tdb.insert_documents.side_effect = _record

        await engine.run_cycle()
        assert len(inserted) == 1
        doc = inserted[0]
        # Datetime fields are plain strings, not datetime objects
        assert isinstance(doc["scheduled_for"], str)
        assert isinstance(doc["fired_at"], str)
        assert doc["scheduled_for"].endswith("Z")
        assert doc["fired_at"].endswith("Z")
        # Full JSON round-trip must succeed (no TypeError from datetime objects)
        json.dumps(doc)


class TestBatchAtomicityFallback:
    """When a batch contains [duplicate, new], individual fallback persists the new one."""

    @pytest.mark.asyncio
    async def test_duplicate_and_new_in_same_batch(self):
        """Batch rejected with DocumentIdAlreadyExists → individual inserts save the new firing."""
        now = _frozen_now_2026()

        # Seed: ScheduleTrigger producing 2 instants (11:57, 11:58).
        schedule_doc = {
            "@id": "ScheduleTrigger/daily",
            "@type": "ScheduleTrigger",
            "enabled": True,
            "dtstart": "2026-07-06T11:57:00Z",
            "rrule": "FREQ=MINUTELY;COUNT=2",
        }

        inserted_cycle1: list[dict] = []

        async def _record1(docs, branch="main", message="", author=""):
            inserted_cycle1.extend(docs)
            return ["fake"]

        engine1 = _make_engine(
            now=lambda: now,
            trigger_docs=[schedule_doc],
            schema_entries=_default_schema(),
        )
        engine1.tdb.insert_documents.side_effect = _record1
        with structlog.testing.capture_logs() as cap1:
            await engine1.run_cycle()
        s1 = [e for e in cap1 if e.get("event") == "cycle_complete"][0]
        assert s1["firings_written"] == 2

        already_inserted_keys: set[str] = {d["occurrence_key"] for d in inserted_cycle1}

        # Verify full-duplicate batch → all suppressed via fallback.
        async def _batch_all_dup(docs, branch="main", message="", author=""):
            if len(docs) > 1:
                raise TdbError(400, "api:DocumentIdAlreadyExists")
            key = docs[0]["occurrence_key"]
            if key in already_inserted_keys:
                raise TdbError(400, "api:DocumentIdAlreadyExists")
            return ["fake"]

        engine2 = _make_engine(
            now=lambda: now,
            trigger_docs=[schedule_doc],
            schema_entries=_default_schema(),
        )
        engine2.tdb.insert_documents.side_effect = _batch_all_dup
        with structlog.testing.capture_logs() as cap2:
            await engine2.run_cycle()
        s2 = [e for e in cap2 if e.get("event") == "cycle_complete"][0]
        assert s2["duplicates_suppressed"] == 2

        # Mixed batch: COUNT=3 produces 11:57 (dup), 11:58 (dup), 11:59 (new).
        schedule_doc3 = {
            "@id": "ScheduleTrigger/daily",
            "@type": "ScheduleTrigger",
            "enabled": True,
            "dtstart": "2026-07-06T11:57:00Z",
            "rrule": "FREQ=MINUTELY;COUNT=3",
        }

        async def _batch_mixed(docs, branch="main", message="", author=""):
            if len(docs) > 1:
                raise TdbError(400, "api:DocumentIdAlreadyExists")
            key = docs[0]["occurrence_key"]
            if key in already_inserted_keys:
                raise TdbError(400, "api:DocumentIdAlreadyExists")
            return ["fake"]

        engine3 = _make_engine(
            now=lambda: now,
            trigger_docs=[schedule_doc3],
            schema_entries=_default_schema(),
        )
        engine3.tdb.insert_documents.side_effect = _batch_mixed
        with structlog.testing.capture_logs() as cap3:
            await engine3.run_cycle()
        s3 = [e for e in cap3 if e.get("event") == "cycle_complete"][0]
        assert s3["firings_written"] == 1  # 11:59 is new
        assert s3["duplicates_suppressed"] == 2  # 11:57 and 11:58 suppressed


class TestFiringDocEntityFields:
    """TriggerFiring documents carry created_at/updated_at (Entity requirement)."""

    @pytest.mark.asyncio
    async def test_firing_doc_has_created_updated_at(self):
        """Inserted firing doc includes created_at and updated_at as ISO strings."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        inserted: list[dict] = []

        async def _record(docs, branch="main", message="", author=""):
            inserted.extend(docs)
            return ["fake"]

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
        )
        engine.tdb.insert_documents.side_effect = _record

        await engine.run_cycle()
        assert len(inserted) == 1
        doc = inserted[0]
        assert "created_at" in doc
        assert "updated_at" in doc
        assert isinstance(doc["created_at"], str)
        assert isinstance(doc["updated_at"], str)
        assert doc["created_at"].endswith("Z")
        assert doc["updated_at"].endswith("Z")


class TestBaselineFirstCycle:
    """First cycle with no prior commit baselines head, produces no change events."""

    @pytest.mark.asyncio
    async def test_baseline_cycle_no_event_firings(self):
        """changes_since returns ([], head) → EventTrigger produces no firings."""
        now = _frozen_now_2026()

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "EventTrigger/ev1",
                    "@type": "EventTrigger",
                    "enabled": True,
                    "event": "created",
                },
            ],
            evaluators=[EventTriggerEvaluator()],
        )
        # changes_since returns ([], 'head') — baseline
        engine.tdb.changes_since = AsyncMock(return_value=([], "head"))

        inserted_docs = []

        async def _record(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        engine.tdb.insert_documents.side_effect = _record

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        summary = [e for e in captured if e.get("event") == "cycle_complete"][0]
        assert summary["firings_written"] == 0
        assert len(inserted_docs) == 0


class TestEventTriggerFiringKeys:
    """EventTrigger firings use commit_id-based occurrence_keys."""

    @pytest.mark.asyncio
    async def test_event_trigger_occurrence_key_contains_commit_id(self):
        """When EventTrigger fires from a change event, occurrence_key encodes commit_id."""
        now = _frozen_now_2026()
        ts = now.timestamp()

        from firnline_core.tdb import ChangeEvent

        change = ChangeEvent(
            commit_id="commit-abc",
            author="tester",
            message="test",
            timestamp=ts,
            inserted=["Task/new"],
            updated=[],
            deleted=[],
        )

        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "EventTrigger/ev1",
                    "@type": "EventTrigger",
                    "enabled": True,
                    "event": "created",
                },
            ],
            evaluators=[EventTriggerEvaluator()],
        )
        engine.tdb.changes_since = AsyncMock(return_value=([change], "head2"))

        inserted_docs = []

        async def _record(docs, branch="main", message="", author=""):
            inserted_docs.extend(docs)
            return ["fake"]

        engine.tdb.insert_documents.side_effect = _record

        await engine.run_cycle()

        assert len(inserted_docs) == 1
        key = inserted_docs[0]["occurrence_key"]
        # New format: commit-abc[:12]-sha256[:12]
        assert key.startswith("commit-abc")
        assert "-" in key
        # Key is stable and deterministically derived from commit_id + IRI
        from triggerd.evaluators import _make_event_key
        assert key == _make_event_key("commit-abc", "Task/new")


class TestStateFilePersistence:
    """The _last_commit map is persisted across restarts via state_file."""

    @pytest.mark.asyncio
    async def test_restart_does_not_rebaseline(self):
        """Two engines sharing the same state file; second sees existing head."""
        import json
        import tempfile
        from pathlib import Path

        state_file = Path(tempfile.gettempdir()) / f"test-triggerd-state-{id(self)}.json"
        # Cleanup before
        state_file.unlink(missing_ok=True)

        try:
            # Write a state file with a known last commit
            initial_state = {"main": "commit-aaa"}
            state_file.write_text(json.dumps(initial_state))

            now = _frozen_now_2026()

            # Engine 1: should load the persisted commit
            eng1 = _make_engine(now=lambda: now)
            eng1.settings = eng1.settings.model_copy(update={"state_file": str(state_file)})
            eng1._last_commit = eng1._load_state()

            assert eng1._last_commit == {"main": "commit-aaa"}

            # Simulate a cycle: changes_since should be called with "commit-aaa"
            eng1.tdb.changes_since = AsyncMock(return_value=([], "head2"))
            await eng1.run_cycle()

            # After the cycle, last_commit should be "head2"
            assert eng1._last_commit == {"main": "head2"}

            # Engine 2: new instance, same state file — should load "head2"
            eng2 = _make_engine(now=lambda: now)
            eng2.settings = eng2.settings.model_copy(update={"state_file": str(state_file)})
            loaded = eng2._load_state()
            assert loaded == {"main": "head2"}, f"Expected head2, got {loaded}"
        finally:
            state_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_corrupt_state_file_tolerated(self):
        """A corrupt/missing state file is tolerated → no crash, empty dict."""
        import json
        import tempfile
        from pathlib import Path

        state_file = Path(tempfile.gettempdir()) / f"test-triggerd-corrupt-{id(self)}.json"
        state_file.unlink(missing_ok=True)

        try:
            # Corrupt JSON
            state_file.write_text("not json {{{")

            now = _frozen_now_2026()
            eng = _make_engine(now=lambda: now)
            eng.settings = eng.settings.model_copy(update={"state_file": str(state_file)})
            loaded = eng._load_state()
            assert loaded == {}
        finally:
            state_file.unlink(missing_ok=True)


class TestGraphQLFallback:
    """GraphQL abstract Triggerable query failure falls back to per-subclass queries."""

    @pytest.mark.asyncio
    async def test_fallback_resolves_via_concrete_subclasses(self):
        """When abstract Triggerable query fails, fallback queries each concrete subclass."""
        now = _frozen_now_2026()
        fire_at = _utc_iso(now - timedelta(seconds=60))
        engine = _make_engine(
            now=lambda: now,
            trigger_docs=[
                {
                    "@id": "OneShotTrigger/t1",
                    "@type": "OneShotTrigger",
                    "enabled": True,
                    "fire_at": fire_at,
                },
            ],
            schema_entries=[
                {"@id": "Triggerable", "@type": "Class", "@abstract": True},
                {"@id": "Reminder", "@type": "Class", "@inherits": "Triggerable"},
                {"@id": "Routine", "@type": "Class", "@inherits": "Triggerable"},
                {"@id": "AbstractTriggerable", "@type": "Class", "@abstract": True, "@inherits": "Triggerable"},
            ],
        )

        # First GraphQL call (abstract) fails, then per-subclass queries succeed
        call_count = 0

        async def _graphql(query, variables=None, branch="main"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Abstract Triggerable query → fail
                raise TdbError(400, '{"errors":[{"message":"Cannot query field"}]}')
            elif "Reminder" in query:
                return {"Reminder": [{"_id": "Reminder/r1"}]}
            elif "Routine" in query:
                return {"Routine": []}
            return {}

        engine.tdb.graphql = _graphql

        with structlog.testing.capture_logs() as captured:
            subject = await engine._resolve_subject("OneShotTrigger/t1", "main")

        assert subject == "Reminder/r1"
        warn_events = [e for e in captured if e.get("event") == "triggerable_abstract_query_failed"]
        assert len(warn_events) == 1

    @pytest.mark.asyncio
    async def test_fallback_zero_or_many_returns_none(self):
        """Fallback path: zero subclasses or ambiguous results → None."""
        engine = _make_engine(
            schema_entries=[
                {"@id": "Triggerable", "@type": "Class", "@abstract": True},
                {"@id": "Reminder", "@type": "Class", "@inherits": "Triggerable"},
            ],
        )

        # Abstract query fails, Reminder query returns 2 results → ambiguous
        call_count = 0

        async def _graphql(query, variables=None, branch="main"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TdbError(400, "fail")
            return {"Reminder": [{"_id": "Reminder/r1"}, {"_id": "Reminder/r2"}]}

        engine.tdb.graphql = _graphql

        with structlog.testing.capture_logs() as captured:
            subject = await engine._resolve_subject("OneShotTrigger/t1", "main")

        assert subject is None
        ambiguous = [e for e in captured if e.get("event") == "subject_ambiguous"]
        assert len(ambiguous) == 1
        assert ambiguous[0]["count"] == 2


class TestStaleCommitRecovery:
    """Engine recovers from a stale change-cursor instead of crash-looping."""

    @pytest.mark.asyncio
    async def test_stale_commit_rebaselines_and_continues(self):
        """When changes_since raises StaleCommitError on a persisted commit,
        the engine logs a warning, re-baselines with None, and continues
        without producing any firings. The last_commit advances to the new head
        and is persisted to the state file."""
        import json
        import tempfile
        from pathlib import Path

        state_file = Path(tempfile.gettempdir()) / f"test-triggerd-stale-{id(self)}.json"
        state_file.unlink(missing_ok=True)

        now = _frozen_now_2026()

        # Persist a stale commit so the engine loads it
        initial_state = {"main": "deadbeef"}
        state_file.write_text(json.dumps(initial_state))

        try:
            engine = _make_engine(
                now=lambda: now,
                trigger_docs=[
                    {
                        "@id": "EventTrigger/ev1",
                        "@type": "EventTrigger",
                        "enabled": True,
                        "event": "created",
                    },
                ],
                evaluators=[EventTriggerEvaluator()],
            )
            # Override state_file so _load_state reads our stale commit
            engine.settings = engine.settings.model_copy(update={"state_file": str(state_file)})
            engine._last_commit = engine._load_state()
            assert engine._last_commit == {"main": "deadbeef"}

            call_count = 0

            async def _changes_since(commit_id, branch):
                nonlocal call_count
                call_count += 1
                if commit_id == "deadbeef":
                    raise StaleCommitError("deadbeef", branch)
                # second call: baseline with None
                return ([], "newhead123")

            engine.tdb.changes_since = _changes_since

            inserted_docs = []

            async def _record(docs, branch="main", message="", author=""):
                inserted_docs.extend(docs)
                return ["fake"]

            engine.tdb.insert_documents.side_effect = _record

            with structlog.testing.capture_logs() as captured:
                await engine.run_cycle()

            # Warning was logged
            warnings = [e for e in captured if e.get("event") == "cursor_stale_rebaselined"]
            assert len(warnings) == 1
            assert warnings[0]["branch"] == "main"
            assert warnings[0]["stale_commit"] == "deadbeef"

            # Cycle completed normally
            summary = [e for e in captured if e.get("event") == "cycle_complete"]
            assert len(summary) == 1
            assert summary[0]["firings_written"] == 0

            # No firings produced (empty changes)
            assert len(inserted_docs) == 0

            # Last commit advanced to the new head
            assert engine._last_commit == {"main": "newhead123"}

            # Persisted state file reflects the new head
            saved = json.loads(state_file.read_text())
            assert saved == {"main": "newhead123"}

            # changes_since was called exactly twice (stale + baseline)
            assert call_count == 2
        finally:
            state_file.unlink(missing_ok=True)
