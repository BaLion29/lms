"""Tests for effectd.engine — plan/execute phases, executor dispatch, backoff, error paths."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import structlog

from effectd.engine import EffectEngine, _scheduled_after
from effectd.settings import EffectdSettings
from firnline_core.base import _format_datetime
from firnline_core.plugins import ExecutionResult, ModuleRequirement

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
# Fake executor
# ---------------------------------------------------------------------------


class FakeExecutor:
    """An executor with controllable result."""

    name = "fake"
    requires: list[ModuleRequirement] = []

    def __init__(
        self,
        kinds: tuple[str, ...] = ("webhook",),
        *,
        ok: bool = True,
        detail: str = "",
        retryable: bool = False,
        external_ref: str | None = None,
        exception: Exception | None = None,
        sleep: float = 0,
    ) -> None:
        self.kinds = kinds
        self.ok = ok
        self.detail = detail
        self.retryable = retryable
        self.external_ref_val = external_ref
        self.exception = exception
        self.sleep = sleep
        self.calls: list[dict] = []

    async def execute(self, action, firing, subject, ctx):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        self.calls.append({"action": action, "firing": firing, "subject": subject, "ctx": ctx})
        if self.exception:
            raise self.exception
        return ExecutionResult(
            ok=self.ok,
            detail=self.detail,
            retryable=self.retryable,
            external_ref=self.external_ref_val,
        )


# ---------------------------------------------------------------------------
# FakeRepo — minimal Repository-like object
# ---------------------------------------------------------------------------


class FakeRepo:
    """A minimal Repository-like object wrapping an AsyncMock TdbClient."""

    def __init__(self, tdb):
        self.tdb = tdb
        self.transition = AsyncMock()
        self.get_documents_by_status = tdb.get_documents_by_status
        self.get_document = tdb.get_document
        self.get_documents = tdb.get_documents
        self.create = AsyncMock()


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _make_engine(
    *,
    executors: list | None = None,
    actions: list[dict] | None = None,
    firings: list[dict] | None = None,
    executions: list[dict] | None = None,
    now: datetime | None = None,
    settings: EffectdSettings | None = None,
    dry_run_global: bool = False,
) -> tuple[EffectEngine, AsyncMock]:
    """Build an EffectEngine backed by an AsyncMock TdbClient wrapped in FakeRepo."""
    tdb = AsyncMock()
    tdb.get_documents_by_status = AsyncMock()
    tdb.get_document = AsyncMock()
    tdb.get_documents = AsyncMock()
    tdb.insert_documents = AsyncMock(return_value=["fake-iri"])

    if now is None:
        now = _frozen_now()

    # Build lookup of all docs by @id for get_document
    all_docs_by_id: dict[str, dict] = {}
    for a in actions or []:
        all_docs_by_id[a["@id"]] = dict(a)
    for f_ in firings or []:
        all_docs_by_id[f_["@id"]] = dict(f_)
    for e_ in executions or []:
        all_docs_by_id[e_["@id"]] = dict(e_)

    # Route get_documents by type
    async def _get_docs(type_: str, branch: str = "main"):
        if type_ == "WebhookAction":
            return [dict(a) for a in (actions or []) if a.get("@type") == "WebhookAction"]
        if type_ == "NotifyAction":
            return [dict(a) for a in (actions or []) if a.get("@type") == "NotifyAction"]
        if type_ == "TriggerFiring":
            return [dict(f_) for f_ in (firings or [])]
        if type_ == "ActionExecution":
            return [dict(e_) for e_ in (executions or [])]
        return []

    tdb.get_documents.side_effect = _get_docs

    # Route get_documents_by_status
    async def _docs_by_status(type_: str, status: str, branch: str = "main"):
        if type_ == "ActionExecution":
            return [dict(e_) for e_ in (executions or []) if e_.get("status") == status]
        return []

    tdb.get_documents_by_status.side_effect = _docs_by_status

    # Route get_document
    async def _get_doc(iri: str, branch: str = "main"):
        doc = all_docs_by_id.get(iri)
        if doc is not None:
            # Return a copy so the caller can mutate it
            return dict(doc)
        raise Exception(f"Not found: {iri}")

    tdb.get_document.side_effect = _get_doc

    repo = FakeRepo(tdb)

    if settings is None:
        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
        )
    else:
        settings = settings

    if dry_run_global:
        settings = settings.model_copy(update={"dry_run": True})

    engine = EffectEngine(
        repo=repo,
        executors=executors,
        settings=settings,
        now=lambda: now,
    )
    return engine, tdb


def _action(
    *,
    iri: str,
    type_: str = "WebhookAction",
    trigger: str,
    mode: str = "auto",
    enabled: bool = True,
    executor: str = "webhook",
) -> dict:
    return {
        "@id": iri,
        "@type": type_,
        "trigger": trigger,
        "mode": mode,
        "enabled": enabled,
        "executor": executor,
        "name": iri.split("/")[-1] if "/" in iri else iri,
    }


def _firing(*, iri: str, trigger: str, scheduled_for: str | None = None, subject: str | None = None) -> dict:
    return {
        "@id": iri,
        "@type": "TriggerFiring",
        "trigger": trigger,
        "scheduled_for": scheduled_for or _utc_iso(_frozen_now()),
        "subject": subject,
        "status": "pending",
    }


# ===================================================================
# Tests
# ===================================================================


class TestPlanner:
    """Planner creates missing ActionExecution documents."""

    @pytest.mark.asyncio
    async def test_creates_execution_for_action_firing_pair(self):
        """Planner creates exactly one execution per (action, firing)."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        engine.repo.create.assert_called_once()
        call_args = engine.repo.create.call_args
        doc = call_args[0][0]
        assert doc["@type"] == "ActionExecution"
        assert doc["status"] == "pending"
        assert doc["attempt"] == 0
        assert doc["action"] == "WebhookAction/wa"
        assert doc["firing"] == "TriggerFiring/f1"
        assert doc["provenance"]["agent"] == "service:effectd"
        assert doc["provenance"]["method"] == "planner"
        assert doc["provenance"]["at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_rerun_with_existing_execution_creates_none(self):
        """Already-planned pairs are skipped."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
        }

        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        engine.repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_firing_older_than_lookback_excluded(self):
        """Firings with scheduled_for before the planning lookback are ignored."""
        now = _frozen_now()
        old_time = now - timedelta(days=30)
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        old_firing = _firing(iri="TriggerFiring/old", trigger="OneShotTrigger/t1", scheduled_for=_utc_iso(old_time))
        recent_firing = _firing(
            iri="TriggerFiring/recent", trigger="OneShotTrigger/t1", scheduled_for=_utc_iso(now - timedelta(hours=1))
        )

        engine, tdb = _make_engine(
            actions=[action],
            firings=[old_firing, recent_firing],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Only the recent firing should get an execution
        assert engine.repo.create.call_count == 1
        call_args = engine.repo.create.call_args
        doc = call_args[0][0]
        assert doc["firing"] == "TriggerFiring/recent"


class TestModeRouting:
    """ActionExecution status depends on action.mode and global dry_run."""

    @pytest.mark.asyncio
    async def test_dry_run_mode_skipped(self):
        """mode=dry_run → status=skipped + result_detail='dry_run'."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", mode="dry_run")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(actions=[action], firings=[firing], now=now)
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        doc = engine.repo.create.call_args[0][0]
        assert doc["status"] == "skipped"
        assert doc["result_detail"] == "dry_run"

    @pytest.mark.asyncio
    async def test_approval_mode_pending_approval(self):
        """mode=approval → status=pending_approval."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", mode="approval")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(actions=[action], firings=[firing], now=now)
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        doc = engine.repo.create.call_args[0][0]
        assert doc["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_approval_mode_not_executed(self):
        """pending_approval execution is never picked up by execute phase."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", mode="approval")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending_approval",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",))
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Executor not called — skip approve-only
        assert len(executor.calls) == 0
        tdb.insert_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_mode_pending(self):
        """mode=auto → status=pending."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", mode="auto")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(actions=[action], firings=[firing], now=now)
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        doc = engine.repo.create.call_args[0][0]
        assert doc["status"] == "pending"

    @pytest.mark.asyncio
    async def test_missing_mode_defaults_pending_approval(self):
        """When mode is absent, default to pending_approval."""
        now = _frozen_now()
        action = {
            "@id": "WebhookAction/wa",
            "@type": "WebhookAction",
            "trigger": "OneShotTrigger/t1",
            "enabled": True,
            "executor": "webhook",
            "name": "wa",
        }
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(actions=[action], firings=[firing], now=now)
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        doc = engine.repo.create.call_args[0][0]
        assert doc["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_global_dry_run_forces_skipped(self):
        """settings.dry_run=True forces all executions to skipped."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", mode="auto")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            now=now,
            dry_run_global=True,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        doc = engine.repo.create.call_args[0][0]
        assert doc["status"] == "skipped"
        assert doc["result_detail"] == "dry_run"


