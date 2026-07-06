"""Tests for evaluator plugin discovery — collisions, broken entry points,
zero-evaluator warning, skipped-plugins logging, duck-type filtering,
and strict propagation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import structlog
import pytest

from triggerd.main import _discover_evaluator_plugins_async
from firnline_core.plugins import DiscoveryResult, ModuleRequirement

_test_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers — minimal evaluator plugin stubs
# ---------------------------------------------------------------------------


class _EvalA:
    name = "eval_a"
    trigger_types = ("TriggerDaily",)
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalB:
    name = "eval_b"
    trigger_types = ("TriggerDaily",)  # same as _EvalA → collision
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalNoCollision:
    name = "eval_no_collision"
    trigger_types = ("TriggerOnce",)
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalPartialOverlap:
    name = "eval_partial"
    trigger_types = ("A", "B")
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalOtherPartial:
    name = "eval_other_partial"
    trigger_types = ("B", "C")
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalWithReq:
    name = "eval_with_req"
    trigger_types = ("TriggerWeekly",)
    requires = [ModuleRequirement(name="missing_module", range=">=2.0.0")]

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalMissingAttrs:
    """Missing trigger_types — should be filtered out in duck-typing."""

    name = "eval_missing_attrs"
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


class _EvalNonCallable:
    name = "eval_non_callable"
    trigger_types = ("TriggerX",)
    occurrences = "not callable"
    requires: list[ModuleRequirement] = []


class _EvalNonListTypes:
    name = "eval_non_list_types"
    trigger_types = "TriggerX"  # not a tuple/list
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, tdb, settings):
        return []


# ---------------------------------------------------------------------------
# 1. trigger_types collision → fatal
# ---------------------------------------------------------------------------


class TestTriggerTypeCollision:
    @pytest.mark.asyncio
    async def test_collision_raises(self, monkeypatch):
        """Two evaluators claiming the same @type → RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalA()), ("b", _EvalB())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with pytest.raises(RuntimeError, match="collision"):
            await _discover_evaluator_plugins_async(tdb, "main", _test_logger)

    @pytest.mark.asyncio
    async def test_no_collision_when_types_differ(self, monkeypatch):
        """Two evaluators with different trigger_types → OK."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalA()), ("b", _EvalNoCollision())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)
        assert len(evaluators) == 2

    @pytest.mark.asyncio
    async def test_partial_overlap_collision_raises(self, monkeypatch):
        """Evaluators with trigger_types ("A","B") and ("B","C") → RuntimeError on "B"."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalPartialOverlap()), ("b", _EvalOtherPartial())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with pytest.raises(RuntimeError, match="collision"):
            await _discover_evaluator_plugins_async(tdb, "main", _test_logger)


# ---------------------------------------------------------------------------
# 2. Broken entry points → fatal
# ---------------------------------------------------------------------------


class TestBrokenEntryPoints:
    @pytest.mark.asyncio
    async def test_broken_entry_point_fatal(self, monkeypatch):
        """Broken entry point in evaluator group → RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(failed=[("broken_eval", "ImportError: no module 'nope'")]),
        )

        with pytest.raises(RuntimeError, match="failed to load"):
            await _discover_evaluator_plugins_async(tdb, "main", _test_logger)


# ---------------------------------------------------------------------------
# 3. Zero evaluators → warning, not fatal
# ---------------------------------------------------------------------------


class TestZeroEvaluators:
    @pytest.mark.asyncio
    async def test_zero_active_evaluators_warns_not_crashes(self, monkeypatch):
        """No active evaluator plugins → warning logged, empty list returned, no RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with structlog.testing.capture_logs() as captured:
            evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)

        assert evaluators == []

        warning_events = [e for e in captured if e.get("event") == "no_active_evaluator_plugins"]
        assert len(warning_events) == 1


# ---------------------------------------------------------------------------
# 4. Skipped-requirements plugin logged
# ---------------------------------------------------------------------------


class TestSkippedPlugins:
    @pytest.mark.asyncio
    async def test_unmet_requirement_skipped_and_logged(self, monkeypatch):
        """Evaluator with unmet requirement → skipped, others active, warning logged."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("with_req", _EvalWithReq()), ("ok", _EvalA())]),
        )

        import firnline_core.plugins as plug_mod

        _orig_check = plug_mod.check_requirements

        async def _check(tdb, reqs, branch="main"):
            violations: list[str] = []
            for req in reqs:
                violations.append(f"module '{req.name}' not installed")
            return violations

        plug_mod.check_requirements = _check
        try:
            with structlog.testing.capture_logs() as captured:
                evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)
            # _EvalWithReq should be skipped, _EvalA should be active
            names = [e.name for e in evaluators]
            assert "eval_a" in names
            assert "eval_with_req" not in names

            skip_events = [e for e in captured if e.get("event") == "evaluator_plugin_skipped"]
            assert len(skip_events) == 1
            assert skip_events[0]["plugin"] == "with_req"
        finally:
            plug_mod.check_requirements = _orig_check


# ---------------------------------------------------------------------------
# 5. Duck-typing: invalid evaluators filtered with warnings
# ---------------------------------------------------------------------------


class TestDuckTypeFiltering:
    @pytest.mark.asyncio
    async def test_missing_attrs_rejected_with_warning(self, monkeypatch):
        """Plugin missing trigger_types → filtered, warning logged."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("bad", _EvalMissingAttrs())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with structlog.testing.capture_logs() as captured:
            evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)

        assert evaluators == []

        warn_events = [e for e in captured if e.get("event") == "plugin_not_evaluator"]
        assert len(warn_events) == 1
        assert warn_events[0]["name"] == "bad"

    @pytest.mark.asyncio
    async def test_non_list_trigger_types_rejected_with_warning(self, monkeypatch):
        """Plugin with non-list trigger_types → filtered, warning logged."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("bad", _EvalNonListTypes())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with structlog.testing.capture_logs() as captured:
            evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)

        assert evaluators == []

        warn_events = [e for e in captured if e.get("event") == "plugin_bad_trigger_types"]
        assert len(warn_events) == 1
        assert warn_events[0]["name"] == "bad"

    @pytest.mark.asyncio
    async def test_non_callable_occurrences_rejected_with_warning(self, monkeypatch):
        """Plugin with non-callable occurrences → filtered, warning logged."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("bad", _EvalNonCallable())]),
        )

        async def _noop_check(tdb, reqs, branch="main"):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with structlog.testing.capture_logs() as captured:
            evaluators = await _discover_evaluator_plugins_async(tdb, "main", _test_logger)

        assert evaluators == []

        warn_events = [e for e in captured if e.get("event") == "plugin_bad_occurrences"]
        assert len(warn_events) == 1
        assert warn_events[0]["name"] == "bad"


# ---------------------------------------------------------------------------
# 6. Strict propagation
# ---------------------------------------------------------------------------


class TestStrictPlugins:
    @pytest.mark.asyncio
    async def test_strict_skipped_raises(self, monkeypatch):
        """strict=True: skipped evaluator raises RuntimeError via select_plugins."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "triggerd.main.discover_plugins",
            lambda group: DiscoveryResult(active=[("with_req", _EvalWithReq())]),
        )

        import firnline_core.plugins as plug_mod

        _orig_check = plug_mod.check_requirements

        async def _check(tdb, reqs, branch="main"):
            return ["module 'missing_module' not installed"]

        plug_mod.check_requirements = _check
        try:
            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                await _discover_evaluator_plugins_async(tdb, "main", _test_logger, strict=True)
        finally:
            plug_mod.check_requirements = _orig_check
