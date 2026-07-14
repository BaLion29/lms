"""Tests for trigger evaluators — correctness, DST handling, edge cases."""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from triggerd.evaluators import (
    OneShotEvaluator,
    RelativeEvaluator,
    ScheduleEvaluator,
    CompositeEvaluator,
    EventTriggerEvaluator,
    _class_short_name,
    resolve_anchor,
    oneshot_plugin,
    schedule_plugin,
    relative_plugin,
    composite_plugin,
    event_plugin,
)
from firnline_core.plugins import EvalContext, TriggerEvaluator
from firnline_core.tdb import ChangeEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
ZURICH = ZoneInfo("Europe/Zurich")

# DST transition dates 2026
# Last Sunday of March: 2026-03-29 (spring forward: CET → CEST)
# Last Sunday of October: 2026-10-25 (fall back: CEST → CET)

MARCH_28 = datetime(2026, 3, 28, tzinfo=UTC)  # Still winter (CET, UTC+1)
MARCH_30 = datetime(2026, 3, 30, tzinfo=UTC)  # Summer (CEST, UTC+2)
OCT_24 = datetime(2026, 10, 24, tzinfo=UTC)  # Still summer
OCT_26 = datetime(2026, 10, 26, tzinfo=UTC)  # Winter


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _make_ctx(tdb=None, default_tz=ZURICH, now=None, resolve_anchor=None, get_occurrences=None, changes=None):
    """Build a minimal EvalContext for testing."""
    if tdb is None:
        tdb = AsyncMock()
    if now is None:
        now = _utc_now
    if resolve_anchor is None:
        resolve_anchor = AsyncMock(return_value=None)
    if get_occurrences is None:
        get_occurrences = AsyncMock(return_value=[])
    if changes is None:
        changes = []
    return EvalContext(
        tdb=tdb,
        default_tz=default_tz,
        now=now,
        resolve_anchor=resolve_anchor,
        get_occurrences=get_occurrences,
        changes=changes,
    )


# ---------------------------------------------------------------------------
# OneShotEvaluator
# ---------------------------------------------------------------------------


class TestOneShotEvaluator:
    @pytest.mark.asyncio
    async def test_inside_window(self):
        ev = OneShotEvaluator()
        trigger = {"@type": "OneShotTrigger", "fire_at": "2026-07-06T09:00:00Z"}
        ws = datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=_make_ctx())
        assert result == [datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)]

    @pytest.mark.asyncio
    async def test_at_window_end_fires(self):
        """Half-open: fire_at == window_end fires."""
        ev = OneShotEvaluator()
        trigger = {"@type": "OneShotTrigger", "fire_at": "2026-07-06T09:00:00Z"}
        ws = datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=_make_ctx())
        assert result == [datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)]

    @pytest.mark.asyncio
    async def test_at_window_start_does_not_fire(self):
        """Half-open: fire_at == window_start does NOT fire."""
        ev = OneShotEvaluator()
        trigger = {"@type": "OneShotTrigger", "fire_at": "2026-07-06T09:00:00Z"}
        ws = datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=_make_ctx())
        assert result == []

    @pytest.mark.asyncio
    async def test_outside_window(self):
        ev = OneShotEvaluator()
        trigger = {"@type": "OneShotTrigger", "fire_at": "2026-07-06T09:00:00Z"}
        ws = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 11, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=_make_ctx())
        assert result == []

    @pytest.mark.asyncio
    async def test_naive_fire_at_treated_as_utc(self):
        ev = OneShotEvaluator()
        trigger = {"@type": "OneShotTrigger", "fire_at": "2026-07-06T09:00:00"}
        ws = datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=_make_ctx())
        assert result == [datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)]


# ---------------------------------------------------------------------------
# ScheduleEvaluator — core & DST
# ---------------------------------------------------------------------------