class TestExecutorSuccess:
    """Executor returns ok=True → execution transitions to succeeded."""

    @pytest.mark.asyncio
    async def test_success_sets_succeeded_status(self):
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=True, external_ref="ext-123")
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Transition called
        engine.repo.transition.assert_called_once_with(
            "ActionExecution/ae1",
            "status",
            "pending",
            "succeeded",
            agent="service:effectd",
        )
        # Executor invoked
        assert len(executor.calls) == 1

        # insert_documents called for field update
        assert tdb.insert_documents.call_count >= 1
        # Find the success insert call
        success_calls = [c for c in tdb.insert_documents.call_args_list if "success" in str(c)]
        # Actually just check the last insert call
        last_call = tdb.insert_documents.call_args_list[-1]
        docs = last_call[0][0]
        assert len(docs) == 1
        updated = docs[0]
        assert updated["attempt"] == 1
        assert updated["executed_at"].endswith("Z")
        assert updated.get("external_ref") == "ext-123"


class TestRetryBackoff:
    """Retryable failures use exponential backoff."""

    @pytest.mark.asyncio
    async def test_retryable_failure_sets_next_attempt_at(self):
        """First retryable failure: attempt 0→1, next_attempt_at = now + 1m."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=False, retryable=True, detail="transient error")
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # No transition — status stays pending
        engine.repo.transition.assert_not_called()

        # Field update via insert_documents
        retry_calls = [c for c in tdb.insert_documents.call_args_list if "retry" in str(c)]
        assert len(retry_calls) == 1
        updated = retry_calls[0][0][0][0]
        assert updated["attempt"] == 1
        assert updated["status"] == "pending"
        # next_attempt_at should be ~now + 1 minute
        next_at = updated["next_attempt_at"]
        assert next_at.endswith("Z")
        parsed = datetime.strptime(next_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert parsed >= now + timedelta(seconds=59)
        assert parsed <= now + timedelta(seconds=61)

    @pytest.mark.asyncio
    async def test_second_retry_doubles_backoff(self):
        """Second retryable failure: attempt 1→2, next_attempt_at = now + 2m."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 1,  # prior attempt was already 1
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=False, retryable=True, detail="still failing")
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        retry_calls = [c for c in tdb.insert_documents.call_args_list if "retry" in str(c)]
        assert len(retry_calls) == 1
        updated = retry_calls[0][0][0][0]
        assert updated["attempt"] == 2
        next_at_str = updated["next_attempt_at"]
        parsed = datetime.strptime(next_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        # backoff: 2^(1) * 60 = 120 seconds
        assert parsed >= now + timedelta(seconds=119)
        assert parsed <= now + timedelta(seconds=121)

    @pytest.mark.asyncio
    async def test_attempts_exhausted_transitions_dead(self):
        """After max_attempts retryable failures → dead."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 2,  # next attempt would be 3, which >= max_attempts (3)
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=False, retryable=True, detail="exhausted")
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        engine.repo.transition.assert_called_once_with(
            "ActionExecution/ae1",
            "status",
            "pending",
            "dead",
            agent="service:effectd",
        )

    @pytest.mark.asyncio
    async def test_nonretryable_failure_transitions_failed(self):
        """retryable=False → failed."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=False, retryable=False, detail="bad request")
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        engine.repo.transition.assert_called_once_with(
            "ActionExecution/ae1",
            "status",
            "pending",
            "failed",
            agent="service:effectd",
        )


class TestTimeout:
    """Executor timeout is treated as retryable failure."""

    @pytest.mark.asyncio
    async def test_timeout_treated_as_retryable(self):
        """Executor sleeping longer than timeout → retryable timeout."""
        now = _frozen_now()
        action = {
            "@id": "WebhookAction/wa",
            "@type": "WebhookAction",
            "trigger": "OneShotTrigger/t1",
            "mode": "auto",
            "enabled": True,
            "executor": "webhook",
            "name": "wa",
            "timeout": "PT1S",  # 1 second timeout
        }
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        # Executor sleeps for 2s, timeout is 1s → times out
        executor = FakeExecutor(kinds=("webhook",), sleep=2.0, ok=True)
        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
        )
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
            settings=settings,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Should get a retry persistence (timeout → retryable)
        retry_calls = [c for c in tdb.insert_documents.call_args_list if "retry" in str(c)]
        assert len(retry_calls) >= 1
        updated = retry_calls[0][0][0][0]
        assert updated["result_detail"] == "timeout"

    @pytest.mark.asyncio
    async def test_executor_exception_is_retryable(self):
        """Executor raising → retryable failure."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), exception=ValueError("boom"))
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Should be retryable with detail containing the exception
        retry_calls = [c for c in tdb.insert_documents.call_args_list if "retry" in str(c)]
        assert len(retry_calls) >= 1
        updated = retry_calls[0][0][0][0]
        assert "boom" in updated.get("result_detail", "")


class TestNextAttemptAt:
    """next_attempt_at scheduling gates re-execution."""

    @pytest.mark.asyncio
    async def test_future_next_attempt_at_skipped(self):
        """Execution not yet due → untouched."""
        now = _frozen_now()
        future = now + timedelta(hours=1)
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
            "next_attempt_at": _utc_iso(future),
        }

        executor = FakeExecutor(kinds=("webhook",))
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        assert len(executor.calls) == 0
        engine.repo.transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_past_next_attempt_at_executed(self):
        """Execution past due → executed."""
        now = _frozen_now()
        past = now - timedelta(hours=1)
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
            "next_attempt_at": _utc_iso(past),
        }

        executor = FakeExecutor(kinds=("webhook",), ok=True)
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        assert len(executor.calls) == 1
        engine.repo.transition.assert_called_once()


class TestMissingExecutor:
    """Missing executor leaves execution pending, logs once per cycle per kind."""

    @pytest.mark.asyncio
    async def test_missing_executor_stays_pending(self):
        """No executor for kind → pending, warning logged."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", executor="unknown_kind")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        # Must have at least one executor for _execute to run,
        # but with a different kind so the lookup fails.
        dummy_executor = FakeExecutor(kinds=("other_kind",))
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[dummy_executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        warnings = [e for e in captured if e.get("event") == "executor_missing"]
        assert len(warnings) == 1
        assert warnings[0]["kind"] == "unknown_kind"
        # No transition, no insert
        engine.repo.transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_executor_logged_once_per_kind(self):
        """Two executions with same missing kind → one warning."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1", executor="unknown_kind")
        action2 = _action(iri="WebhookAction/wb", trigger="OneShotTrigger/t1", executor="unknown_kind")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        exec1 = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }
        exec2 = {
            "@id": "ActionExecution/ae2",
            "@type": "ActionExecution",
            "action": "WebhookAction/wb",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wb#f1",
        }

        dummy_executor = FakeExecutor(kinds=("other_kind",))
        engine, tdb = _make_engine(
            actions=[action, action2],
            firings=[firing],
            executions=[exec1, exec2],
            executors=[dummy_executor],
            now=now,
        )
        engine.repo.create = AsyncMock()

        with structlog.testing.capture_logs() as captured:
            await engine.run_cycle()

        warnings = [e for e in captured if e.get("event") == "executor_missing"]
        assert len(warnings) == 1  # throttled to once per kind per cycle


class TestOrderingAndCap:
    """Executions are processed oldest-first, capped at max_executions_per_cycle."""

    @pytest.mark.asyncio
    async def test_oldest_first_ordering(self):
        """Oldest (by @id) is executed first within the cap."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        older = _format_datetime(now - timedelta(hours=2))
        newer = _format_datetime(now - timedelta(hours=1))
        exec_old = {
            "@id": "ActionExecution/ae_old",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa_old#f1",
        }
        exec_new = {
            "@id": "ActionExecution/ae_new",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa_new#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=True)
        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
            max_executions_per_cycle=1,  # only 1 gets executed
        )
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[exec_new, exec_old],
            executors=[executor],
            now=now,
            settings=settings,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Only one execution should run, sorted by @id (deterministic)
        assert len(executor.calls) == 1
        assert executor.calls[0]["action"]["@id"] == "WebhookAction/wa"
        # With @id sort, "ae_new" < "ae_old" alphabetically
        assert executor.calls[0]["ctx"].idempotency_key == "wa_new#f1"

    @pytest.mark.asyncio
    async def test_due_execution_runs_past_not_due_in_cap(self):
        """A due execution beyond the cap position still runs when
        earlier ones are not yet due (next_attempt_at in future)."""
        now = _frozen_now()
        future = now + timedelta(hours=1)
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        # Two not-yet-due executions (first positions), one due execution
        exec_not_due_1 = {
            "@id": "ActionExecution/ae_nd1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa_nd1#f1",
            "next_attempt_at": _utc_iso(future),
        }
        exec_not_due_2 = {
            "@id": "ActionExecution/ae_nd2",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa_nd2#f1",
            "next_attempt_at": _utc_iso(future),
        }
        exec_due = {
            "@id": "ActionExecution/ae_due",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa_due#f1",
        }

        executor = FakeExecutor(kinds=("webhook",), ok=True)
        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
            max_executions_per_cycle=1,  # only 1 slot, but the due one is position 3
        )
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[exec_not_due_1, exec_not_due_2, exec_due],
            executors=[executor],
            now=now,
            settings=settings,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # The cap=1 slot should go to the due execution, not the not-due ones
        assert len(executor.calls) == 1
        assert executor.calls[0]["ctx"].idempotency_key == "wa_due#f1"


