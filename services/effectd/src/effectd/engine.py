"""Effect engine — orchestrates plan/execute phases over TriggerFiring documents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from effectd.legacy_notify import LegacyNotifyLoop, _strip_nones
from firnline_core.base import _format_datetime
from firnline_core.conventions import agent_id, utc_now
from firnline_core.durations import parse_duration, parse_iso_datetime
from firnline_core.plugins import ActionContext, ExecutionResult
from firnline_core.repository import TransitionError as RepoTransitionError
from firnline_core.tdb import TdbConflictError, short_iri

if TYPE_CHECKING:
    from effectd.settings import EffectdSettings

logger = structlog.get_logger(__name__)

_UTC = timezone.utc

# Concrete Action subclasses queryable via TerminusDB document API.
# The abstract "Action" class cannot be queried — see docs/terminusdb-notes.md §8.
_CONCRETE_ACTION_TYPES = ("WebhookAction", "NotifyAction")


class EffectEngine:
    """Effect delivery engine.

    Each ``run_cycle`` executes three phases in order:

    1. **PLAN** — enumerate (action, firing) pairs missing an
       ActionExecution and insert exactly one per pair.
    2. **EXECUTE** — pick up pending ActionExecution documents, resolve
       executor, invoke with timeout, persist outcomes.
    3. **LEGACY** — delegate to :class:`LegacyNotifyLoop` when
       ``settings.legacy_notification_loop`` is enabled (default).
    """

    def __init__(
        self,
        repo: Any,
        channels: list[object],
        *,
        executors: list[Any] | None = None,
        settings: EffectdSettings | None = None,
        now: Any = None,
        logger: Any = None,
    ) -> None:
        self.repo = repo
        self.channels = channels
        self.executors: list[Any] = executors or []
        self.settings = settings
        self.log = logger or structlog.get_logger(__name__)
        self._now = now if now is not None else utc_now
        self._agent = agent_id("service", "effectd")

        if settings is None or settings.legacy_notification_loop:
            self._legacy = LegacyNotifyLoop(
                repo=repo,
                channels=channels,
                now=now,
                logger=logger,
            )
        else:
            self._legacy = None

    # ------------------------------------------------------------------
    # run_cycle — top-level phase dispatcher
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: Any = None) -> None:
        """Run one full delivery cycle: plan → execute → legacy."""
        if should_stop is not None and getattr(should_stop, "is_set", lambda: False)():
            return

        now = self._now()

        try:
            await self._plan(now)
        except Exception:
            self.log.warning("plan_phase_failed", exc_info=True)

        try:
            await self._execute(now)
        except Exception:
            self.log.warning("execute_phase_failed", exc_info=True)

        if self._legacy is not None:
            await self._legacy.run_cycle(should_stop)

    # ------------------------------------------------------------------
    # Phase 1 — PLAN
    # ------------------------------------------------------------------

    async def _plan(self, now: datetime) -> None:
        """Discover (action, firing) pairs and create missing ActionExecutions."""
        settings = self.settings
        if settings is None:
            return

        # ── Fetch all Action documents (concrete subclasses only) ─────────
        # Abstract "Action" is not queryable per terminusdb-notes §8.
        actions: list[dict[str, Any]] = []
        for type_ in _CONCRETE_ACTION_TYPES:
            try:
                docs = await self.repo.get_documents(type_)
                actions.extend(docs)
            except Exception:
                self.log.warning("action_fetch_failed", type=type_, exc_info=True)

        enabled_actions = [a for a in actions if a.get("enabled") is not False]
        if not enabled_actions:
            return

        # ── Fetch TriggerFiring docs in the planning window ───────────────
        try:
            firings = await self.repo.get_documents("TriggerFiring")
        except Exception:
            self.log.warning("firing_fetch_failed", exc_info=True)
            return

        lookback = parse_duration(settings.planning_lookback)
        window_start = now - lookback if lookback is not None else now
        firings = [f for f in firings if _scheduled_after(f, window_start)]

        if not firings:
            return

        # ── Fetch existing ActionExecution docs ───────────────────────────
        try:
            executions = await self.repo.get_documents("ActionExecution")
        except Exception:
            self.log.warning("execution_fetch_failed", exc_info=True)
            executions = []

        # Index by (short_action_iri, short_firing_iri)
        existing: set[tuple[str, str]] = set()
        for ex in executions:
            action_iri = short_iri(ex.get("action", ""))
            firing_iri = short_iri(ex.get("firing", ""))
            if action_iri and firing_iri:
                existing.add((action_iri, firing_iri))

        # ── Insert missing executions ─────────────────────────────────────
        for action in enabled_actions:
            try:
                await self._plan_for_action(now, action, firings, existing)
            except Exception:
                self.log.warning(
                    "plan_action_failed",
                    action=action.get("@id", "?"),
                    exc_info=True,
                )

    async def _plan_for_action(
        self,
        now: datetime,
        action: dict[str, Any],
        firings: list[dict[str, Any]],
        existing: set[tuple[str, str]],
    ) -> None:
        """Create ActionExecution docs for one action across all matching firings."""
        action_iri = action.get("@id", "")
        action_short = short_iri(action_iri)
        action_trigger = short_iri(action.get("trigger", ""))
        action_mode = action.get("mode", "approval")  # default: approval
        action_name = action.get("name", action_short)

        for firing in firings:
            firing_trigger = short_iri(firing.get("trigger", ""))
            if firing_trigger != action_trigger:
                continue

            firing_short = short_iri(firing.get("@id", ""))
            if (action_short, firing_short) in existing:
                continue

            # Determine initial execution status
            dry_run_global = bool(self.settings and self.settings.dry_run)
            idempotency_key = f"{action_short}#{firing_short}"

            if dry_run_global or action_mode == "dry_run":
                status = "skipped"
                result_detail = "dry_run"
            elif action_mode == "auto":
                status = "pending"
                result_detail = None
            else:
                # Default when mode absent or explicitly "approval"
                status = "pending_approval"
                result_detail = None

            doc = {
                "@type": "ActionExecution",
                "action": action_iri,
                "firing": firing.get("@id", ""),
                "status": status,
                "idempotency_key": idempotency_key,
                "attempt": 0,
                "created_at": _format_datetime(now),
                "updated_at": _format_datetime(now),
                "provenance": {
                    "agent": self._agent,
                    "at": _format_datetime(now),
                    "method": "planner",
                },
            }
            if result_detail is not None:
                doc["result_detail"] = result_detail

            firing_key = firing.get("occurrence_key") or firing_short
            try:
                await self.repo.create(
                    doc,
                    agent=self._agent,
                    method="planner",
                )
                self.log.info(
                    "execution_planned",
                    action=action_name,
                    firing=firing_key,
                    status=status,
                )
            except TdbConflictError:
                self.log.warning(
                    "execution_plan_conflict",
                    action=action_name,
                    firing=firing_key,
                )
            except Exception:
                self.log.warning(
                    "execution_plan_failed",
                    action=action_name,
                    firing=firing_key,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Phase 2 — EXECUTE
    # ------------------------------------------------------------------

    async def _execute(self, now: datetime) -> None:
        """Pick up pending ActionExecution docs, invoke executors, persist outcomes."""
        settings = self.settings
        if settings is None or not self.executors:
            return

        try:
            pending_execs = await self.repo.get_documents_by_status("ActionExecution", "pending")
        except Exception:
            self.log.warning("execute_fetch_failed", exc_info=True)
            return

        # Sort oldest-first, cap
        pending_execs.sort(key=lambda d: d.get("created_at", ""))
        max_ex = settings.max_executions_per_cycle
        pending_execs = pending_execs[:max_ex]

        missing_kinds: set[str] = set()

        for execution in pending_execs:
            try:
                await self._execute_one(now, execution, missing_kinds)
            except Exception:
                self.log.warning(
                    "execute_one_failed",
                    execution=execution.get("@id", "?"),
                    exc_info=True,
                )

    async def _execute_one(
        self,
        now: datetime,
        execution: dict[str, Any],
        missing_kinds: set[str],
    ) -> None:
        """Execute a single pending ActionExecution."""
        execution_iri = execution.get("@id", "")

        # ── Check next_attempt_at ──────────────────────────────────────
        next_at_raw = execution.get("next_attempt_at")
        if next_at_raw:
            try:
                next_at = parse_iso_datetime(next_at_raw)
                if now < next_at:
                    return  # not yet due
            except Exception:
                pass  # unparseable → proceed

        # ── Resolve action, firing, subject ────────────────────────────
        try:
            action = await self.repo.get_document(execution["action"])
        except Exception:
            self.log.warning("action_resolve_failed", execution=execution_iri, exc_info=True)
            return

        try:
            firing = await self.repo.get_document(execution["firing"])
        except Exception:
            self.log.warning("firing_resolve_failed", execution=execution_iri, exc_info=True)
            return

        subject = await self._resolve_subject(firing.get("subject"))

        # ── Select executor ────────────────────────────────────────────
        executor_kind = action.get("executor", "")
        executor = _select_executor(self.executors, executor_kind)
        if executor is None:
            if executor_kind not in missing_kinds:
                missing_kinds.add(executor_kind)
                self.log.warning("executor_missing", kind=executor_kind)
            return  # leave pending, do not consume an attempt

        # ── Execute with timeout ───────────────────────────────────────
        timeout_raw = action.get("timeout") or (self.settings.default_timeout if self.settings else "PT30S")
        timeout_td = parse_duration(timeout_raw)
        timeout_secs = timeout_td.total_seconds() if timeout_td else 30.0

        ctx = ActionContext(
            tdb=self.repo.tdb,
            logger=self.log,
            now=lambda: now,
            idempotency_key=execution.get("idempotency_key", ""),
            dry_run=False,
        )

        try:
            result = await asyncio.wait_for(
                executor.execute(action, firing, subject, ctx),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            result = ExecutionResult(ok=False, retryable=True, detail="timeout")
        except Exception as exc:
            result = ExecutionResult(ok=False, retryable=True, detail=str(exc))

        # ── Persist outcome ────────────────────────────────────────────
        try:
            await self._persist_outcome(now, execution, action, result)
        except TdbConflictError:
            self.log.warning("execute_persist_conflict", execution=execution_iri)

    async def _persist_outcome(
        self,
        now: datetime,
        execution: dict[str, Any],
        action: dict[str, Any],
        result: ExecutionResult,
    ) -> None:
        """Write the execution result back to TerminusDB."""
        execution_iri = execution["@id"]
        prior_attempt = int(execution.get("attempt", 0))
        new_attempt = prior_attempt + 1

        max_attempts = action.get("max_attempts") or (self.settings.default_max_attempts if self.settings else 3)
        backoff_raw = action.get("retry_backoff") or (self.settings.default_retry_backoff if self.settings else "PT1M")
        backoff_base = parse_duration(backoff_raw)
        backoff_td = backoff_base if backoff_base else parse_duration("PT1M")
        assert backoff_td is not None

        repo = self.repo
        now_str = _format_datetime(now)

        if result.ok:
            # success: transition pending → succeeded
            try:
                await repo.transition(
                    execution_iri,
                    "status",
                    "pending",
                    "succeeded",
                    agent=self._agent,
                )
            except RepoTransitionError as exc:
                self.log.warning("transition_failed", execution=execution_iri, error=str(exc))
                return

            # Write extra fields via insert (mirrors legacy loop pattern)
            try:
                doc = await repo.get_document(execution_iri)
                doc["attempt"] = new_attempt
                doc["executed_at"] = now_str
                doc["external_ref"] = result.external_ref
                doc["result_detail"] = result.detail or None
                doc["updated_at"] = now_str
                cleaned = _strip_nones(doc)
                await repo.tdb.insert_documents(
                    [cleaned],
                    message=f"effectd: success {short_iri(execution_iri)}",
                )
            except Exception:
                self.log.warning("success_field_update_failed", execution=execution_iri, exc_info=True)

        else:
            # failure
            if result.retryable and new_attempt < max_attempts:
                # retryable, not yet exhausted → stay pending, set backoff
                try:
                    doc = await repo.get_document(execution_iri)
                    backoff_secs = backoff_td.total_seconds() * (2 ** prior_attempt)
                    next_at = now_str if backoff_secs == 0 else _format_datetime(
                        now + backoff_td * (2 ** prior_attempt)
                    )
                    doc["attempt"] = new_attempt
                    doc["executed_at"] = now_str
                    doc["next_attempt_at"] = next_at
                    doc["result_detail"] = result.detail or None
                    doc["updated_at"] = now_str
                    cleaned = _strip_nones(doc)
                    await repo.tdb.insert_documents(
                        [cleaned],
                        message=f"effectd: retry {short_iri(execution_iri)}",
                    )
                except Exception:
                    self.log.warning("retry_persist_failed", execution=execution_iri, exc_info=True)
            elif result.retryable:
                # attempts exhausted → dead
                try:
                    await repo.transition(
                        execution_iri,
                        "status",
                        "pending",
                        "dead",
                        agent=self._agent,
                    )
                except RepoTransitionError as exc:
                    self.log.warning("transition_failed", execution=execution_iri, error=str(exc))
                    return
                try:
                    doc = await repo.get_document(execution_iri)
                    doc["attempt"] = new_attempt
                    doc["executed_at"] = now_str
                    doc["result_detail"] = result.detail or None
                    doc["updated_at"] = now_str
                    cleaned = _strip_nones(doc)
                    await repo.tdb.insert_documents(
                        [cleaned],
                        message=f"effectd: dead {short_iri(execution_iri)}",
                    )
                except Exception:
                    self.log.warning("dead_field_update_failed", execution=execution_iri, exc_info=True)
            else:
                # failure - retryable False → failed
                try:
                    await repo.transition(
                        execution_iri,
                        "status",
                        "pending",
                        "failed",
                        agent=self._agent,
                    )
                except RepoTransitionError as exc:
                    self.log.warning("transition_failed", execution=execution_iri, error=str(exc))
                    return
                try:
                    doc = await repo.get_document(execution_iri)
                    doc["attempt"] = new_attempt
                    doc["executed_at"] = now_str
                    doc["result_detail"] = result.detail or None
                    doc["updated_at"] = now_str
                    cleaned = _strip_nones(doc)
                    await repo.tdb.insert_documents(
                        [cleaned],
                        message=f"effectd: failed {short_iri(execution_iri)}",
                    )
                except Exception:
                    self.log.warning("failed_field_update_failed", execution=execution_iri, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_subject(self, subject_iri: str | None) -> dict[str, Any] | None:
        """Resolve a subject IRI to its document, tolerating failures."""
        if not subject_iri:
            return None
        try:
            return await self.repo.get_document(subject_iri)
        except Exception:
            self.log.debug("subject_resolution_failed", subject=subject_iri, exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _scheduled_after(firing: dict[str, Any], window_start: datetime) -> bool:
    """Return True if *firing*'s scheduled_for is on or after *window_start*."""
    raw = firing.get("scheduled_for")
    if not raw:
        return True  # include if missing
    try:
        dt = parse_iso_datetime(raw)
        return dt >= window_start
    except Exception:
        return True  # include if unparseable


def _select_executor(
    executors: list[Any], kind: str
) -> Any | None:
    """Return the first executor whose ``kinds`` contains *kind*."""
    for ex in executors:
        if kind in ex.kinds:
            return ex
    return None
