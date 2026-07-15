"""Unit tests for firnline_webui.calendar_introspect helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from firnline_webui.calendar_introspect import (
    calendarable_classes,
    datetime_fields,
    events_in_range,
    parse_events,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def event_class_def() -> dict:
    """Class with start_datetime and end_datetime fields (dict form)."""
    return {
        "@id": "Event",
        "@type": "Class",
        "name": "xsd:string",
        "start_datetime": {"@class": "xsd:dateTime", "@type": "Optional"},
        "end_datetime": {"@class": "xsd:dateTime", "@type": "Optional"},
        "location": "xsd:string",
    }


@pytest.fixture
def task_class_def() -> dict:
    """Class with due_date (plain string form)."""
    return {
        "@id": "Task",
        "@type": "Class",
        "name": "xsd:string",
        "due_date": "xsd:dateTime",
        "status": "xsd:string",
    }


@pytest.fixture
def scheduled_activity_class_def() -> dict:
    """Class with start/end datetime fields."""
    return {
        "@id": "ScheduledActivity",
        "@type": "Class",
        "start_datetime": "xsd:dateTime",
        "end_datetime": "xsd:dateTime",
        "title": "xsd:string",
    }


@pytest.fixture
def abstract_class_def() -> dict:
    return {
        "@id": "AbstractBase",
        "@type": "Class",
        "@abstract": True,
    }


@pytest.fixture
def subdocument_class_def() -> dict:
    return {
        "@id": "Address",
        "@type": "Class",
        "@subdocument": True,
        "valid_from": "xsd:dateTime",
    }


@pytest.fixture
def no_datetime_class_def() -> dict:
    return {
        "@id": "Tag",
        "@type": "Class",
        "name": "xsd:string",
        "color": "xsd:string",
    }


@pytest.fixture
def schema_with_variety(
    event_class_def,
    task_class_def,
    scheduled_activity_class_def,
    abstract_class_def,
    subdocument_class_def,
    no_datetime_class_def,
) -> list[dict]:
    return [
        event_class_def,
        task_class_def,
        scheduled_activity_class_def,
        abstract_class_def,
        subdocument_class_def,
        no_datetime_class_def,
    ]


@pytest.fixture
def event_docs() -> list[dict]:
    return [
        {
            "@id": "Event/1",
            "@type": "Event",
            "name": "Team Standup",
            "start_datetime": "2026-07-07T09:00:00Z",
            "end_datetime": "2026-07-07T09:30:00Z",
        },
        {
            "@id": "Event/2",
            "@type": "Event",
            "name": "Lunch",
            "start_datetime": "2026-07-07T12:00:00+02:00",
            "end_datetime": "2026-07-07T13:00:00+02:00",
        },
    ]


@pytest.fixture
def task_docs() -> list[dict]:
    return [
        {
            "@id": "Task/1",
            "@type": "Task",
            "name": "File taxes",
            "due_date": "2026-07-15T23:59:59Z",
        },
        {
            "@id": "Task/2",
            "@type": "Task",
            "name": "No due date task",
        },
    ]


# ── datetime_fields ─────────────────────────────────────────────────────


def test_datetime_fields_plain_string(task_class_def):
    result = datetime_fields(task_class_def)
    assert result == ["due_date"]


def test_datetime_fields_dict_form(event_class_def):
    result = datetime_fields(event_class_def)
    assert "start_datetime" in result
    assert "end_datetime" in result
    assert len(result) == 2


def test_datetime_fields_mixed():
    class_def = {
        "@id": "Mixed",
        "@type": "Class",
        "a": "xsd:dateTime",
        "b": {"@class": "xsd:dateTime", "@type": "Optional"},
        "c": "xsd:string",
    }
    result = datetime_fields(class_def)
    assert set(result) == {"a", "b"}


def test_datetime_fields_none():
    assert datetime_fields({"@id": "Foo", "@type": "Class"}) == []


def test_datetime_fields_ignores_at_keys():
    class_def = {
        "@id": "Foo",
        "@type": "Class",
        "@class": "xsd:dateTime",  # should be skipped
        "real": "xsd:dateTime",
    }
    assert datetime_fields(class_def) == ["real"]


# ── calendarable_classes ────────────────────────────────────────────────


def test_calendarable_classes_event_role_inference(event_class_def):
    result = calendarable_classes([event_class_def])
    assert len(result) == 1
    spec = result[0]
    assert spec["class_id"] == "Event"
    assert spec["start_field"] == "start_datetime"
    assert spec["end_field"] == "end_datetime"
    assert spec["instant_field"] is None
    assert spec["title_field"] == "name"


def test_calendarable_classes_task_instant_role(task_class_def):
    result = calendarable_classes([task_class_def])
    assert len(result) == 1
    spec = result[0]
    assert spec["start_field"] is None
    assert spec["end_field"] is None
    assert spec["instant_field"] == "due_date"


def test_calendarable_classes_title_fallback():
    class_def = {
        "@id": "Note",
        "@type": "Class",
        "text": "xsd:string",
        "due_date": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    assert result[0]["title_field"] == "@id"


def test_calendarable_classes_title_prefers_name_over_title():
    class_def = {
        "@id": "Item",
        "@type": "Class",
        "name": "xsd:string",
        "title": "xsd:string",
        "due_date": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    assert result[0]["title_field"] == "name"


def test_calendarable_classes_title_uses_title():
    class_def = {
        "@id": "Item",
        "@type": "Class",
        "title": "xsd:string",
        "due_date": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    assert result[0]["title_field"] == "title"


def test_calendarable_classes_excludes_abstract(abstract_class_def):
    assert calendarable_classes([abstract_class_def]) == []


def test_calendarable_classes_excludes_subdocument(subdocument_class_def):
    assert calendarable_classes([subdocument_class_def]) == []


def test_calendarable_classes_excludes_no_datetime(no_datetime_class_def):
    assert calendarable_classes([no_datetime_class_def]) == []


def test_calendarable_classes_excludes_non_class():
    schema = [
        {"@id": "Foo", "@type": "Enum", "@value": ["a"]},
    ]
    assert calendarable_classes(schema) == []


def test_calendarable_classes_variety(schema_with_variety):
    result = calendarable_classes(schema_with_variety)
    ids = {r["class_id"] for r in result}
    assert ids == {"Event", "Task", "ScheduledActivity"}


def test_calendarable_classes_no_double_assignment():
    """A field assigned to start must never also be assigned to end."""
    class_def = {
        "@id": "Meeting",
        "@type": "Class",
        "start_datetime": "xsd:dateTime",
        "end_datetime": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    spec = result[0]
    assert spec["start_field"] == "start_datetime"
    assert spec["end_field"] == "end_datetime"
    assert spec["start_field"] != spec["end_field"]


def test_calendarable_classes_single_field_becomes_instant():
    class_def = {
        "@id": "Reminder",
        "@type": "Class",
        "title": "xsd:string",
        "alert_at": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    assert result[0]["instant_field"] == "alert_at"
    assert result[0]["start_field"] is None


def test_calendarable_classes_start_keyword_inference():
    """Fields matching start keywords (case‑insensitive) become start_field."""
    class_def = {
        "@id": "Appointment",
        "@type": "Class",
        "name": "xsd:string",
        "starts_at": "xsd:dateTime",
        "ends_at": "xsd:dateTime",
    }
    result = calendarable_classes([class_def])
    assert result[0]["start_field"] == "starts_at"
    assert result[0]["end_field"] == "ends_at"


# ── parse_events ────────────────────────────────────────────────────────


def test_parse_events_start_and_end(event_docs, event_class_def):
    spec = calendarable_classes([event_class_def])[0]
    events = parse_events(event_docs, spec)
    assert len(events) == 2
    assert events[0]["id"] == "Event/1"
    assert events[0]["title"] == "Team Standup"
    assert events[0]["start"] == "2026-07-07T09:00:00Z"
    assert events[0]["end"] == "2026-07-07T09:30:00Z"
    assert events[0]["all_day"] is False


def test_parse_events_instant_only(task_docs, task_class_def):
    spec = calendarable_classes([task_class_def])[0]
    events = parse_events(task_docs, spec)
    assert len(events) == 1  # only the doc with due_date
    assert events[0]["start"] == "2026-07-15T23:59:59Z"
    assert events[0]["end"] == ""


def test_parse_events_missing_datetime_skipped(task_docs, task_class_def):
    spec = calendarable_classes([task_class_def])[0]
    events = parse_events(task_docs, spec)
    ids = {e["id"] for e in events}
    assert "Task/2" not in ids


def test_parse_events_z_suffix_normalised():
    spec = {
        "class_id": "Event",
        "start_field": "start",
        "end_field": None,
        "instant_field": None,
        "title_field": "name",
    }
    docs = [
        {
            "@id": "Ev/1",
            "name": "Test",
            "start": "2026-01-01T12:00:00Z",
        }
    ]
    events = parse_events(docs, spec)
    assert len(events) == 1
    assert events[0]["start"] == "2026-01-01T12:00:00Z"


def test_parse_events_unparsable_skipped():
    spec = {
        "class_id": "Event",
        "start_field": "start",
        "end_field": None,
        "instant_field": None,
        "title_field": "name",
    }
    docs = [
        {"@id": "Ev/1", "name": "Bad", "start": "not-a-date"},
        {"@id": "Ev/2", "name": "Good", "start": "2026-01-01T12:00:00Z"},
    ]
    events = parse_events(docs, spec)
    assert len(events) == 1
    assert events[0]["id"] == "Ev/2"


def test_parse_events_title_fallback_to_iri():
    spec = {
        "class_id": "Reminder",
        "start_field": None,
        "end_field": None,
        "instant_field": "alert_at",
        "title_field": "title",
    }
    docs = [
        {
            "@id": "terminusdb:///data/Reminder/abc123",
            "alert_at": "2026-07-01T08:00:00Z",
        }
    ]
    events = parse_events(docs, spec)
    assert len(events) == 1
    assert events[0]["title"] == "Reminder/abc123"


def test_parse_events_datetime_dict_value():
    """Datetime value nested in a dict is correctly extracted."""
    spec = {
        "class_id": "Event",
        "start_field": "when",
        "end_field": None,
        "instant_field": None,
        "title_field": "name",
    }
    docs = [
        {
            "@id": "Ev/1",
            "name": "Nested",
            "when": {"@value": "2026-07-07T10:00:00Z", "@type": "xsd:dateTime"},
        }
    ]
    events = parse_events(docs, spec)
    assert len(events) == 1
    assert events[0]["start"] == "2026-07-07T10:00:00Z"


# ── events_in_range ─────────────────────────────────────────────────────


def _make_event(start: str, end: str = "") -> dict:
    return {"id": "x", "class": "Test", "title": "t", "start": start, "end": end, "all_day": False}


def _dr(start: str, end: str) -> tuple[datetime, datetime]:
    return (
        datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        datetime.fromisoformat(end).replace(tzinfo=timezone.utc),
    )


def test_events_in_range_overlap():
    events = [
        _make_event("2026-07-07T08:00:00+00:00", "2026-07-07T10:00:00+00:00"),
    ]
    rng = _dr("2026-07-07T07:00:00+00:00", "2026-07-07T09:00:00+00:00")
    assert len(events_in_range(events, *rng)) == 1


def test_events_in_range_no_overlap():
    events = [
        _make_event("2026-07-07T08:00:00+00:00", "2026-07-07T09:00:00+00:00"),
    ]
    rng = _dr("2026-07-07T10:00:00+00:00", "2026-07-07T12:00:00+00:00")
    assert len(events_in_range(events, *rng)) == 0


def test_events_in_range_instant_in_range():
    events = [
        _make_event("2026-07-07T08:00:00+00:00", ""),
    ]
    rng = _dr("2026-07-07T07:00:00+00:00", "2026-07-07T09:00:00+00:00")
    assert len(events_in_range(events, *rng)) == 1


def test_events_in_range_instant_at_start_excluded():
    """Instant event exactly at range_start should be excluded (half‑open)."""
    events = [
        _make_event("2026-07-07T07:00:00+00:00", ""),
    ]
    rng = _dr("2026-07-07T07:00:00+00:00", "2026-07-07T09:00:00+00:00")
    assert len(events_in_range(events, *rng)) == 0


def test_events_in_range_naive_assumed_utc():
    """Naive event datetimes are treated as UTC."""
    events = [
        _make_event("2026-07-07T08:00:00", "2026-07-07T09:00:00"),
    ]
    rng = _dr("2026-07-07T08:30:00+00:00", "2026-07-07T10:00:00+00:00")
    assert len(events_in_range(events, *rng)) == 1


def test_events_in_range_mixed_timezone():
    """Event with +02:00 offset compared against UTC range."""
    events = [
        _make_event("2026-07-07T10:00:00+02:00", "2026-07-07T11:00:00+02:00"),  # 08:00–09:00 UTC
    ]
    rng = _dr("2026-07-07T07:00:00+00:00", "2026-07-07T08:30:00+00:00")
    assert len(events_in_range(events, *rng)) == 1


def test_events_in_range_empty_list():
    assert events_in_range([], *_dr("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")) == []


def test_events_in_range_unparsable_skipped():
    events = [
        {"id": "x", "class": "T", "title": "t", "start": "not-a-date", "end": "", "all_day": False},
        _make_event("2026-07-07T08:00:00+00:00", ""),
    ]
    rng = _dr("2026-07-07T00:00:00+00:00", "2026-07-08T00:00:00+00:00")
    result = events_in_range(events, *rng)
    assert len(result) == 1
    assert result[0]["start"] == "2026-07-07T08:00:00+00:00"