class TestProvenance:
    """Every written execution carries correct provenance."""

    @pytest.mark.asyncio
    async def test_planned_execution_has_provenance(self):
        """Planned execution has agent 'service:effectd' and Z-suffixed timestamps."""
        now = _frozen_now()
        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")

        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            now=now,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        engine.repo.create.assert_called_once()
        call_args = engine.repo.create.call_args
        doc = call_args[0][0]
        assert doc["provenance"]["agent"] == "service:effectd"
        assert doc["provenance"]["method"] == "planner"
        assert doc["provenance"]["at"].endswith("Z")


class TestAcceptanceRespx:
    """Acceptance-style test: a WebhookAction with a real httpx POST via respx."""

    @pytest.mark.asyncio
    async def test_webhook_executor_posts_and_succeeds(self):
        """One WebhookAction in auto mode + one firing → exactly one HTTP call, succeeded execution."""
        pytest.importorskip("respx")
        import httpx
        import respx

        now = _frozen_now()

        action = _action(iri="WebhookAction/wa", trigger="OneShotTrigger/t1")
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "WebhookAction/wa",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "wa#f1",
        }

        # Build a simple real-executor that POSTs via httpx
        class WebhookExecutor:
            name = "webhook"
            requires: list[ModuleRequirement] = []
            kinds = ("webhook",)

            async def execute(self, action, firing, subject, ctx):
                url = action.get("url", "http://fake.example.com/webhook")
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        json={
                            "idempotency_key": ctx.idempotency_key,
                            "firing_id": firing.get("@id"),
                        },
                    )
                return ExecutionResult(
                    ok=resp.is_success,
                    detail="ok" if resp.is_success else "fail",
                    external_ref=str(resp.status_code),
                )

        # Add url to action for the webhook executor
        action["url"] = "https://example.com/webhook"

        async with respx.MockRouter() as router:
            route = router.post("https://example.com/webhook").respond(200)

            engine, tdb = _make_engine(
                actions=[action],
                firings=[firing],
                executions=[execution],
                executors=[WebhookExecutor()],
                now=now,
            )
            engine.repo.create = AsyncMock()

            await engine.run_cycle()

            # Exactly one HTTP call
            assert route.call_count == 1

            # Transition to succeeded
            engine.repo.transition.assert_called_once_with(
                "ActionExecution/ae1",
                "status",
                "pending",
                "succeeded",
                agent="service:effectd",
            )


