"""Tests for evaluator plugin discovery via PluginHost — collisions,
broken entry points, zero-evaluator warning, skipped-plugins logging,
protocol validation, and strict propagation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from triggerd.main import _discover_evaluator_plugins_async
from firnline_core.plugins import DiscoveryResult, ModuleRequirement


# ---------------------------------------------------------------------------
# Helpers — minimal evaluator plugin stubs matching TriggerEvaluator protocol
# ---------------------------------------------------------------------------


class _EvalA:
    name = "eval_a"
    trigger_types = ("TriggerDaily",)
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalB:
    name = "eval_b"
    trigger_types = ("TriggerDaily",)  # same as _EvalA → collision
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalNoCollision:
    name = "eval_no_collision"
    trigger_types = ("TriggerOnce",)
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalPartialOverlap:
    name = "eval_partial"
    trigger_types = ("A", "B")
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalOtherPartial:
    name = "eval_other_partial"
    trigger_types = ("B", "C")
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalWithReq:
    name = "eval_with_req"
    trigger_types = ("TriggerWeekly",)
    requires = [ModuleRequirement(name="missing_module", range=">=2.0.0")]

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalMissingTriggerTypes:
    """Missing trigger_types — filtered by protocol validation (attribute check)."""

    name = "eval_missing_attrs"
    requires: list[ModuleRequirement] = []

    async def occurrences(self, trigger, *, window_start, window_end, ctx):
        return []


class _EvalNonCallable:
    name = "eval_non_callable"
    trigger_types = ("TriggerX",)
    occurrences = "not callable"
    requires: list[ModuleRequirement] = []


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
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalA()), ("b", _EvalB())]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with pytest.raises(RuntimeError, match="collision"):
            await _discover_evaluator_plugins_async(tdb, "main", None)

    @pytest.mark.asyncio
    async def test_no_collision_when_types_differ(self, monkeypatch):
        """Two evaluators with different trigger_types → OK."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalA()), ("b", _EvalNoCollision())]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        evaluators = await _discover_evaluator_plugins_async(tdb, "main", None)
        assert len(evaluators) == 2

    @pytest.mark.asyncio
    async def test_partial_overlap_collision_raises(self, monkeypatch):
        """Evaluators with trigger_types ("A","B") and ("B","C") → RuntimeError on "B"."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("a", _EvalPartialOverlap()), ("b", _EvalOtherPartial())]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        with pytest.raises(RuntimeError, match="collision"):
            await _discover_evaluator_plugins_async(tdb, "main", None)


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
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(failed=[("broken_eval", "ImportError: no module 'nope'")]),
        )

        with pytest.raises(RuntimeError, match="failed to load"):
            await _discover_evaluator_plugins_async(tdb, "main", None)


# ---------------------------------------------------------------------------
# 3. Zero evaluators → warning, not fatal (behavior check)
# ---------------------------------------------------------------------------


class TestZeroEvaluators:
    @pytest.mark.asyncio
    async def test_zero_active_evaluators_returns_empty_no_error(self, monkeypatch):
        """No active evaluator plugins → empty list returned, no RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        evaluators = await _discover_evaluator_plugins_async(tdb, "main", None)
        assert evaluators == []


# ---------------------------------------------------------------------------
# 4. Skipped-requirements plugin → filtered
# ---------------------------------------------------------------------------


class TestSkippedPlugins:
    @pytest.mark.asyncio
    async def test_unmet_requirement_skipped(self, monkeypatch):
        """Evaluator with unmet requirement → skipped, others active."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("with_req", _EvalWithReq()), ("ok", _EvalA())]),
        )

        import firnline_core.plugins as plug_mod

        _orig_check = plug_mod.check_requirements

        async def _check(tdb, reqs, branch="main", registry=None, required_classes=None):
            violations: list[str] = []
            for req in reqs:
                violations.append(f"module '{req.name}' not installed")
            return violations

        plug_mod.check_requirements = _check
        try:
            evaluators = await _discover_evaluator_plugins_async(tdb, "main", None)
            # _EvalWithReq should be skipped, _EvalA should be active
            names = [e.name for e in evaluators]
            assert "eval_a" in names
            assert "eval_with_req" not in names
        finally:
            plug_mod.check_requirements = _orig_check


# ---------------------------------------------------------------------------
# 5. Protocol validation (replaces duck-typing checks)
# ---------------------------------------------------------------------------


class TestProtocolValidation:
    @pytest.mark.asyncio
    async def test_missing_trigger_types_is_skipped(self, monkeypatch):
        """Plugin missing trigger_types → filtered by protocol validation."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("bad", _EvalMissingTriggerTypes())]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        evaluators = await _discover_evaluator_plugins_async(tdb, "main", None)
        assert evaluators == []

    @pytest.mark.asyncio
    async def test_non_callable_occurrences_is_skipped(self, monkeypatch):
        """Plugin with non-callable occurrences → filtered by protocol validation."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("bad", _EvalNonCallable())]),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []

        monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

        evaluators = await _discover_evaluator_plugins_async(tdb, "main", None)
        assert evaluators == []


# ---------------------------------------------------------------------------
# 6. Strict propagation
# ---------------------------------------------------------------------------


class TestStrictPlugins:
    @pytest.mark.asyncio
    async def test_strict_skipped_raises(self, monkeypatch):
        """strict=True: skipped evaluator raises RuntimeError via PluginHost."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(active=[("with_req", _EvalWithReq())]),
        )

        import firnline_core.plugins as plug_mod

        _orig_check = plug_mod.check_requirements

        async def _check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return ["module 'missing_module' not installed"]

        plug_mod.check_requirements = _check
        try:
            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                await _discover_evaluator_plugins_async(tdb, "main", None, strict=True)
        finally:
            plug_mod.check_requirements = _orig_check
