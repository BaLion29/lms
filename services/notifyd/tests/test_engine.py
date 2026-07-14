"""Tests for notifyd.engine — no network, AsyncMock TdbClient, fake channel objects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import structlog

from notifyd.engine import NotifyEngine
from firnline_core.plugins import DeliveryResult, ModuleRequirement

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(dt: datetime) -> str:
    """Return UTC ISO-8601 (TDB canonical form)."""
    return dt.astimezone(timezone.utc).isoformat()


def _frozen_now() -> datetime:
    return datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fake notification channel
# ---------------------------------------------------------------------------


class FakeChannel:
    """A channel with a controllable deliver result."""

    name = "fake"
    requires: list[ModuleRequirement] = []

    def __init__(self, *, ok: bool = True, detail: str = "", exception: Exception | None = None) -> None:
        self.ok = ok
        self.detail = detail
        self.exception = exception
        self.calls: list[dict] = []

    async def deliver(self, firing, subject, ctx):
        self.calls.append({"firing": firing, "subject": subject, "ctx": ctx})
        if self.exception:
            raise self.exception
        return DeliveryResult(ok=self.ok, detail=self.detail)


# ---------------------------------------------------------------------------
# Fake repository
# ---------------------------------------------------------------------------


class FakeRepo:
    """A minimal Repository-like object wrapping an AsyncMock TdbClient."""

    def __init__(self, tdb):
        self.tdb = tdb
        self.transition = AsyncMock()
        self.get_documents_by_status = tdb.get_documents_by_status
        self.get_document = tdb.get_document
        self.get_documents = AsyncMock(return_value=[])
        self.create = AsyncMock()


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _make_engine(
    *,
    channels: list | None = None,
    pending_firings: list[dict] | None = None,
    notified_firings: list[dict] | None = None,
    snoozed_firings: list[dict] | None = None,
    trigger_doc: dict | None = None,
    subject_doc: dict | None = None,
    now: datetime | None = None,
) -> NotifyEngine:
    """Build a NotifyEngine backed by an AsyncMock TdbClient wrapped in FakeRepo."""
    tdb = AsyncMock()
    tdb.get_documents_by_status = AsyncMock()
    tdb.get_document = AsyncMock()
    tdb.insert_documents = AsyncMock(return_value=["fake-iri"])

    # Build lookup of all docs by @id for get_document
    all_docs_by_id: dict[str, dict] = {}
    for f in (pending_firings or []):
        all_docs_by_id[f["@id"]] = dict(f)
    for f in (notified_firings or []):
        all_docs_by_id[f["@id"]] = dict(f)
    for f in (snoozed_firings or []):
        all_docs_by_id[f["@id"]] = dict(f)
    if trigger_doc:
        all_docs_by_id[trigger_doc["@id"]] = dict(trigger_doc)
    if subject_doc:
        all_docs_by_id[subject_doc["@id"]] = dict(subject_doc)

    # Route get_documents_by_status by status
    async def _docs_by_status(type_: str, status: str, branch: str = "main"):
        if status == "pending":
            return [dict(f) for f in (pending_firings or [])]
        if status == "notified":
            return [dict(f) for f in (notified_firings or [])]
        if status == "snoozed":
            return [dict(f) for f in (snoozed_firings or [])]
        return []

    tdb.get_documents_by_status.side_effect = _docs_by_status

    # Route get_document (also handles firing @ids for post-transition bumps)
    async def _get_doc(iri: str, branch: str = "main"):
        doc = all_docs_by_id.get(iri)
        if doc is not None:
            return dict(doc)
        raise Exception(f"Not found: {iri}")

    tdb.get_document.side_effect = _get_doc

    repo = FakeRepo(tdb)

    if channels is None:
        channels = []
    if now is None:
        now = _frozen_now()

    return NotifyEngine(repo=repo, channels=channels, now=lambda: now)


# ---------------------------------------------------------------------------
# Pending → Notified
# ---------------------------------------------------------------------------


class TestPendingToNotified:
    @pytest.mark.asyncio
    async def test_pending_firing_notified_with_count_1(self):
        """A pending firing gets notified: status=notified, notification_count=1, last_notified_at set."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        firing = {
            "@id": "TriggerFiring/f1",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": None,
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], pending_firings=[firing], now=now)

        with structlog.testing.capture_logs() as _captured:
            await engine.run_cycle()

        # Channel was called
        assert len(channel.calls) == 1
        assert channel.calls[0]["firing"]["@id"] == "TriggerFiring/f1"
        assert channel.calls[0]["subject"] is None

        # transition called with correct args
        engine.repo.transition.assert_called_once_with(
            "TriggerFiring/f1",
            "status",
            "pending",
            "notified",
            agent="service:notifyd",
        )
        # insert_documents called for bump
        engine.repo.tdb.insert_documents.assert_called_once()
        bump_call = engine.repo.tdb.insert_documents.call_args[0]
        bump_docs = bump_call[0]
        assert len(bump_docs) == 1
        assert bump_docs[0]["notification_count"] == 1
        assert bump_docs[0]["last_notified_at"] is not None
        assert bump_docs[0]["last_notified_at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_pending_with_subject_resolved(self):
        """Subject IRI is resolved and passed to channels."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        subject_doc = {
            "@id": "Reminder/r1",
            "@type": "Reminder",
            "name": "Test Reminder",
        }
        firing = {
            "@id": "TriggerFiring/f2",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": "Reminder/r1",
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], pending_firings=[firing], subject_doc=subject_doc, now=now)

        await engine.run_cycle()

        assert len(channel.calls) == 1
        assert channel.calls[0]["subject"] == subject_doc
        engine.repo.transition.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_subject_resolution_failure_tolerated(self):
        """When subject fetch fails, subject=None is passed — no crash."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        firing = {
            "@id": "TriggerFiring/f3",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": "Reminder/nonexistent",
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        # subject_doc is None, so get_document for Reminder/nonexistent will raise
        engine = _make_engine(channels=[channel], pending_firings=[firing], subject_doc=None, now=now)

        await engine.run_cycle()

        # Still delivered with subject=None
        assert len(channel.calls) == 1
        assert channel.calls[0]["subject"] is None
        engine.repo.transition.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_channels_fail_leaves_pending(self):
        """When all channels return ok=False, firing stays pending — no transition."""
        now = _frozen_now()
        channel = FakeChannel(ok=False, detail="send failed")
        firing = {
            "@id": "TriggerFiring/f4",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": None,
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], pending_firings=[firing], now=now)

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        assert len(channel.calls) == 1
        engine.repo.transition.assert_not_called()
        engine.repo.tdb.insert_documents.assert_not_called()
        all_failed = [e for e in captured if e.get("event") == "delivery_all_failed"]
        assert len(all_failed) == 1

    @pytest.mark.asyncio
    async def test_first_channel_ok_second_fails_still_notifies(self):
        """At least one channel ok → notify. Other failures logged but not fatal."""
        now = _frozen_now()
        ok_channel = FakeChannel(ok=True)
        fail_channel = FakeChannel(ok=False, detail="nope")
        firing = {
            "@id": "TriggerFiring/f5",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": None,
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[ok_channel, fail_channel], pending_firings=[firing], now=now)

        await engine.run_cycle()

        assert len(ok_channel.calls) == 1
        assert len(fail_channel.calls) == 1
        engine.repo.transition.assert_called_once()

    @pytest.mark.asyncio
    async def test_channel_exception_is_tolerated(self):
        """A channel that raises is skipped; other channels still tried."""
        now = _frozen_now()
        bad_channel = FakeChannel(ok=True, exception=RuntimeError("boom"))
        good_channel = FakeChannel(ok=True)
        firing = {
            "@id": "TriggerFiring/f6",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T11:00:00Z",
            "scheduled_for": "2026-07-07T11:00:00Z",
            "fired_at": "2026-07-07T11:59:00Z",
            "status": "pending",
            "subject": None,
            "created_at": "2026-07-07T11:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[bad_channel, good_channel], pending_firings=[firing], now=now)

        await engine.run_cycle()

        assert len(good_channel.calls) == 1
        engine.repo.transition.assert_called_once()


# ---------------------------------------------------------------------------
# No channels idle
# ---------------------------------------------------------------------------


class TestNoChannelsIdle:
    @pytest.mark.asyncio
    async def test_no_channels_idles_gracefully(self):
        """Zero channels → cycle returns without fetching or writing anything."""
        engine = _make_engine(channels=[])

        await engine.run_cycle()

        engine.repo.tdb.get_documents_by_status.assert_not_called()
        engine.repo.tdb.insert_documents.assert_not_called()


# ---------------------------------------------------------------------------
# Renotify / Expiry
# ---------------------------------------------------------------------------


class TestRenotifyAndExpiry:
    @pytest.mark.asyncio
    async def test_renotify_fires_after_renotify_every(self):
        """When renotify_every has passed, firing is redelivered and notification_count bumped."""
        now = _frozen_now()
        last_notified = now - timedelta(hours=2)
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "renotify_every": "PT1H",
        }
        firing = {
            "@id": "TriggerFiring/f7",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(last_notified),
            "notification_count": 1,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        await engine.run_cycle()

        assert len(channel.calls) == 1
        engine.repo.tdb.insert_documents.assert_called_once()
        updated_doc = engine.repo.tdb.insert_documents.call_args[0][0][0]
        assert updated_doc["notification_count"] == 2

    @pytest.mark.asyncio
    async def test_renotify_not_due_yet_skipped(self):
        """When renotify_every has NOT passed, no redelivery."""
        now = _frozen_now()
        last_notified = now - timedelta(minutes=30)  # only 30 min ago
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "renotify_every": "PT1H",
        }
        firing = {
            "@id": "TriggerFiring/f8",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(last_notified),
            "notification_count": 1,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:30:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        await engine.run_cycle()

        assert len(channel.calls) == 0
        engine.repo.tdb.insert_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_renotifications_respected(self):
        """When notification_count reaches 1 + max_renotifications, no more renotifies."""
        now = _frozen_now()
        last_notified = now - timedelta(hours=2)
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "renotify_every": "PT1H",
            "max_renotifications": 3,  # total max = 4 notifications
        }
        firing = {
            "@id": "TriggerFiring/f9",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(last_notified),
            "notification_count": 4,  # already at cap (1 + 3)
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        await engine.run_cycle()

        assert len(channel.calls) == 0
        engine.repo.tdb.insert_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_renotifications_none_unlimited(self):
        """max_renotifications=None → unlimited renotifies."""
        now = _frozen_now()
        last_notified = now - timedelta(hours=2)
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "renotify_every": "PT1H",
            "max_renotifications": None,
        }
        firing = {
            "@id": "TriggerFiring/f10",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(last_notified),
            "notification_count": 99,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        await engine.run_cycle()

        assert len(channel.calls) == 1
        engine.repo.tdb.insert_documents.assert_called_once()
        updated_doc = engine.repo.tdb.insert_documents.call_args[0][0][0]
        assert updated_doc["notification_count"] == 100

    @pytest.mark.asyncio
    async def test_expire_after_expires(self):
        """When expire_after has passed, firing transitions to expired."""
        now = _frozen_now()
        scheduled = now - timedelta(hours=3)
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "expire_after": "PT1H",  # expired 2h ago
            "renotify_every": "PT30M",
        }
        firing = {
            "@id": "TriggerFiring/f11",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T09:00:00Z",
            "scheduled_for": _utc_iso(scheduled),
            "fired_at": "2026-07-07T09:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(now - timedelta(hours=2)),
            "notification_count": 1,
            "created_at": "2026-07-07T09:00:00Z",
            "updated_at": "2026-07-07T10:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        await engine.run_cycle()

        # Expiry takes precedence over renotify
        assert len(channel.calls) == 0
        engine.repo.transition.assert_called_once_with(
            "TriggerFiring/f11",
            "status",
            "notified",
            "expired",
            agent="service:notifyd",
        )

    @pytest.mark.asyncio
    async def test_malformed_renotify_every_skipped_with_log(self):
        """Unparseable renotify_every → logged, no crash, no update."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "renotify_every": "not-a-duration",
        }
        firing = {
            "@id": "TriggerFiring/f12",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(now - timedelta(hours=2)),
            "notification_count": 1,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        assert len(channel.calls) == 0
        engine.repo.tdb.insert_documents.assert_not_called()
        warnings = [e for e in captured if e.get("event") == "unparseable_renotify_every"]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_malformed_expire_after_logged_but_continues(self):
        """Unparseable expire_after → logged as warning, renotify still checked."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        trigger_doc = {
            "@id": "OneShotTrigger/t1",
            "@type": "OneShotTrigger",
            "expire_after": "garbage",
            "renotify_every": "PT1H",
        }
        firing = {
            "@id": "TriggerFiring/f13",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(now - timedelta(hours=2)),
            "notification_count": 1,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=trigger_doc,
            now=now,
        )

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        # Renotify still happened
        assert len(channel.calls) == 1
        engine.repo.tdb.insert_documents.assert_called_once()
        warnings = [e for e in captured if e.get("event") == "unparseable_expire_after"]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_trigger_fetch_failure_skipped(self):
        """When trigger doc can't be fetched, firing is skipped — no crash."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        # No trigger_doc → get_document will raise
        firing = {
            "@id": "TriggerFiring/f14",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/missing",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "notified",
            "subject": None,
            "last_notified_at": _utc_iso(now - timedelta(hours=2)),
            "notification_count": 1,
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(
            channels=[channel],
            notified_firings=[firing],
            trigger_doc=None,
            now=now,
        )

        await engine.run_cycle()

        assert len(channel.calls) == 0
        engine.repo.transition.assert_not_called()
        engine.repo.tdb.insert_documents.assert_not_called()


# ---------------------------------------------------------------------------
# Snoozed wake-up
# ---------------------------------------------------------------------------


class TestSnoozed:
    @pytest.mark.asyncio
    async def test_snoozed_wakes_up_and_notifies(self):
        """When snoozed_until <= now, delivers and transitions to notified.

        Preserves prior notification_count (increments, doesn't reset).
        snoozed_until key is removed entirely (not set to null).
        """
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        firing = {
            "@id": "TriggerFiring/f15",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "snoozed",
            "subject": None,
            "snoozed_until": _utc_iso(now - timedelta(minutes=5)),
            "notification_count": 3,
            "last_notified_at": _utc_iso(now - timedelta(hours=1)),
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], snoozed_firings=[firing], now=now)

        await engine.run_cycle()

        assert len(channel.calls) == 1
        # transition called: snoozed → notified
        engine.repo.transition.assert_called_once_with(
            "TriggerFiring/f15",
            "status",
            "snoozed",
            "notified",
            agent="service:notifyd",
        )
        # insert_documents called for unsnooze bump
        engine.repo.tdb.insert_documents.assert_called_once()
        bump_docs = engine.repo.tdb.insert_documents.call_args[0][0]
        assert len(bump_docs) == 1
        updated_doc = bump_docs[0]
        # Preserved count + 1
        assert updated_doc["notification_count"] == 4
        # snoozed_until must be absent (not null)
        assert "snoozed_until" not in updated_doc
        # No None values anywhere in the replaced doc
        assert all(v is not None for v in updated_doc.values())

    @pytest.mark.asyncio
    async def test_snoozed_not_due_stays_snoozed(self):
        """When snoozed_until is in the future, no delivery."""
        now = _frozen_now()
        channel = FakeChannel(ok=True)
        firing = {
            "@id": "TriggerFiring/f16",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "snoozed",
            "subject": None,
            "snoozed_until": _utc_iso(now + timedelta(hours=1)),
            "notification_count": 1,
            "last_notified_at": _utc_iso(now - timedelta(hours=1)),
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], snoozed_firings=[firing], now=now)

        await engine.run_cycle()

        assert len(channel.calls) == 0
        engine.repo.transition.assert_not_called()
        engine.repo.tdb.insert_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_snoozed_delivery_all_fails_stays_snoozed(self):
        """When snoozed wake-up delivery fails, stays snoozed for retry."""
        now = _frozen_now()
        channel = FakeChannel(ok=False)
        firing = {
            "@id": "TriggerFiring/f17",
            "@type": "TriggerFiring",
            "trigger": "OneShotTrigger/t1",
            "occurrence_key": "2026-07-07T10:00:00Z",
            "scheduled_for": "2026-07-07T10:00:00Z",
            "fired_at": "2026-07-07T10:59:00Z",
            "status": "snoozed",
            "subject": None,
            "snoozed_until": _utc_iso(now - timedelta(minutes=5)),
            "notification_count": 1,
            "last_notified_at": _utc_iso(now - timedelta(hours=1)),
            "created_at": "2026-07-07T10:00:00Z",
            "updated_at": "2026-07-07T11:00:00Z",
        }
        engine = _make_engine(channels=[channel], snoozed_firings=[firing], now=now)

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        assert len(channel.calls) == 1
        engine.repo.transition.assert_not_called()
        engine.repo.tdb.insert_documents.assert_not_called()
        failed = [e for e in captured if e.get("event") == "snoozed_delivery_all_failed"]
        assert len(failed) == 1


# ---------------------------------------------------------------------------
# Import test — zero extensions installed
# ---------------------------------------------------------------------------


def test_module_imports_with_zero_extensions():
    """All modules import successfully even with no extensions installed."""