class TestGotifyExecutorE2E:
    """End-to-end: NotifyAction + GotifyExecutor via respx-mocked Gotify API."""

    @pytest.mark.asyncio
    async def test_notify_action_gotify_sends_and_succeeds(self):
        """NotifyAction (auto) + firing → exactly one HTTP call, succeeded with external_ref."""
        pytest.importorskip("respx")
        pytest.importorskip("firnline_ext_gotify")
        import json
        import respx

        from firnline_ext_gotify.executor import GotifyExecutor, GotifySettings

        now = _frozen_now()

        action = {
            "@id": "NotifyAction/na1",
            "@type": "NotifyAction",
            "trigger": "OneShotTrigger/t1",
            "mode": "auto",
            "enabled": True,
            "executor": "notify:gotify",
            "name": "na1",
        }
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "NotifyAction/na1",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "na1#f1",
        }

        executor = GotifyExecutor()
        executor._settings = GotifySettings(
            url="https://gotify.example.com",
            token="test-token",
            priority=5,
            timeout_seconds=10,
        )

        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
        )

        async with respx.MockRouter() as router:
            route = router.post("https://gotify.example.com/message").respond(200, json={"id": 55})

            engine, tdb = _make_engine(
                actions=[action],
                firings=[firing],
                executions=[execution],
                executors=[executor],
                now=now,
                settings=settings,
            )
            engine.repo.create = AsyncMock()

            await engine.run_cycle()

            # ── Exactly one HTTP call ──
            assert route.call_count == 1

            request = route.calls.last.request
            assert request.headers["X-Gotify-Key"] == "test-token"
            assert request.headers["X-Firnline-Idempotency-Key"] == "na1#f1"

            payload = json.loads(request.content)
            assert payload["priority"] == 5
            assert "Firnline" in payload["title"]

            # ── Transition to succeeded ──
            engine.repo.transition.assert_called_once_with(
                "ActionExecution/ae1",
                "status",
                "pending",
                "succeeded",
                agent="service:effectd",
            )

            # ── external_ref persisted ──
            success_calls = [c for c in tdb.insert_documents.call_args_list if "success" in str(c)]
            assert len(success_calls) >= 1
            updated = success_calls[-1][0][0][0]
            assert updated.get("external_ref") == "55"


