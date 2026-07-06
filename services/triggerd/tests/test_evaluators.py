"""Tests for trigger evaluators — correctness, DST handling, edge cases."""

from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from triggerd.evaluators import (
    OneShotEvaluator,
    RelativeEvaluator,
    ScheduleEvaluator,
    CompositeEvaluator,
    _parse_duration,
    _parse_iso_datetime,
    resolve_anchor,
    oneshot_plugin,
    schedule_plugin,
    relative_plugin,
    composite_plugin,
)
from firnline_core.plugins import EvalContext, TriggerEvaluator

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


def _make_ctx(tdb=None, default_tz=ZURICH, now=None, resolve_anchor=None, get_occurrences=None):
    """Build a minimal EvalContext for testing."""
    if tdb is None:
        tdb = AsyncMock()
    if now is None:
        now = _utc_now
    if resolve_anchor is None:
        resolve_anchor = AsyncMock(return_value=None)
    if get_occurrences is None:
        get_occurrences = AsyncMock(return_value=[])
    return EvalContext(
        tdb=tdb,
        default_tz=default_tz,
        now=now,
        resolve_anchor=resolve_anchor,
        get_occurrences=get_occurrences,
    )


# ---------------------------------------------------------------------------
# _parse_iso_datetime
# ---------------------------------------------------------------------------


class TestParseIsoDatetime:
    def test_z_suffix(self):
        assert _parse_iso_datetime("2026-07-06T09:00:00Z") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_offset(self):
        assert _parse_iso_datetime("2026-07-06T11:00:00+02:00") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_naive_treated_as_utc(self):
        assert _parse_iso_datetime("2026-07-06T09:00:00") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_subsecond(self):
        result = _parse_iso_datetime("2026-07-06T09:00:00.500Z")
        assert result == datetime(2026, 7, 6, 9, 0, 0, 500000, tzinfo=UTC)


# ---------------------------------------------------------------------------
# _parse_duration
# ---------------------------------------------------------------------------


class TestParseDuration:
    def test_days_only(self):
        assert _parse_duration("P1D") == timedelta(days=1)

    def test_hours_minutes(self):
        assert _parse_duration("PT2H30M") == timedelta(hours=2, minutes=30)

    def test_full(self):
        assert _parse_duration("P1DT2H30M15S") == timedelta(days=1, hours=2, minutes=30, seconds=15)

    def test_negative(self):
        assert _parse_duration("-PT15M") == timedelta(minutes=-15)

    def test_negative_with_days(self):
        assert _parse_duration("-P1DT1H") == timedelta(days=-1, hours=-1)

    def test_pt_only(self):
        assert _parse_duration("PT1H") == timedelta(hours=1)

    @pytest.mark.parametrize("bad", ["garbage", "P", "T1H", "P1DT", "1D", "P1H", "", "P1M", "P2Y"])
    def test_malformed_returns_none(self, bad):
        assert _parse_duration(bad) is None


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
# RelativeEvaluator
# ---------------------------------------------------------------------------


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
    async def test_anchor_resolve_unsupported_class_warns(self):
        """resolve_anchor for Reminder → warning + None."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(return_value={"@type": "Reminder", "@id": "doc/Reminder/x", "name": "x"})
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Reminder/x")

        assert result is None
        assert any("anchor_unsupported" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_anchor_missing_field_warns(self):
        """Event without start_datetime → warning + None."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Event", "@id": "doc/Event/e", "name": "e", "start_datetime": None}
        )
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Event/e")

        assert result is None
        assert any("anchor_field_missing" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_anchor_unknown_type_warns(self):
        """Unknown @type → warning + None."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(return_value={"@type": "Foobar", "@id": "doc/Foobar/f"})
        ctx = _make_ctx(tdb=tdb)

        with structlog.testing.capture_logs() as captured:
            result = await resolve_anchor(ctx, "doc/Foobar/f")

        assert result is None
        assert any("anchor_unsupported" in r.get("event", "") for r in captured)

    @pytest.mark.asyncio
    async def test_anchor_event_start_datetime(self):
        """Event → start_datetime is resolved."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Event", "@id": "doc/Event/e", "start_datetime": "2026-07-06T09:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Event/e")
        assert result == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_task_due_date(self):
        """Task → due_date is resolved."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Task", "@id": "doc/Task/t", "due_date": "2026-12-01T12:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Task/t")
        assert result == datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_anchor_activity_start_datetime(self):
        """Activity → start_datetime is resolved."""
        tdb = AsyncMock()
        tdb.get_document = AsyncMock(
            return_value={"@type": "Activity", "@id": "doc/Activity/a", "start_datetime": "2026-01-01T00:00:00Z"}
        )
        ctx = _make_ctx(tdb=tdb)
        result = await resolve_anchor(ctx, "doc/Activity/a")
        assert result == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# CompositeEvaluator
# ---------------------------------------------------------------------------


class TestCompositeEvaluator:
    @pytest.mark.asyncio
    async def test_or_mode_union(self):
        """Two OneShot operands in or mode → union of fire times."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/main",
            "mode": "or",
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
            "mode": "or",
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
            "mode": "or",
            "operands": ["doc/CompositeTrigger/b"],
        }
        trigger_b = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/b",
            "mode": "or",
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
    async def test_and_mode_unsupported_warning(self):
        """mode=and → composite_mode_unsupported warning + empty."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/and",
            "mode": "and",
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
    async def test_not_mode_unsupported_warning(self):
        """mode=not → composite_mode_unsupported warning + empty."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/not",
            "mode": "not",
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
    async def test_operand_fetch_failure_warning(self):
        """Operand get_document raises → warning + skip."""
        ev = CompositeEvaluator()
        trigger = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/main",
            "mode": "or",
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
            "mode": "or",
            "operands": ["doc/OneShotTrigger/d"],
        }
        trigger_c = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/c",
            "mode": "or",
            "operands": ["doc/OneShotTrigger/d"],
        }
        trigger_a = {
            "@type": "CompositeTrigger",
            "@id": "doc/CompositeTrigger/a",
            "mode": "or",
            "operands": ["doc/CompositeTrigger/b", "doc/CompositeTrigger/c"],
        }

        tdb = AsyncMock()
        tdb.get_document = AsyncMock(side_effect=[trigger_b, trigger_c, trigger_d, trigger_d])

        async def fake_get_occurrences(trig, ws, we, visited):
            if trig.get("@type") == "CompositeTrigger":
                return await ev._eval_or(
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

    @pytest.mark.parametrize(
        "plugin",
        [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin],
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
        for plugin in [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin]:
            assert any(r.name == "triggers" for r in plugin.requires)

    def test_duck_type_compatible_with_main_py(self):
        """Verify each plugin passes main.py's duck-type check filters."""
        for plugin in [oneshot_plugin, schedule_plugin, relative_plugin, composite_plugin]:
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