class TestScheduleEvaluator:
    @pytest.mark.asyncio
    async def test_daily_7am_zurich_winter_utc_6am(self):
        """Winter (CET=UTC+1): 07:00 Zurich → 06:00 UTC."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-03-28T06:00:00Z",  # 07:00 Zurich in winter
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
        }
        ctx = _make_ctx(default_tz=ZURICH)
        ws = datetime(2026, 3, 28, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 3, 29, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert len(result) == 1
        assert result[0] == datetime(2026, 3, 28, 6, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_daily_7am_zurich_summer_utc_5am(self):
        """Summer (CEST=UTC+2): 07:00 Zurich → 05:00 UTC."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-03-28T06:00:00Z",
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
        }
        ctx = _make_ctx(default_tz=ZURICH)
        ws = datetime(2026, 3, 30, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 3, 31, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert len(result) == 1
        assert result[0] == datetime(2026, 3, 30, 5, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_daily_7am_zurich_autumn_transition(self):
        """Around autumn fall-back: Oct 24 (CEST) → 05:00Z, Oct 26 (CET) → 06:00Z."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-10-01T05:00:00Z",  # 07:00 Zurich in summer
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
        }
        ctx = _make_ctx(default_tz=ZURICH)

        # Oct 24 — still CEST (UTC+2)
        ws = datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 10, 25, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert result == [datetime(2026, 10, 24, 5, 0, 0, tzinfo=UTC)]

        # Oct 26 — CET (UTC+1)
        ws = datetime(2026, 10, 26, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 10, 27, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert result == [datetime(2026, 10, 26, 6, 0, 0, tzinfo=UTC)]

    @pytest.mark.asyncio
    async def test_trigger_timezone_overrides_default(self):
        """When trigger.timezone is set, it's used instead of default_tz."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-07-06T04:00:00Z",  # 07:00 in Moscow
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
            "timezone": "Europe/Moscow",
        }
        # default_tz is ZURICH, but trigger says Moscow (UTC+3)
        ctx = _make_ctx(default_tz=ZURICH)
        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        # 07:00 Moscow = 04:00 UTC
        assert result == [datetime(2026, 7, 6, 4, 0, 0, tzinfo=UTC)]

    @pytest.mark.asyncio
    async def test_invalid_timezone_falls_back_with_warning(self):
        """Invalid timezone name → warning + fallback to default_tz."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-07-06T04:00:00Z",  # 06:00 Zurich (< BYHOUR=7, so fires same day)
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
            "timezone": "Nope/Nowhere",
        }
        ctx = _make_ctx(default_tz=ZURICH)
        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 1  # Falls back to Zurich
        assert any("schedule_timezone_invalid" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_malformed_rrule_warning_empty(self):
        """Malformed rrule → WARNING + empty list."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-07-06T06:00:00Z",
            "rrule": "THIS_IS_NOT_VALID",
        }
        ctx = _make_ctx()
        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        assert any("schedule_rrule_invalid" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_half_open_start_excluded(self):
        """Rule occurrences exactly at window_start are excluded."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-03-28T06:00:00Z",
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
        }
        ctx = _make_ctx(default_tz=ZURICH)
        # window_start at 06:00Z (07:00 Zurich) — should NOT include
        ws = datetime(2026, 3, 28, 6, 0, 0, tzinfo=UTC)
        we = datetime(2026, 3, 28, 7, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_rrule_at_window_end_fires(self):
        """Rule occurrence exactly at window_end DOES fire (half-open)."""
        ev = ScheduleEvaluator()
        trigger = {
            "@type": "ScheduleTrigger",
            "dtstart": "2026-03-28T06:00:00Z",
            "rrule": "FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
        }
        ctx = _make_ctx(default_tz=ZURICH)
        # 07:00 Zurich on Mar 28 = 06:00 UTC; set window_end to exactly that
        ws = datetime(2026, 3, 28, 5, 0, 0, tzinfo=UTC)
        we = datetime(2026, 3, 28, 6, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert result == [datetime(2026, 3, 28, 6, 0, 0, tzinfo=UTC)]


# ---------------------------------------------------------------------------
# _class_short_name
# ---------------------------------------------------------------------------


class TestClassShortName:
    def test_plain_type(self):
        assert _class_short_name("Reminder") == "Reminder"

    def test_slash_prefixed(self):
        assert _class_short_name("terminusdb:///data/Reminder") == "Reminder"

    def test_hash_prefixed(self):
        assert _class_short_name("terminusdb:///schema#Task") == "Task"

    def test_empty(self):
        assert _class_short_name("") == ""


# ---------------------------------------------------------------------------
# RelativeEvaluator
# ---------------------------------------------------------------------------

_ANCHOR_MAP = {"Reminder": "due_date", "Event": "start_at", "Task": "deadline"}


class TestRelativeEvaluator:
    @pytest.mark.asyncio
    async def test_task_offset_minus_15m(self):
        """Task with due_date, offset "-PT15M" fires 15 min before."""
        ev = RelativeEvaluator()
        trigger = {
            "@type": "RelativeTrigger",
            "anchor": "doc/Task/abc",
            "offset": "-PT15M",
        }

        anchor_dt = datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
        resolve = AsyncMock(return_value=anchor_dt)
        ctx = _make_ctx(resolve_anchor=resolve)

        ws = datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        expected = datetime(2026, 7, 6, 8, 45, 0, tzinfo=UTC)
        assert result == [expected]
        resolve.assert_called_once_with("doc/Task/abc")

    @pytest.mark.asyncio
    async def test_anchor_none_returns_empty(self):
        """anchor → None (unsupported class) → empty list, no crash."""
        ev = RelativeEvaluator()
        trigger = {
            "@type": "RelativeTrigger",
            "anchor": "doc/Reminder/xyz",
            "offset": "PT1H",
        }
        resolve = AsyncMock(return_value=None)
        ctx = _make_ctx(resolve_anchor=resolve)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_offset_warning_empty(self):
        """Malformed offset → WARNING + empty list."""
        ev = RelativeEvaluator()
        trigger = {
            "@type": "RelativeTrigger",
            "anchor": "doc/Task/abc",
            "offset": "not-a-duration",
        }
        resolve = AsyncMock(return_value=datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC))
        ctx = _make_ctx(resolve_anchor=resolve)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        assert any("relative_offset_invalid" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_anchor_resolve_uses_class_anchor_field(self):
        """resolve_anchor reads the class's anchor_field from the map."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Reminder", "@id": "doc/Reminder/x", "due_date": "2026-07-06T09:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Reminder/x", class_anchor_fields=_ANCHOR_MAP)
        assert result == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_via_dict_ref(self):
        """resolve_anchor works with a dict ref (not IRI fetch)."""
        tdb = AsyncMock()
        doc = {"@type": "Event", "@id": "doc/Event/e", "start_at": "2026-07-06T09:00:00Z"}
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, doc, class_anchor_fields=_ANCHOR_MAP)
        assert result == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_no_anchor_field_metadata(self):
        """Class has no anchor_field in the map → dormant (no anchor_field)."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Foobar", "@id": "doc/Foobar/f", "due_date": "2026-07-06T09:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Foobar/f", class_anchor_fields=_ANCHOR_MAP)

        assert result is None
        dormant = [e for e in captured if e.get("event") == "trigger_dormant"]
        assert len(dormant) == 1
        assert dormant[0]["reason"] == "no anchor_field"

    @pytest.mark.asyncio
    async def test_anchor_field_missing_from_doc(self):
        """Doc has class in map but the field is not set → dormant (anchor unset)."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Reminder", "@id": "doc/Reminder/r", "title": "test"}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Reminder/r", class_anchor_fields=_ANCHOR_MAP)

        assert result is None
        dormant = [e for e in captured if e.get("event") == "trigger_dormant"]
        assert len(dormant) == 1
        assert dormant[0]["reason"] == "anchor unset"

    @pytest.mark.asyncio
    async def test_anchor_null_field_returns_none(self):
        """Anchor field explicitly null → dormant (anchor unset)."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Task", "@id": "doc/Task/t", "deadline": None}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Task/t", class_anchor_fields=_ANCHOR_MAP)

        assert result is None
        dormant = [e for e in captured if e.get("event") == "trigger_dormant"]
        assert len(dormant) == 1
        assert dormant[0]["reason"] == "anchor unset"

    @pytest.mark.asyncio
    async def test_anchor_malformed_value_returns_none(self):
        """Malformed anchor field value → None (debug logged)."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Reminder", "@id": "doc/Reminder/r", "due_date": "not-a-date"}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Reminder/r", class_anchor_fields=_ANCHOR_MAP)

        assert result is None
        assert any("anchor_parse_failed" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_anchor_present(self):
        """Anchor field resolved correctly via map."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Event", "@id": "doc/Event/e", "start_at": "2026-07-06T09:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Event/e", class_anchor_fields=_ANCHOR_MAP)
        assert result == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_prefixed_iri_type(self):
        """resolve_anchor handles prefixed @type IRIs."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={
                "@type": "terminusdb:///schema#Reminder",
                "@id": "doc/Reminder/x",
                "due_date": "2026-07-06T09:00:00Z",
            }
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Reminder/x", class_anchor_fields=_ANCHOR_MAP)
        assert result == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_map_none_returns_none(self):
        """When class_anchor_fields is None (backward compat), returns None with dormant log."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Reminder", "@id": "doc/Reminder/x", "due_date": "2026-07-06T09:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Reminder/x", class_anchor_fields=None)

        assert result is None
        dormant = [e for e in captured if e.get("event") == "trigger_dormant"]
        assert len(dormant) == 1
        assert dormant[0]["reason"] == "no anchor_field"


# ---------------------------------------------------------------------------
# CompositeEvaluator
# ---------------------------------------------------------------------------


class TestCompositeEvaluator:
    @pytest.mark.asyncio
    async def test_any_mode_union(self):
        """Two OneShot operands in any mode → union of fire times."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/main",
            "mode": "any",
            "operands": ["doc/OneShotTrigger/a", "doc/OneShotTrigger/b"],
        }

        t1 = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/a", "fire_at": "2026-07-06T09:00:00Z"}
        t2 = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/b", "fire_at": "2026-07-06T10:00:00Z"}

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[t1, t2])

        async def fake_get_occurrences(trig, ws, we, visited):
            ev2 = OneShotEvaluator()
            return await ev2.occurrences(trig, window_start=ws, window_end=we, ctx=_make_ctx())

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 6, 23, 59, 59, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == [
            datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC),
        ]
        assert tdb.get_document.call_count == 2

    @pytest.mark.asyncio
    async def test_self_reference_cycle_warning(self):
        """Composite with self in operands → cycle warning, no infinite loop."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/self",
            "mode": "any",
            "operands": ["doc/CompositeTrigger/self"],
        }
        tdb = AsyncMock()
        # get_document won't be called for the self-iri because visited catches it first
        ctx = _make_ctx(tdb=tdb)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        assert any("composite_cycle_detected" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_nested_cycle_a_b_a(self):
        """A→B→A cycle detected."""
        ev = CompositeEvaluator()
        trigger_a = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/a",
            "mode": "any",
            "operands": ["doc/CompositeTrigger/b"],
        }
        trigger_b = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/b",
            "mode": "any",
            "operands": ["doc/CompositeTrigger/a"],
        }

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(return_value=trigger_b)

        # get_occurrences recurses only once (for b)
        fake_get_occurrences = AsyncMock(return_value=[])

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        result = await ev.occurrences(trigger_a, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        # The get_occurrences call for b should detect a cycle (a is visited)
        assert fake_get_occurrences.call_count == 1

        called_visited = fake_get_occurrences.call_args[0][3]
        assert "doc/CompositeTrigger/a" in called_visited

    @pytest.mark.asyncio
    async def test_all_mode_missing_window_warning(self):
        """mode=all without window → warning + empty."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/allnowin",
            "mode": "all",
            "operands": ["doc/OneShotTrigger/a", "doc/OneShotTrigger/b"],
        }
        ctx = _make_ctx()

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        assert any("composite_all_missing_window" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_unsupported_mode_warning(self):
        """Unsupported mode → composite_mode_unsupported warning + empty."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/bad",
            "mode": "or",
            "operands": ["doc/OneShotTrigger/a"],
        }
        ctx = _make_ctx()

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []
        assert any("composite_mode_unsupported" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_all_mode_coincidence_window(self):
        """mode=all with window: coincidence working correctly."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/all",
            "mode": "all",
            "window": "PT5M",
            "operands": ["doc/OneShotTrigger/a", "doc/OneShotTrigger/b"],
        }

        # a has instants at 09:00, 09:10; b at 09:02, 10:00
        t_a = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/a", "fire_at": "2026-07-06T09:00:00Z"}
        t_b = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/b", "fire_at": "2026-07-06T09:02:00Z"}

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[t_a, t_b])

        ctx = _make_ctx(tdb=tdb)

        # Provide a get_occurrences that returns what OneShot would produce
        async def fake_get_occurrences(trig, ws, we, visited):
            ev2 = OneShotEvaluator()
            return await ev2.occurrences(trig, window_start=ws, window_end=we, ctx=_make_ctx())

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        # 09:00 qualifies because b has 09:02 within [09:00, 09:05]
        assert result == [datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)]

    @pytest.mark.asyncio
    async def test_all_mode_no_coincidence(self):
        """mode=all: no coincidence when operands are too far apart."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/all",
            "mode": "all",
            "window": "PT5M",
            "operands": ["doc/OneShotTrigger/a", "doc/OneShotTrigger/b"],
        }

        t_a = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/a", "fire_at": "2026-07-06T09:00:00Z"}
        t_b = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/b", "fire_at": "2026-07-06T10:00:00Z"}

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[t_a, t_b])

        async def fake_get_occurrences(trig, ws, we, visited):
            ev2 = OneShotEvaluator()
            return await ev2.occurrences(trig, window_start=ws, window_end=we, ctx=_make_ctx())

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        # 09:00 doesn't qualify: b's 10:00 is not within [09:00, 09:05]
        assert result == []

    @pytest.mark.asyncio
    async def test_operand_fetch_failure_warning(self):
        """Operand get_document raises → warning + skip."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/main",
            "mode": "any",
            "operands": ["doc/OneShotTrigger/broken", "doc/OneShotTrigger/ok"],
        }
        ok_trigger = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/ok", "fire_at": "2026-07-06T10:00:00Z"}

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[RuntimeError("fetch failed"), ok_trigger])

        async def fake_get_occurrences(trig, ws, we, visited):
            ev2 = OneShotEvaluator()
            return await ev2.occurrences(trig, window_start=ws, window_end=we, ctx=_make_ctx())

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == [datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)]
        assert any("composite_operand_fetch_failed" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_diamond_no_false_cycle_union(self):
        """Diamond A→(B,C), B→D, C→D with OneShot D: union contains D once, no cycle warning."""
        ev = CompositeEvaluator()
        # D is a OneShot trigger shared by B and C
        trigger_d = {"@type": "OneShotTrigger", "@id": "doc/OneShotTrigger/d", "fire_at": "2026-07-06T09:00:00Z"}

        trigger_b = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/b",
            "mode": "any",
            "operands": ["doc/OneShotTrigger/d"],
        }
        trigger_c = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/c",
            "mode": "any",
            "operands": ["doc/OneShotTrigger/d"],
        }
        trigger_a = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/a",
            "mode": "any",
            "operands": ["doc/CompositeTrigger/b", "doc/CompositeTrigger/c"],
        }

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[trigger_b, trigger_c, trigger_d, trigger_d])

        async def fake_get_occurrences(trig, ws, we, visited):
            if trig.get("@type") == "CompositeTrigger":
                return await ev._eval_any(
                    trig, ws, we, _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences), visited
                )
            ev2 = OneShotEvaluator()
            return await ev2.occurrences(trig, window_start=ws, window_end=we, ctx=_make_ctx())

        ctx = _make_ctx(tdb=tdb, get_occurrences=fake_get_occurrences)

        ws = datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC)
        we = datetime(2026, 7, 7, 0, 0, 0, tzinfo=UTC)

        with structlog.testing.capture_logs() as captured:
            result = await ev.occurrences(trigger_a, window_start=ws, window_end=we, ctx=ctx)

        # D fires once, deduplicated by instant
        assert result == [datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)]
        # No cycle warning emitted
        assert not any("composite_cycle_detected" in r.get("event", "") for r in captured)
        # D fetched once per branch (twice total), not skipped on second branch
        assert tdb.get_document.call_count == 4  # B, C, D (via B), D (via C)