class TestScheduledAfter:
    """Tests for _scheduled_after lookback filter."""

    def test_scheduled_for_in_window_returns_true(self):
        """Firing within lookback window → included."""
        window = datetime(2026, 7, 1, tzinfo=UTC)
        firing = {"@id": "Firing/f1", "scheduled_for": _utc_iso(datetime(2026, 7, 2, tzinfo=UTC))}
        assert _scheduled_after(firing, window) is True

    def test_scheduled_for_before_window_returns_false(self):
        """Firing before lookback window → excluded."""
        window = datetime(2026, 7, 10, tzinfo=UTC)
        firing = {"@id": "Firing/f1", "scheduled_for": _utc_iso(datetime(2026, 7, 2, tzinfo=UTC))}
        assert _scheduled_after(firing, window) is False

    def test_missing_scheduled_for_excluded_and_warns(self):
        """Missing scheduled_for → excluded with warning."""
        window = _frozen_now()
        firing = {"@id": "Firing/f1"}
        with structlog.testing.capture_logs() as captured:
            result = _scheduled_after(firing, window)
        assert result is False
        warnings = [e for e in captured if e.get("event") == "firing_missing_scheduled_for"]
        assert len(warnings) >= 1

    def test_unparseable_scheduled_for_excluded_and_warns(self):
        """Unparseable scheduled_for → excluded with warning."""
        window = _frozen_now()
        firing = {"@id": "Firing/f1", "scheduled_for": "not-a-date"}
        with structlog.testing.capture_logs() as captured:
            result = _scheduled_after(firing, window)
        assert result is False
        warnings = [e for e in captured if e.get("event") == "firing_unparseable_scheduled_for"]
        assert len(warnings) >= 1


