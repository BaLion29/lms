"""Golden-JSON round-trip tests for generated TerminusDB kernel models.

Covers the kernel-only facade: Captured, Tag, OneShotTrigger, ScheduleTrigger,
TriggerFiring, WebhookAction, ActionExecution, Provenance, ExternalRef,
and SchemaModule.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from firnline_core.generated.actions import (
    ActionExecution,
    ActionMode,
    ExecutionStatus,
    WebhookAction,
)
from firnline_core.generated.core import ExternalRef, Provenance, SchemaModule, Tag
from firnline_core.generated.capture import Captured, CapturedStatus
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
# Captured round-trip (with Entity fields)
# ========================================================================


def test_captured_round_trip():
    """Parse a server-shaped response, assert fields, then re-serialise."""
    data = {
        "@id": "Captured/abc123",
        "@type": "Captured",
        "content": "Hello world",
        "content_type": "text/plain",
        "status": "new",
        "captured_at": "2026-07-05T14:00:00Z",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:ingestd",
            "at": "2026-07-05T14:00:00Z",
        },
        "contexts": [],
        "external_refs": [],
        "derived_from": [],
    }
    cap = Captured.model_validate(data)

    assert cap.id_ == "Captured/abc123"
    assert cap.type_ == "Captured"
    assert cap.content == "Hello world"
    assert cap.content_type == "text/plain"
    assert cap.status == CapturedStatus.NEW
    assert cap.captured_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert cap.created_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert cap.updated_at == datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    assert cap.contexts == []
    assert cap.external_refs == []
    assert cap.derived_from == []
    assert cap.provenance.agent == "service:ingestd"

    result = cap.to_tdb()
    assert result["@id"] == "Captured/abc123"
    assert result["@type"] == "Captured"
    assert result["content"] == "Hello world"
    assert result["status"] == "new"


def test_captured_label_field_classvar():
    """Captured has label_field ClassVar set to 'content'."""
    assert Captured.label_field == "content"


def test_captured_with_external_refs():
    """Captured carries embedded ExternalRef subdocuments."""
    data = {
        "@id": "Captured/xyz",
        "@type": "Captured",
        "content": "check PR",
        "content_type": "text/plain",
        "status": "new",
        "captured_at": "2026-07-06T08:00:00Z",
        "created_at": "2026-07-06T08:00:00Z",
        "updated_at": "2026-07-06T08:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:ingestd",
            "at": "2026-07-06T08:00:00Z",
        },
        "contexts": ["projects/thing"],
        "external_refs": [
            {"@type": "ExternalRef", "system": "github", "external_id": "issue/42"},
        ],
        "derived_from": [],
    }
    cap = Captured.model_validate(data)
    assert cap.contexts == ["projects/thing"]
    assert len(cap.external_refs) == 1
    assert cap.external_refs[0].system == "github"
    assert cap.external_refs[0].external_id == "issue/42"

    result = cap.to_tdb()
    assert "contexts" in result
    assert "external_refs" in result


# ========================================================================
# Tag round-trip
# ========================================================================


def test_tag_round_trip():
    """Tag model round-trips with required provenance and derived_from."""
    data = {
        "@id": "Tag/learning",
        "@type": "Tag",
        "name": "learning",
        "created_at": "2026-07-06T08:00:00Z",
        "updated_at": "2026-07-06T08:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "user:basti",
            "at": "2026-07-06T08:00:00Z",
        },
        "contexts": [],
        "external_refs": [],
        "derived_from": [],
    }
    tag = Tag.model_validate(data)
    assert tag.name == "learning"
    assert tag.type_ == "Tag"
    assert tag.label_field == "name"
    assert tag.provenance.agent == "user:basti"

    result = tag.to_tdb()
    assert result["name"] == "learning"


# ========================================================================
# Provenance round-trip (no source field anymore)
# ========================================================================


def test_provenance_serialisation():
    """Provenance subdocument round-trips correctly (no source field)."""
    data = {
        "@id": "Provenance/abc",
        "@type": "Provenance",
        "agent": "service:capture-agent",
        "at": "2026-07-06T08:00:00Z",
        "method": "auto",
        "confidence": 0.95,
    }
    prov = Provenance.model_validate(data)
    assert prov.agent == "service:capture-agent"
    assert prov.at == datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC)
    assert prov.method == "auto"
    assert prov.confidence == 0.95

    # source must not exist
    assert "source" not in Provenance.model_fields

    expected = {
        "@id": "Provenance/abc",
        "@type": "Provenance",
        "agent": "service:capture-agent",
        "at": "2026-07-06T08:00:00Z",
        "method": "auto",
        "confidence": 0.95,
    }
    assert prov.to_tdb() == expected


def test_provenance_minimal():
    """Provenance with only required fields + None optionals."""
    prov = Provenance(
        agent="service:test-agent",
        at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
    )
    result = prov.to_tdb()
    assert result == {
        "@type": "Provenance",
        "agent": "service:test-agent",
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
# Entity default factories (derived_from, contexts, external_refs on
# Entity inheritors)
# ========================================================================


def test_entity_defaults_on_construction():
    """New Entity inheritors get empty lists for collection fields."""
    cap = Captured(
        content="hi",
        content_type="text/plain",
        status=CapturedStatus.NEW,
        captured_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        ),
    )
    assert cap.contexts == []
    assert cap.external_refs == []
    assert cap.derived_from == []


# ========================================================================
# Entity has archived_at
# ========================================================================


def test_entity_has_archived_at():
    """Entity inheritors have archived_at field (default None)."""
    cap = Captured(
        content="test",
        content_type="text/plain",
        status=CapturedStatus.NEW,
        captured_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 6, 8, 0, 0, tzinfo=UTC),
        ),
    )
    assert cap.archived_at is None
    assert "archived_at" in Captured.model_fields


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
    cap = Captured(
        content="test",
        content_type="text/plain",
        status=CapturedStatus.NEW,
        captured_at=dt,
        created_at=dt,
        updated_at=dt,
        provenance=Provenance(
            agent="service:test",
            at=dt,
        ),
    )
    result = cap.to_tdb()
    assert result["created_at"] == "2026-07-05T14:00:00Z"
    assert result["updated_at"] == "2026-07-05T14:00:00Z"


# ========================================================================
# Microseconds stripped in serialisation
# ========================================================================


def test_datetime_with_microseconds_serializes_without_them():
    """Datetime with non-zero microseconds -> output has no fractional seconds."""
    dt = datetime(2026, 7, 5, 14, 0, 0, 123456, tzinfo=UTC)
    cap = Captured(
        content="micros",
        content_type="text/plain",
        status=CapturedStatus.NEW,
        captured_at=dt,
        created_at=dt,
        updated_at=dt,
        provenance=Provenance(
            agent="service:test",
            at=dt,
        ),
    )
    result = cap.to_tdb()
    assert result["created_at"] == "2026-07-05T14:00:00Z"
    assert result["updated_at"] == "2026-07-05T14:00:00Z"


# ========================================================================
# Wrong @type -> ValidationError
# ========================================================================


def test_captured_wrong_at_type_raises_validation_error():
    """Parsing a payload with @type mismatch raises ValidationError."""
    data = {
        "@type": "TriggerFiring",
        "content": "hello",
        "content_type": "text/plain",
        "status": "new",
        "captured_at": "2026-07-05T14:00:00Z",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:test",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
    }
    with pytest.raises(ValidationError):
        Captured.model_validate(data)


# ========================================================================
# Forward-compat: unknown extra fields do NOT raise
# ========================================================================


def test_extra_fields_preserved():
    """Unknown extra fields survive a round-trip through Pydantic (extra='allow')."""
    data = {
        "@id": "Captured/abc",
        "@type": "Captured",
        "content": "test",
        "content_type": "text/plain",
        "status": "new",
        "captured_at": "2026-07-05T14:00:00Z",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:test",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
        "unknown_field": "should-be-preserved",
    }
    cap = Captured.model_validate(data)
    assert cap.content == "test"
    result = cap.to_tdb()
    assert result["unknown_field"] == "should-be-preserved"


# ========================================================================
# OneShotTrigger round-trip (with nag fields + required provenance)
# ========================================================================


def test_oneshot_trigger_round_trip():
    """OneShotTrigger inherits Trigger/Entity fields and has fire_at."""
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
        "provenance": {
            "@type": "Provenance",
            "agent": "service:scheduler",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
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
        "derived_from": [],
        "provenance": {
            "@type": "Provenance",
            "agent": "service:scheduler",
            "at": "2026-07-05T14:00:00Z",
        },
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
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        ),
    )
    result = t.to_tdb()
    # Entity defaults are present (empty list)
    assert result["contexts"] == []
    assert result["external_refs"] == []
    assert result["derived_from"] == []
    assert result["provenance"]["agent"] == "service:test"
    assert "valid_from" not in result
    assert "valid_until" not in result
    assert "renotify_every" not in result
    assert "max_renotifications" not in result
    assert "expire_after" not in result


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
        "provenance": {
            "@type": "Provenance",
            "agent": "service:scheduler",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
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
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        ),
    )
    assert t.timezone is None

    result = t.to_tdb()
    assert "timezone" not in result


# ========================================================================
# TriggerFiring round-trip (with Entity fields + required provenance)
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
        "provenance": {
            "@type": "Provenance",
            "agent": "service:scheduler",
            "at": "2026-07-05T14:00:00Z",
        },
        "contexts": [],
        "external_refs": [],
        "derived_from": [],
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
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        ),
    )
    result = firing.to_tdb()

    assert result["trigger"] == "ScheduleTrigger/repeat1"
    assert result["status"] == "pending"
    assert result["contexts"] == []
    assert result["external_refs"] == []
    assert result["derived_from"] == []
    assert result["provenance"]["agent"] == "service:test"

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
            "provenance": {
                "@type": "Provenance",
                "agent": "service:test",
                "at": "2026-07-05T14:00:00Z",
            },
            "derived_from": [],
        }
        firing = TriggerFiring.model_validate(data)
        assert firing.status.value == value
        assert firing.to_tdb()["status"] == value


# ========================================================================
# WebhookAction round-trip
# ========================================================================


def test_webhook_action_round_trip():
    """WebhookAction round-trips with all optional fields set."""
    data = {
        "@id": "WebhookAction/alert",
        "@type": "WebhookAction",
        "name": "alert-webhook",
        "enabled": True,
        "trigger": "ScheduleTrigger/repeat1",
        "executor": "webhook",
        "mode": "approval",
        "url": "https://hooks.example.com/alert",
        "http_method": "POST",
        "payload_template": '{"text": "$name"}',
        "timeout": "PT30S",
        "max_attempts": 3,
        "retry_backoff": "PT10S",
        "params": '{"headers": {"X-Token": "{{TOKEN}}"}}',
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "user:basti",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
    }
    wa = WebhookAction.model_validate(data)

    assert wa.id_ == "WebhookAction/alert"
    assert wa.type_ == "WebhookAction"
    assert wa.name == "alert-webhook"
    assert wa.enabled is True
    assert wa.trigger == "ScheduleTrigger/repeat1"
    assert wa.executor == "webhook"
    assert wa.mode == ActionMode.APPROVAL
    assert wa.url == "https://hooks.example.com/alert"
    assert wa.http_method == "POST"
    assert wa.payload_template == '{"text": "$name"}'
    assert wa.timeout == "PT30S"
    assert wa.max_attempts == 3
    assert wa.retry_backoff == "PT10S"
    assert wa.params == '{"headers": {"X-Token": "{{TOKEN}}"}}'

    result = wa.to_tdb()
    assert result["@id"] == "WebhookAction/alert"
    assert result["@type"] == "WebhookAction"
    assert result["mode"] == "approval"
    assert result["url"] == "https://hooks.example.com/alert"


def test_webhook_action_minimal():
    """WebhookAction with only required fields omits None optionals."""
    wa = WebhookAction(
        name="minimal-webhook",
        enabled=True,
        trigger="ScheduleTrigger/r1",
        executor="webhook",
        mode=ActionMode.AUTO,
        url="https://example.com/hook",
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        provenance=Provenance(
            agent="service:test",
            at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        ),
    )
    result = wa.to_tdb()
    assert result["contexts"] == []
    assert result["external_refs"] == []
    assert result["derived_from"] == []
    assert result["provenance"]["agent"] == "service:test"
    for key in ("http_method", "payload_template", "timeout",
                "max_attempts", "retry_backoff", "params"):
        assert key not in result, f"{key!r} must be absent"


# ========================================================================
# ActionExecution round-trip
# ========================================================================


def test_action_execution_round_trip():
    """ActionExecution round-trips with all optional fields set."""
    data = {
        "@id": "ActionExecution/WebhookAction%2Falert/TriggerFiring%2FScheduleTrigger%252Frepeat1%2F2026-07-06T09%3A00%3A00Z",
        "@type": "ActionExecution",
        "action": "WebhookAction/alert",
        "firing": "TriggerFiring/ScheduleTrigger%252Frepeat1/2026-07-06T09:00:00Z",
        "status": "succeeded",
        "idempotency_key": "WebhookAction/alert#ScheduleTrigger/repeat1/2026-07-06T09:00:00Z",
        "attempt": 1,
        "executed_at": "2026-07-06T09:00:02Z",
        "next_attempt_at": "2026-07-06T09:01:00Z",
        "result_detail": "HTTP 200 OK",
        "external_ref": "github:deploy/42",
        "approved_at": "2026-07-06T08:55:00Z",
        "approved_by": "user:alice",
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:effectd",
            "at": "2026-07-06T09:00:02Z",
        },
        "derived_from": [],
    }
    ae = ActionExecution.model_validate(data)

    assert ae.type_ == "ActionExecution"
    assert ae.action == "WebhookAction/alert"
    assert ae.firing == "TriggerFiring/ScheduleTrigger%252Frepeat1/2026-07-06T09:00:00Z"
    assert ae.status == ExecutionStatus.SUCCEEDED
    assert ae.idempotency_key == "WebhookAction/alert#ScheduleTrigger/repeat1/2026-07-06T09:00:00Z"
    assert ae.attempt == 1
    assert ae.executed_at == datetime(2026, 7, 6, 9, 0, 2, tzinfo=UTC)
    assert ae.next_attempt_at == datetime(2026, 7, 6, 9, 1, 0, tzinfo=UTC)
    assert ae.result_detail == "HTTP 200 OK"
    assert ae.external_ref == "github:deploy/42"
    assert ae.approved_at == datetime(2026, 7, 6, 8, 55, 0, tzinfo=UTC)
    assert ae.approved_by == "user:alice"

    result = ae.to_tdb()
    assert result["@type"] == "ActionExecution"
    assert result["status"] == "succeeded"
    assert result["idempotency_key"] == "WebhookAction/alert#ScheduleTrigger/repeat1/2026-07-06T09:00:00Z"


def test_action_execution_minimal():
    """ActionExecution with optional fields unset excludes them from output."""
    ae = ActionExecution(
        action="WebhookAction/alert",
        firing="TriggerFiring/ScheduleTrigger%252Frepeat1/2026-07-06T09:00:00Z",
        status=ExecutionStatus.PENDING_APPROVAL,
        idempotency_key="WebhookAction/alert#ScheduleTrigger/repeat1/2026-07-06T09:00:00Z",
        attempt=0,
        created_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        provenance=Provenance(
            agent="service:effectd",
            at=datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC),
        ),
    )
    result = ae.to_tdb()
    assert result["status"] == "pending_approval"
    assert result["attempt"] == 0
    assert result["contexts"] == []
    assert result["external_refs"] == []
    assert result["derived_from"] == []
    assert result["provenance"]["agent"] == "service:effectd"
    for key in ("executed_at", "next_attempt_at", "result_detail",
                "external_ref", "approved_at", "approved_by"):
        assert key not in result, f"{key!r} must be absent"


def test_action_execution_all_statuses():
    """All ExecutionStatus enum values can be used."""
    for value in ("pending_approval", "pending", "succeeded", "failed", "dead", "skipped"):
        data = {
            "@type": "ActionExecution",
            "action": "WebhookAction/alert",
            "firing": "TriggerFiring/ScheduleTrigger%252Frepeat1/2026-07-06T09:00:00Z",
            "status": value,
            "idempotency_key": "WebhookAction/alert#ScheduleTrigger/repeat1/2026-07-06T09:00:00Z",
            "attempt": 0,
            "created_at": "2026-07-05T14:00:00Z",
            "updated_at": "2026-07-05T14:00:00Z",
            "provenance": {
                "@type": "Provenance",
                "agent": "service:test",
                "at": "2026-07-05T14:00:00Z",
            },
            "derived_from": [],
        }
        ae = ActionExecution.model_validate(data)
        assert ae.status.value == value
        assert ae.to_tdb()["status"] == value


def test_action_execution_transitions_classvar():
    """ActionExecution has transitions ClassVar set."""
    assert ActionExecution.transitions == {
        "pending_approval": ["pending"],
        "pending": ["succeeded", "failed", "dead"],
        "succeeded": [],
        "failed": [],
        "dead": [],
        "skipped": [],
    }


def test_action_execution_label_field_classvar():
    """ActionExecution has label_field ClassVar set to 'idempotency_key'."""
    assert ActionExecution.label_field == "idempotency_key"


def test_webhook_action_label_field_classvar():
    """WebhookAction has label_field ClassVar set to 'name'."""
    assert WebhookAction.label_field == "name"


def test_action_execution_extra_fields_preserved():
    """Unknown extra fields survive round-trip (extra='allow')."""
    data = {
        "@id": "ActionExecution/ae1",
        "@type": "ActionExecution",
        "action": "WebhookAction/alert",
        "firing": "TriggerFiring/f1",
        "status": "pending",
        "idempotency_key": "WebhookAction/alert#f1",
        "attempt": 0,
        "created_at": "2026-07-05T14:00:00Z",
        "updated_at": "2026-07-05T14:00:00Z",
        "provenance": {
            "@type": "Provenance",
            "agent": "service:test",
            "at": "2026-07-05T14:00:00Z",
        },
        "derived_from": [],
        "custom_field": "forward-compat",
    }
    ae = ActionExecution.model_validate(data)
    result = ae.to_tdb()
    assert result["custom_field"] == "forward-compat"