# ---------------------------------------------------------------------------
# EventTriggerEvaluator
# ---------------------------------------------------------------------------


class TestEventTriggerEvaluator:
    """EventTrigger evaluator — created/updated/status_changed, subject matching, commit keys."""

    def _make_change(
        self,
        commit_id: str = "abc123",
        timestamp: float = 1718234567.0,
        inserted: list[str] | None = None,
        updated: list[str] | None = None,
    ) -> ChangeEvent:
        return ChangeEvent(
            commit_id=commit_id,
            author="tester",
            message="test commit",
            timestamp=timestamp,
            inserted=inserted or [],
            updated=updated or [],
            deleted=[],
        )

    @pytest.mark.asyncio
    async def test_created_matches_inserted(self):
        """kind=created: fires on inserted IRIs."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "@id": "EventTrigger/ev1", "event": "created"}
        change = self._make_change(inserted=["Task/t1", "Project/p1"])
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 2
        # Both instants are equal (same change timestamp), dict has one key
        instant = result[0]
        keys = ev._event_keys.get("EventTrigger/ev1", {}).get(instant, [])
        assert len(keys) == 2
        # New key format: commit_id[:12]-sha256[:12]
        assert all("abc123" in k for k in keys)
        # Verify determinism: same candidate IRI → same hash
        from triggerd.evaluators import _make_event_key
        assert _make_event_key("abc123", "Task/t1") == _make_event_key("abc123", "Task/t1")

    @pytest.mark.asyncio
    async def test_updated_matches_updated(self):
        """kind=updated: fires on updated IRIs."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "@id": "EventTrigger/ev2", "event": "updated"}
        change = self._make_change(updated=["Reminder/r1"])
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 1
        instant = result[0]
        keys = ev._event_keys.get("EventTrigger/ev2", {}).get(instant, [])
        assert len(keys) == 1
        assert keys[0].startswith("abc123")

    @pytest.mark.asyncio
    async def test_subject_iri_filter(self):
        """Only matching subject IRI fires."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "event": "created", "subject": "Task/t1"}
        change = self._make_change(inserted=["Task/t1", "Task/t2"])
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_subject_class_prefix_filter(self):
        """subject_class filtering via prefix match."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "event": "created", "subject_class": "Task"}
        change = self._make_change(inserted=["Task/t1", "Project/p1"])
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_status_changed_with_field_to_value(self):
        """status_changed with field/to_value: fetches doc and checks equality."""
        ev = EventTriggerEvaluator()
        trigger = {
            "@type": "EventTrigger",
            "event": "status_changed",
            "field": "status",
            "to_value": "done",
        }
        change = self._make_change(updated=["Task/t1", "Task/t2"])

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[
            {"@id": "Task/t1", "status": "done"},
            {"@id": "Task/t2", "status": "open"},
        ])
        ctx = _make_ctx(tdb=tdb, changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        # Only Task/t1 has status=done
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_changes_empty(self):
        """Empty changes list → no firings."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "event": "created"}
        ctx = _make_ctx(changes=[])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []

    @pytest.mark.asyncio
    async def test_timestamp_fallback_to_window_end(self):
        """ChangeEvent with no timestamp → falls back to window_end."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "event": "created"}
        change = ChangeEvent(
            commit_id="def456",
            author="tester",
            message="test",
            timestamp=None,
            inserted=["Task/t1"],
            updated=[],
            deleted=[],
        )
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert len(result) == 1
        assert result[0] == we

    @pytest.mark.asyncio
    async def test_unsupported_event_kind_empty(self):
        """Unknown event kind → empty list."""
        ev = EventTriggerEvaluator()
        trigger = {"@type": "EventTrigger", "event": "completed"}
        change = self._make_change(inserted=["Task/t1"])
        ctx = _make_ctx(changes=[change])

        ws = datetime(2026, 1, 1, tzinfo=UTC)
        we = datetime(2026, 12, 31, tzinfo=UTC)
        result = await ev.occurrences(trigger, window_start=ws, window_end=we, ctx=ctx)

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_triggers_isolated_keys(self):
        """Two EventTriggers in one cycle do not clobber each other's keys."""
        ev = EventTriggerEvaluator()
        t1 = {"@type": "EventTrigger", "@id": "EventTrigger/a", "event": "created"}
        t2 = {"@type": "EventTrigger", "@id": "EventTrigger/b", "event": "created"}
        change = self._make_change(inserted=["Task/x"])
        ctx = _make_ctx(changes=[change])

        r1 = await ev.occurrences(t1, window_start=datetime(2026, 1, 1, tzinfo=UTC),
                                  window_end=datetime(2026, 12, 31, tzinfo=UTC), ctx=ctx)
        r2 = await ev.occurrences(t2, window_start=datetime(2026, 1, 1, tzinfo=UTC),
                                  window_end=datetime(2026, 12, 31, tzinfo=UTC), ctx=ctx)

        # Both triggers should have fired.
        assert len(r1) == 1
        assert len(r2) == 1

        # Each trigger's keys are isolated.
        keys_a = ev._event_keys.get("EventTrigger/a", {}).get(r1[0], [])
        keys_b = ev._event_keys.get("EventTrigger/b", {}).get(r2[0], [])
        assert len(keys_a) == 1
        assert len(keys_b) == 1
        # Keys should be identical (same commit_id, same candidate IRI)
        assert keys_a == keys_b


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_oneshot_isinstance_trigger_evaluator(self):
        assert isinstance(oneshot_plugin, TriggerEvaluator)

    def test_schedule_isinstance_trigger_evaluator(self):
        assert isinstance(schedule_plugin, TriggerEvaluator)

    def test_relative_isinstance_trigger_evaluator(self):
        assert isinstance(relative_plugin, TriggerEvaluator)

    def test_composite_isinstance_trigger_evaluator(self):
        assert isinstance(composite_plugin, TriggerEvaluator)

    def test_event_isinstance_trigger_evaluator(self):
        assert isinstance(event_plugin, TriggerEvaluator)

    @pytest.mark.parametrize(
        "plugin",
        [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin, event_plugin],
    )
    def test_plugin_has_required_attributes(self, plugin):
        assert hasattr(plugin, "name")
        assert isinstance(plugin.name, str)
        assert hasattr(plugin, "requires")
        assert isinstance(plugin.requires, list)
        assert hasattr(plugin, "trigger_types")
        assert isinstance(plugin.trigger_types, tuple)
        assert hasattr(plugin, "occurrences")
        assert callable(plugin.occurrences)

    def test_all_have_trigger_module_requirement(self):
        for plugin in [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin, event_plugin]:
            assert any(r.name == "triggers" for r in plugin.requires)

    def test_duck_type_compatible_with_main_py(self):
        """Verify each plugin passes main.py's duck-type check filters."""
        for plugin in [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin, event_plugin]:
            assert hasattr(plugin, "name")
            trigger_types = plugin.trigger_types
            assert isinstance(trigger_types, (tuple, list))
            assert callable(plugin.occurrences)


# ---------------------------------------------------------------------------
# EvalContext shape
# ---------------------------------------------------------------------------


class TestEvalContext:
    def test_minimal_construction(self):
        tdb = AsyncMock()
        ctx = _make_ctx(tdb=tdb)
        assert ctx.tdb is tdb
        assert ctx.default_tz == ZURICH
        assert callable(ctx.now)
        assert callable(ctx.resolve_anchor)
        assert callable(ctx.get_occurrences)
