"""Legacy zero-config notification loop (default_notify).

This module contains the original notification loop logic extracted from
engine.py.  It processes TriggerFiring documents in three phases:
pending → deliver → notified, nag/expiry policy, and snooze wake-up.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from firnline_core.base import _format_datetime
from firnline_core.conventions import agent_id
from firnline_core.durations import parse_duration, parse_iso_datetime
from firnline_core.plugins import DeliveryResult, NotifyContext
from firnline_core.repository import TransitionError as RepoTransitionError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_nones(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *doc* with all ``None``-valued keys removed."""
    return {k: v for k, v in doc.items() if v is not None}


# ---------------------------------------------------------------------------
# Legacy notification loop
# ---------------------------------------------------------------------------


class LegacyNotifyLoop:
    """Legacy zero-config notification loop.

    Each cycle processes TriggerFiring documents by status:
    1. **pending** — deliver via channels, transition to notified.
    2. **notified** — check nag/expiry policy on the trigger doc, renotify or expire.
    3. **snoozed** — wake up when snoozed_until has passed, deliver as pending.
    """

    def __init__(
        self,
        repo: Any,
        channels: list[object],
        *,
        now: Any = None,
        logger: Any = None,
    ) -> None:
        self.repo = repo
        self.channels = channels
        self.log = logger or structlog.get_logger(__name__)
        self._now = now if now is not None else self._utc_now
        self._agent = agent_id("service", "effectd")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(tz=timezone.utc)

    async def _resolve_subject(self, subject_iri: str | None) -> dict[str, Any] | None:
        """Resolve a subject IRI to its document, tolerating failures."""
        if not subject_iri:
            return None
        try:
            return await self.repo.get_document(subject_iri)
        except Exception:
            self.log.debug("subject_resolution_failed", subject=subject_iri, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: Any = None) -> None:
        """Run one full notification cycle."""
        if should_stop is not None and getattr(should_stop, "is_set", lambda: False)():
            return

        repo = self.repo
        now = self._now()

        if not self.channels:
            self.log.debug("cycle_idle_no_channels")
            return

        # ── Phase a: PENDING firings ─────────────────────────────────
        try:
            pending = await repo.get_documents_by_status("TriggerFiring", "pending")
        except Exception:
            self.log.warning("pending_fetch_failed", exc_info=True)
            pending = []

        for firing in pending:
            subject = await self._resolve_subject(firing.get("subject"))
            ctx = NotifyContext(tdb=repo.tdb, logger=self.log, now=lambda: now)
            delivered = await self._deliver(firing, subject, ctx)
            if delivered:
                try:
                    await repo.transition(
                        firing["@id"],
                        "status",
                        "pending",
                        "notified",
                        agent=self._agent,
                    )
                except RepoTransitionError as exc:
                    self.log.warning("firing_transition_failed", firing=firing.get("@id"), error=str(exc))
                # Update non-status fields (notification_count, last_notified_at)
                # on top of the already-transitioned document
                try:
                    doc = await repo.get_document(firing["@id"])
                    doc["last_notified_at"] = _format_datetime(now)
                    doc["notification_count"] = 1
                    await repo.tdb.insert_documents([doc], message=f"effectd: bump {firing.get('@id', '?')}")
                except Exception:
                    self.log.warning("firing_bump_failed", firing=firing.get("@id"), exc_info=True)
            else:
                self.log.info("delivery_all_failed", firing=firing.get("@id"))

        # ── Phase b: NOTIFIED firings (renag / expiry) ───────────────
        try:
            notified = await repo.get_documents_by_status("TriggerFiring", "notified")
        except Exception:
            self.log.warning("notified_fetch_failed", exc_info=True)
            notified = []

        for firing in notified:
            trigger_doc = None
            trigger_iri = firing.get("trigger")
            if trigger_iri:
                try:
                    trigger_doc = await repo.get_document(trigger_iri)
                except Exception:
                    self.log.debug("trigger_fetch_failed", trigger=trigger_iri, exc_info=True)

            if trigger_doc is None:
                continue

            expire_after_raw = trigger_doc.get("expire_after")
            renotify_every_raw = trigger_doc.get("renotify_every")
            max_renotifications = trigger_doc.get("max_renotifications")

            scheduled_for = parse_iso_datetime(firing["scheduled_for"])

            # ── Expiry check ─────────────────────────────────────────
            if expire_after_raw:
                expire_delta = parse_duration(expire_after_raw)
                if expire_delta is not None:
                    if now >= scheduled_for + expire_delta:
                        try:
                            await repo.transition(
                                firing["@id"],
                                "status",
                                "notified",
                                "expired",
                                agent=self._agent,
                            )
                        except RepoTransitionError as exc:
                            self.log.warning("expire_transition_failed", firing=firing.get("@id"), error=str(exc))
                        continue
                else:
                    self.log.warning(
                        "unparseable_expire_after",
                        trigger=trigger_iri,
                        expire_after=expire_after_raw,
                    )

            # ── Renotify check ───────────────────────────────────────
            if renotify_every_raw:
                renotify_delta = parse_duration(renotify_every_raw)
                if renotify_delta is None:
                    self.log.warning(
                        "unparseable_renotify_every",
                        trigger=trigger_iri,
                        renotify_every=renotify_every_raw,
                    )
                    continue

                last_notified_raw = firing.get("last_notified_at")
                if not last_notified_raw:
                    continue

                last_notified = parse_iso_datetime(last_notified_raw)
                if now >= last_notified + renotify_delta:
                    notification_count = firing.get("notification_count") or 0
                    cap = (1 + max_renotifications) if max_renotifications is not None else None
                    if cap is None or notification_count < cap:
                        subject = await self._resolve_subject(firing.get("subject"))
                        ctx = NotifyContext(tdb=repo.tdb, logger=self.log, now=lambda: now)
                        redelivered = await self._deliver(firing, subject, ctx)
                        if redelivered:
                            try:
                                doc = await repo.get_document(firing["@id"])
                                doc["notification_count"] = notification_count + 1
                                doc["last_notified_at"] = _format_datetime(now)
                                await repo.tdb.insert_documents(
                                    [doc], message=f"effectd: renotify {firing.get('@id', '?')}"
                                )
                            except Exception:
                                self.log.warning("renotify_bump_failed", firing=firing.get("@id"), exc_info=True)
                        else:
                            self.log.info("renotify_all_failed", firing=firing.get("@id"))

        # ── Phase c: SNOOZED firings ─────────────────────────────────
        try:
            snoozed = await repo.get_documents_by_status("TriggerFiring", "snoozed")
        except Exception:
            self.log.warning("snoozed_fetch_failed", exc_info=True)
            snoozed = []

        for firing in snoozed:
            snoozed_until_raw = firing.get("snoozed_until")
            if not snoozed_until_raw:
                continue
            snoozed_until = parse_iso_datetime(snoozed_until_raw)
            if now >= snoozed_until:
                subject = await self._resolve_subject(firing.get("subject"))
                ctx = NotifyContext(tdb=repo.tdb, logger=self.log, now=lambda: now)
                delivered = await self._deliver(firing, subject, ctx)
                if delivered:
                    try:
                        await repo.transition(
                            firing["@id"],
                            "status",
                            "snoozed",
                            "notified",
                            agent=self._agent,
                        )
                    except RepoTransitionError as exc:
                        self.log.warning("snoozed_transition_failed", firing=firing.get("@id"), error=str(exc))
                    try:
                        doc = await repo.get_document(firing["@id"])
                        doc["last_notified_at"] = _format_datetime(now)
                        doc["notification_count"] = (firing.get("notification_count") or 0) + 1
                        doc["snoozed_until"] = None
                        cleaned = _strip_nones(doc)
                        await repo.tdb.insert_documents([cleaned], message=f"effectd: unsnooze {firing.get('@id', '?')}")
                    except Exception:
                        self.log.warning("unsnooze_bump_failed", firing=firing.get("@id"), exc_info=True)
                else:
                    self.log.info("snoozed_delivery_all_failed", firing=firing.get("@id"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: NotifyContext,
    ) -> bool:
        """Try all channels; return True if at least one succeeds."""
        any_ok = False
        for channel in self.channels:
            try:
                result = await channel.deliver(firing, subject, ctx)
            except Exception:
                self.log.warning(
                    "channel_deliver_exception",
                    channel=getattr(channel, "name", "?"),
                    firing=firing.get("@id"),
                    exc_info=True,
                )
                continue
            if isinstance(result, DeliveryResult) and result.ok:
                any_ok = True
            else:
                self.log.info(
                    "channel_deliver_failed",
                    channel=getattr(channel, "name", "?"),
                    firing=firing.get("@id"),
                    detail=getattr(result, "detail", ""),
                )
        return any_ok
