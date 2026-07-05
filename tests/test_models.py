"""Golden-JSON round-trip tests for TerminusDB models."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ingestd.models import (
    Contact,
    Event,
    EventStatus,
    InboxNote,
    InboxNoteStatus,
    Location,
    Person,
    Task,
    TaskStatus,
    _format_datetime,
)


# ---- helpers -----------------------------------------------------------

UTC = timezone.utc
CEST = timezone(timedelta(hours=2))


# ========================================================================
# InboxNote round-trip
# ========================================================================


def test_inboxnote_round_trip():
    """Parse a server-shaped response, assert fields, then re-serialise."""
    data = {
        "@id": "InboxNote/abc123",
        "@type": "InboxNote",
        "content": "Hello world",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    note = InboxNote.model_validate(data)

    assert note.id_ == "InboxNote/abc123"
    assert note.type_ == "InboxNote"
    assert note.content == "Hello world"
    assert note.status == InboxNoteStatus.NEW
    assert note.created_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert note.updated_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    expected = {
        "@id": "InboxNote/abc123",
        "@type": "InboxNote",
        "content": "Hello world",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    assert note.to_tdb() == expected


# ========================================================================
# Task – minimal (all optional fields None)
# ========================================================================


def test_task_minimal_excludes_none():
    task = Task(
        name="Review PR",
        status=TaskStatus.OPEN,
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
    )
    result = task.to_tdb()

    # No @id when id_ is None
    assert "@id" not in result
    # None-valued optional fields are excluded
    for key in (
        "description",
        "due_date",
        "priority",
        "derived_from",
        "estimated_duration",
    ):
        assert key not in result, f"{key!r} must be absent"

    # required_context defaults to [] and IS present (empty list ≠ None)
    assert result["required_context"] == []

    # Golden dict
    assert result == {
        "@type": "Task",
        "name": "Review PR",
        "status": "open",
        "required_context": [],
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }


# ========================================================================
# Event – IRI references as plain strings
# ========================================================================


def test_event_with_iri_references():
    event = Event(
        name="Team sync",
        status=EventStatus.OPEN,
        derived_from="InboxNote/abc123",
        location="Location/xyz",
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
    )
    result = event.to_tdb()
    assert result["derived_from"] == "InboxNote/abc123"
    assert result["location"] == "Location/xyz"
    assert result["@type"] == "Event"


# ========================================================================
# Person with nested Contact
# ========================================================================


def test_person_with_contact():
    contact = Contact(email="alice@example.com", domicile="Location/123")
    person = Person(name="Alice", contact=contact)
    result = person.to_tdb()

    assert result == {
        "@type": "Person",
        "name": "Alice",
        "contact": {
            "@type": "Contact",
            "email": "alice@example.com",
            "domicile": "Location/123",
        },
    }

    # Contact itself can also serialise standalone
    assert contact.to_tdb() == {
        "@type": "Contact",
        "email": "alice@example.com",
        "domicile": "Location/123",
    }


def test_contact_with_id():
    """Server returns @id on GET; model must accept it."""
    data = {
        "@id": "Contact/abc",
        "@type": "Contact",
        "email": "bob@example.com",
    }
    c = Contact.model_validate(data)
    assert c.id_ == "Contact/abc"
    assert c.email == "bob@example.com"


# ========================================================================
# Datetime serialiser
# ========================================================================


def test_datetime_non_utc_converts_to_z():
    """Aware datetime in CEST (UTC+2) → UTC with Z suffix."""
    dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=CEST)
    assert _format_datetime(dt) == "2026-07-05T12:00:00Z"


def test_datetime_naive_treated_as_utc():
    """Naive datetime is assumed UTC."""
    dt = datetime(2026, 7, 5, 14, 0, 0)
    assert _format_datetime(dt) == "2026-07-05T14:00:00Z"


def test_datetime_on_model_field():
    """model_dump(mode='json') uses the PlainSerializer."""
    dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    note = InboxNote(
        content="test",
        status=InboxNoteStatus.NEW,
        created_at=dt,
        updated_at=dt,
    )
    result = note.to_tdb()
    assert result["created_at"] == "2026-07-05T14:00:00Z"
    assert result["updated_at"] == "2026-07-05T14:00:00Z"


# ========================================================================
# Forward-compat: unknown extra fields do NOT raise
# ========================================================================


def test_extra_fields_ignored():
    """Parsing a server response with unknown keys (e.g. coordinates) is ok."""
    data = {
        "@id": "Location/abc",
        "@type": "Location",
        "name": "Home",
        "address": "123 Main St",
        "aliases": ["home"],
        "coordinates": "48.8566,2.3522",  # xdd:coordinate, not in model
    }
    loc = Location.model_validate(data)
    assert loc.name == "Home"
    assert loc.address == "123 Main St"
    assert loc.aliases == ["home"]

    # coordinates must not leak into serialised output
    result = loc.to_tdb()
    assert "coordinates" not in result


# ========================================================================
# Microseconds stripped in serialisation
# ========================================================================


def test_datetime_with_microseconds_serializes_without_them():
    """Datetime with non-zero microseconds → output has no fractional seconds."""
    dt = datetime(2026, 7, 5, 14, 0, 0, 123456, tzinfo=UTC)
    note = InboxNote(
        content="micros",
        status=InboxNoteStatus.NEW,
        created_at=dt,
        updated_at=dt,
    )
    result = note.to_tdb()
    assert result["created_at"] == "2026-07-05T14:00:00Z"
    assert result["updated_at"] == "2026-07-05T14:00:00Z"


# ========================================================================
# Wrong @type → ValidationError
# ========================================================================


def test_inboxnote_wrong_at_type_raises_validation_error():
    """Parsing a payload with @type mismatch raises ValidationError."""
    data = {
        "@type": "Task",
        "content": "hello",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    with pytest.raises(ValidationError):
        InboxNote.model_validate(data)
