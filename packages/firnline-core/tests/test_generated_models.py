"""Golden-JSON round-trip tests for generated TerminusDB kernel models.

Covers the kernel-only facade: InboxNote, OneShotTrigger, ScheduleTrigger,
TriggerFiring, Provenance, ExternalRef, and SchemaModule.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from firnline_core.generated.core import ExternalRef, Provenance, SchemaModule
from firnline_core.generated.inbox import (
    InboxNote,
    InboxNoteStatus,
)
from firnline_core.generated.triggers import (
    FiringStatus,
    OneShotTrigger,
    ScheduleTrigger,
    TriggerFiring,
)
from firnline_core.base import _format_datetime


# ---- helpers -----------------------------------------------------------

UTC = timezone.utc
CEST = timezone(timedelta(hours=2))


# ========================================================================
# InboxNote round-trip (with Entity fields)
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
        "contexts": [],
        "external_refs": [],
    }
    note = InboxNote.model_validate(data)

    assert note.id_ == "InboxNote/abc123"
    assert note.type_ == "InboxNote"
    assert note.content == "Hello world"
    assert note.status == InboxNoteStatus.NEW
    assert note.created_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert note.updated_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert note.contexts == []
    assert note.external_refs == []
    assert note.provenance is None

    expected = {
        "@id": "InboxNote/abc123",
        "@type": "InboxNote",
        "content": "Hello world",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "contexts": [],
        "external_refs": [],
    }
    assert note.to_tdb() == expected


def test_inboxnote_with_external_refs():
    """InboxNote carries embedded ExternalRef subdocuments."""
    _ref = ExternalRef(system="github", external_id="issue/42")
    data = {
        "@id": "InboxNote/xyz",
        "@type": "InboxNote",
        "content": "check PR",
        "status": "new",
        "created_at": "2026-07-06T08:00:00Z",
        "updated_at": "2026-07-06T08:00:00Z",
        "contexts": ["projects/thing"],
        "external_refs": [
            {"@type": "ExternalRef", "system": "github", "external_id": "issue/42"},
        ],
    }
    note = InboxNote.model_validate(data)
    assert note.contexts == ["projects/thing"]
    assert len(note.external_refs) == 1
    assert note.external_refs[0].system == "github"
    assert note.external_refs[0].external_id == "issue/42"

    result = note.to_tdb()
    assert "contexts" in result
    assert "external_refs" in result


# ========================================================================
# Provenance round-trip
# ========================================================================


def test_provenance_serialisation():
    """Provenance subdocument round-trips correctly."""
    data = {
        "@id": "Provenance/abc",
        "@type": "Provenance",
        "agent": "capture-agent",
        "at": "2026-07-06T08:00:00Z",
        "method": "auto",
        "confidence": 0.95,
        "source": "InboxNote/xyz",
    }
    prov = Provenance.model_validate(data)
    assert prov.agent == "capture-agent"
    assert prov.at == datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
    assert prov.method == "auto"
    assert prov.confidence == 0.95
    assert prov.source == "InboxNote/xyz"

    expected = {
        "@id": "Provenance/abc",
        "@type": "Provenance",
        "agent": "capture-agent",
        "at": "2026-07-06T08:00:00Z",
        "method": "auto",
        "confidence": 0.95,
        "source": "InboxNote/xyz",
    }
    assert prov.to_tdb() == expected


def test_provenance_minimal():
    """Provenance with only required fields + None optionals."""
    prov = Provenance(
        agent="test-agent",
        at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
    )
    result = prov.to_tdb()
    assert result == {
        "@type": "Provenance",
        "agent": "test-agent",
        "at": "2026-07-06T08:00:00Z",
    }
    for key in ("method", "confidence", "source"):
        assert key not in result, f"{key!r} must be absent"


# ========================================================================
# ExternalRef
# ========================================================================


def test_external_ref_round_trip():
    """ExternalRef ValueHash-keyed subdocument serialises."""
    ref = ExternalRef(
        system="jira",
        external_id="PROJ-123",
        url="https://jira.example.com/PROJ-123",
        last_synced_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
    )
    result = ref.to_tdb()
    assert result["system"] == "jira"
    assert result["external_id"] == "PROJ-123"
    assert result["url"] == "https://jira.example.com/PROJ-123"
    assert result["last_synced_at"] == "2026-07-06T08:00:00Z"


def test_external_ref_minimal():
    """ExternalRef with only required fields."""
    ref = ExternalRef(system="git", external_id="abcdef")
    result = ref.to_tdb()
    assert result == {
        "@type": "ExternalRef",
        "system": "git",
        "external_id": "abcdef",
    }


# ========================================================================
# SchemaModule round-trip
# ========================================================================


def test_schema_module_round_trip():
    """SchemaModule is a concrete registry class."""
    data = {
        "@id": "SchemaModule/core",
        "@type": "SchemaModule",
        "name": "core",
        "version": "0.1.0",
        "checksum": "abc123",
        "installed_at": "2026-07-06T08:00:00Z",
        "origin": "repo:core",
        "description": "Core markers and base",
    }
    sm = SchemaModule.model_validate(data)
    assert sm.name == "core"
    assert sm.version == "0.1.0"
    assert sm.checksum == "abc123"
    assert sm.installed_at == datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
    assert sm.origin == "repo:core"
    assert sm.description == "Core markers and base"

    result = sm.to_tdb()
    assert result["name"] == "core"


# ========================================================================
# Entity default factories
# ========================================================================


def test_entity_defaults_on_construction():
    """New Entity inheritors get empty contexts/external_refs by default."""
    note = InboxNote(
        content="hi",
        status=InboxNoteStatus.NEW,
        created_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
    )
    assert note.contexts == []
    assert note.external_refs == []
    assert note.provenance is None


# ========================================================================
# Datetime serialiser
# ========================================================================

def test_datetime_non_utc_converts_to_z():
    """Aware datetime in CEST (UTC+2) -> UTC with Z suffix."""
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
# Microseconds stripped in serialisation
# ========================================================================


def test_datetime_with_microseconds_serializes_without_them():
    """Datetime with non-zero microseconds -> output has no fractional seconds."""
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
# Wrong @type -> ValidationError
# ========================================================================


def test_inboxnote_wrong_at_type_raises_validation_error():
    """Parsing a payload with @type mismatch raises ValidationError."""
    data = {
        "@type": "TriggerFiring",
        "content": "hello",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    with pytest.raises(ValidationError):
        InboxNote.model_validate(data)


# ========================================================================
# Forward-compat: unknown extra fields do NOT raise
# ========================================================================


def test_extra_fields_ignored():
    """Parsing a server response with unknown keys is ok (ignore extra)."""
    data = {
        "@id": "InboxNote/abc",
        "@type": "InboxNote",
        "content": "test",
        "status": "new",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "unknown_field": "should-be-ignored",
    }
    note = InboxNote.model_validate(data)
    assert note.content == "test"
    result = note.to_tdb()
    assert "unknown_field" not in result


# ========================================================================
# OneShotTrigger round-trip (with nag fields)
# ========================================================================


def test_oneshot_trigger_round_trip():
    """OneShotTrigger inherits Trigger fields and has fire_at."""
    data = {
        "@id": "OneShotTrigger/fire1",
        "@type": "OneShotTrigger",
        "name": "one-shot-sale",
        "enabled": True,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "fire_at": "2026-07-06T09:00:00Z",
        "renotify_every": "PT30M",
        "max_renotifications": 3,
    }
    t = OneShotTrigger.model_validate(data)

    assert t.id_ == "OneShotTrigger/fire1"
    assert t.type_ == "OneShotTrigger"
    assert t.name == "one-shot-sale"
    assert t.enabled is True
    assert t.fire_at == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
    assert t.renotify_every == "PT30M"
    assert t.max_renotifications == 3

    expected = {
        "@id": "OneShotTrigger/fire1",
        "@type": "OneShotTrigger",
        "name": "one-shot-sale",
        "enabled": True,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "fire_at": "2026-07-06T09:00:00Z",
        "renotify_every": "PT30M",
        "max_renotifications": 3,
        "contexts": [],
        "external_refs": [],
    }
    assert t.to_tdb() == expected


def test_oneshot_trigger_excludes_none_optionals():
    """Optional inherited fields that are None are omitted."""
    t = OneShotTrigger(
        name="boom",
        enabled=True,
        fire_at=datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
    )
    result = t.to_tdb()
    # Entity defaults are present (empty list)
    assert result["contexts"] == []
    assert result["external_refs"] == []
    assert "valid_from" not in result
    assert "valid_until" not in result
    assert "renotify_every" not in result
    assert "max_renotifications" not in result
    assert "expire_after" not in result
    assert "provenance" not in result


# ========================================================================
# ScheduleTrigger with optional timezone
# ========================================================================


def test_schedule_trigger_with_timezone():
    """ScheduleTrigger accepts and serialises the optional timezone field."""
    data = {
        "@id": "ScheduleTrigger/repeat1",
        "@type": "ScheduleTrigger",
        "name": "daily-standup",
        "enabled": True,
        "dtstart": "2026-07-06T09:00:00Z",
        "rrule": "FREQ=DAILY",
        "timezone": "Europe/Berlin",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
    }
    t = ScheduleTrigger.model_validate(data)

    assert t.type_ == "ScheduleTrigger"
    assert t.timezone == "Europe/Berlin"
    assert t.rrule == "FREQ=DAILY"

    result = t.to_tdb()
    assert result["timezone"] == "Europe/Berlin"


def test_schedule_trigger_without_timezone():
    """ScheduleTrigger works without the optional timezone field."""
    t = ScheduleTrigger(
        name="daily-standup",
        enabled=True,
        dtstart=datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC),
        rrule="FREQ=DAILY",
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
    )
    assert t.timezone is None

    result = t.to_tdb()
    assert "timezone" not in result


# ========================================================================
# TriggerFiring round-trip (with Entity fields)
# ========================================================================


def test_trigger_firing_round_trip_all_fields():
    """TriggerFiring with all optional fields set serialises correctly."""
    data = {
        "@id": "TriggerFiring/ScheduleTrigger%2Frepeat1/2026-07-06T09:00:00Z",
        "@type": "TriggerFiring",
        "trigger": "ScheduleTrigger/repeat1",
        "occurrence_key": "2026-07-06T09:00:00Z",
        "scheduled_for": "2026-07-06T09:00:00Z",
        "fired_at": "2026-07-06T09:00:01Z",
        "status": "notified",
        "subject": "Reminder/abc",
        "acknowledged_at": "2026-07-06T09:05:00Z",
        "snoozed_until": "2026-07-06T10:00:00Z",
        "last_notified_at": "2026-07-06T09:00:01Z",
        "notification_count": 1,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "contexts": [],
        "external_refs": [],
    }
    firing = TriggerFiring.model_validate(data)

    assert firing.id_ == "TriggerFiring/ScheduleTrigger%2Frepeat1/2026-07-06T09:00:00Z"
    assert firing.type_ == "TriggerFiring"
    assert firing.trigger == "ScheduleTrigger/repeat1"
    assert firing.occurrence_key == "2026-07-06T09:00:00Z"
    assert firing.scheduled_for == datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC)
    assert firing.fired_at == datetime(2026, 7, 6, 9, 0, 1, tzinfo=UTC)
    assert firing.status == FiringStatus.NOTIFIED
    assert firing.subject == "Reminder/abc"
    assert firing.acknowledged_at == datetime(2026, 7, 6, 9, 5, 0, tzinfo=UTC)
    assert firing.snoozed_until == datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
    assert firing.last_notified_at == datetime(2026, 7, 6, 9, 0, 1, tzinfo=UTC)
    assert firing.notification_count == 1
    assert firing.created_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert firing.updated_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    expected = {
        "@id": "TriggerFiring/ScheduleTrigger%2Frepeat1/2026-07-06T09:00:00Z",
        "@type": "TriggerFiring",
        "trigger": "ScheduleTrigger/repeat1",
        "occurrence_key": "2026-07-06T09:00:00Z",
        "scheduled_for": "2026-07-06T09:00:00Z",
        "fired_at": "2026-07-06T09:00:01Z",
        "status": "notified",
        "subject": "Reminder/abc",
        "acknowledged_at": "2026-07-06T09:05:00Z",
        "snoozed_until": "2026-07-06T10:00:00Z",
        "last_notified_at": "2026-07-06T09:00:01Z",
        "notification_count": 1,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "contexts": [],
        "external_refs": [],
    }
    assert firing.to_tdb() == expected


def test_trigger_firing_minimal_excludes_none():
    """TriggerFiring with optional fields unset excludes them from output."""
    firing = TriggerFiring(
        trigger="ScheduleTrigger/repeat1",
        occurrence_key="2026-07-06T09:00:00Z",
        scheduled_for=datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC),
        fired_at=datetime(2026, 7, 6, 9, 0, 1, tzinfo=UTC),
        status=FiringStatus.PENDING,
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
    )
    result = firing.to_tdb()

    assert result == {
        "@type": "TriggerFiring",
        "trigger": "ScheduleTrigger/repeat1",
        "occurrence_key": "2026-07-06T09:00:00Z",
        "scheduled_for": "2026-07-06T09:00:00Z",
        "fired_at": "2026-07-06T09:00:01Z",
        "status": "pending",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "contexts": [],
        "external_refs": [],
    }

    for key in ("subject", "acknowledged_at", "snoozed_until",
                "last_notified_at", "notification_count"):
        assert key not in result, f"{key!r} must be absent"


def test_trigger_firing_all_statuses():
    """All FiringStatus enum values can be used."""
    for value in ("pending", "notified", "acknowledged", "snoozed", "expired"):
        data = {
            "@type": "TriggerFiring",
            "trigger": "ScheduleTrigger/r1",
            "occurrence_key": "2026-07-06T09:00:00Z",
            "scheduled_for": "2026-07-06T09:00:00Z",
            "fired_at": "2026-07-06T09:00:01Z",
            "status": value,
            "created_at": "2026-07-05T14:00:00Z",
            "updated_at": "2026-07-05T14:00:00Z",
        }
        firing = TriggerFiring.model_validate(data)
        assert firing.status.value == value
        assert firing.to_tdb()["status"] == value
