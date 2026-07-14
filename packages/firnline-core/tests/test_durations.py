"""Tests for firnline_core.durations — parse_duration and parse_iso_datetime."""

from datetime import datetime, timedelta, timezone

import pytest

from firnline_core.durations import parse_duration, parse_iso_datetime

UTC = timezone.utc


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------


class TestParseDuration:
    """Happy-path and malformed duration parsing."""

    def test_days_only(self):
        assert parse_duration("P1D") == timedelta(days=1)

    def test_hours_minutes(self):
        assert parse_duration("PT2H30M") == timedelta(hours=2, minutes=30)

    def test_full(self):
        assert parse_duration("P1DT2H30M15S") == timedelta(days=1, hours=2, minutes=30, seconds=15)

    def test_negative(self):
        assert parse_duration("-PT15M") == timedelta(minutes=-15)

    def test_negative_with_days(self):
        assert parse_duration("-P1DT1H") == timedelta(days=-1, hours=-1)

    def test_pt_only(self):
        assert parse_duration("PT1H") == timedelta(hours=1)

    def test_simple_hours(self):
        td = parse_duration("PT1H")
        assert td == timedelta(hours=1)

    def test_minutes(self):
        td = parse_duration("PT30M")
        assert td == timedelta(minutes=30)

    def test_complex(self):
        td = parse_duration("P1DT2H30M10S")
        assert td == timedelta(days=1, hours=2, minutes=30, seconds=10)

    def test_days(self):
        td = parse_duration("P7D")
        assert td == timedelta(days=7)

    def test_seconds_only(self):
        td = parse_duration("PT45S")
        assert td == timedelta(seconds=45)

    def test_bare_p_is_none(self):
        assert parse_duration("P") is None

    def test_invalid_is_none(self):
        assert parse_duration("not-a-duration") is None

    @pytest.mark.parametrize("bad", ["garbage", "P", "T1H", "P1DT", "1D", "P1H", "", "P1M", "P2Y"])
    def test_malformed_returns_none(self, bad):
        assert parse_duration(bad) is None


# ---------------------------------------------------------------------------
# parse_iso_datetime
# ---------------------------------------------------------------------------


class TestParseIsoDatetime:
    def test_z_suffix(self):
        assert parse_iso_datetime("2026-07-06T09:00:00Z") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_offset(self):
        assert parse_iso_datetime("2026-07-06T11:00:00+02:00") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_naive_treated_as_utc(self):
        assert parse_iso_datetime("2026-07-06T09:00:00") == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)

    def test_subsecond(self):
        result = parse_iso_datetime("2026-07-06T09:00:00.500Z")
        assert result == datetime(2026, 7, 6, 9, 0, 0, 500000, tzinfo=UTC)