def test_module_imports_with_zero_extensions():
    """All modules import successfully even with no extensions installed."""
    import importlib

    for mod in ("effectd", "effectd.main", "effectd.engine", "effectd.settings"):
        importlib.import_module(mod)


class TestDefaultNotifyExecutorFallback:
    """When action has no executor field, settings.default_notify_executor is used."""

    @pytest.mark.asyncio
    async def test_missing_executor_falls_back_to_default_notify_executor(self):
        """Action with no executor field → uses settings.default_notify_executor."""
        now = _frozen_now()
        action = {
            "@id": "NotifyAction/na1",
            "@type": "NotifyAction",
            "trigger": "OneShotTrigger/t1",
            "mode": "auto",
            "enabled": True,
            "name": "na1",
            # No "executor" field
        }
        firing = _firing(iri="TriggerFiring/f1", trigger="OneShotTrigger/t1")
        execution = {
            "@id": "ActionExecution/ae1",
            "@type": "ActionExecution",
            "action": "NotifyAction/na1",
            "firing": "TriggerFiring/f1",
            "status": "pending",
            "attempt": 0,
            "idempotency_key": "na1#f1",
        }

        # Executor provides "notify:gotify" (the default_notify_executor)
        executor = FakeExecutor(kinds=("notify:gotify",), ok=True, external_ref="ext-123")
        settings = EffectdSettings(
            tdb_db="test",
            tdb_password="pw",
            default_notify_executor="notify:gotify",
        )
        engine, tdb = _make_engine(
            actions=[action],
            firings=[firing],
            executions=[execution],
            executors=[executor],
            now=now,
            settings=settings,
        )
        engine.repo.create = AsyncMock()

        await engine.run_cycle()

        # Executor was called (default_notify_executor matched)
        assert len(executor.calls) == 1
        engine.repo.transition.assert_called_once_with(
            "ActionExecution/ae1",
            "status",
            "pending",
            "succeeded",
            agent="service:effectd",
        )
