"""Tests for plugin host behaviour — kind collisions, source collisions,
prompt construction, kind dispatch, discovery strictness, and requirement checking.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal
from unittest.mock import AsyncMock

import structlog
import pytest
from pydantic import BaseModel

from ingestd.extraction import (
    build_extraction_context,
    parse_extraction,
)
from ingestd.main import _discover_extractor_plugins_async, _discover_source_plugins_async
from firnline_core.plugins import (
    DiscoveryResult,
    ModuleRequirement,
    select_plugins,
)

UTC = timezone.utc

# Logger for tests that call discovery helpers
_test_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers — minimal plugin stubs
# ---------------------------------------------------------------------------


class _TestTaskProposal(BaseModel):
    kind: Literal["task"] = "task"
    name: str
    description: str | None = None


class _TestEventProposal(BaseModel):
    kind: Literal["event"] = "event"
    name: str
    date: datetime | None = None


class _PluginA:
    name = "plugin_a"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="a", range=">=1.0.0")]

    def proposal_models(self):
        return [_TestTaskProposal]

    def prompt_snippet(self):
        return "\n### Plugin A\nExtract tasks from text."

    async def linking_context(self, tdb, *, index=None, branch=""):
        return ""

    async def build_documents(self, proposal, ctx):
        return [{"@type": "Task", "name": proposal.name}]


class _PluginB:
    name = "plugin_b"
    requires: list[ModuleRequirement] = []

    def proposal_models(self):
        return [_TestEventProposal]

    def prompt_snippet(self):
        return "\n### Plugin B\nExtract events from text."

    async def linking_context(self, tdb, *, index=None, branch=""):
        return ""

    async def build_documents(self, proposal, ctx):
        return [{"@type": "Event", "name": proposal.name}]


class _PluginCollision:
    """Declares the same 'task' kind as PluginA → should be rejected."""

    name = "plugin_collision"
    requires: list[ModuleRequirement] = []

    def proposal_models(self):
        return [_TestTaskProposal]

    def prompt_snippet(self):
        return "\n### Collision\nDuplicate."

    async def linking_context(self, tdb, *, index=None, branch=""):
        return ""

    async def build_documents(self, proposal, ctx):
        return []


# ---------------------------------------------------------------------------
# 1. Kind collision is fatal
# ---------------------------------------------------------------------------


class TestKindCollision:
    def test_two_plugins_same_kind_raises(self):
        """Two plugins both declaring 'task' kind → ValueError."""
        with pytest.raises(ValueError, match="Kind collision.*'task'"):
            build_extraction_context([_PluginA(), _PluginCollision()])

    def test_no_collision_when_kinds_differ(self):
        """Two plugins with different kinds → no error, both mapped."""
        ctx = build_extraction_context([_PluginA(), _PluginB()])
        assert set(ctx.kind_to_model.keys()) == {"task", "event"}
        assert set(ctx.kind_to_plugin.keys()) == {"task", "event"}

    def test_single_plugin_works(self):
        ctx = build_extraction_context([_PluginA()])
        assert list(ctx.kind_to_model.keys()) == ["task"]


# ---------------------------------------------------------------------------
# 2. (document_type, ready_status) collision is fatal
# ---------------------------------------------------------------------------


class _SourceA:
    name = "source_a"
    document_type = "Captured"
    ready_status = "new"
    done_status = "processed"
    failed_status = "failed"
    requires: list[ModuleRequirement] = []

    def text(self, doc):
        return doc.get("content", "")

    def reference_time(self, doc):
        from datetime import datetime, timezone
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class _SourceB:
    name = "source_b"
    document_type = "Captured"
    ready_status = "new"  # same as _SourceA → collision
    done_status = "processed"
    failed_status = "failed"
    requires: list[ModuleRequirement] = []

    def text(self, doc):
        return doc.get("content", "")

    def reference_time(self, doc):
        from datetime import datetime, timezone
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class _SourceDifferent:
    name = "source_diff"
    document_type = "Captured"
    ready_status = "transcribed"
    done_status = "processed"
    failed_status = "failed"
    requires: list[ModuleRequirement] = []

    def text(self, doc):
        return doc.get("transcription", "")

    def reference_time(self, doc):
        from datetime import datetime, timezone
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class TestSourceCollision:
    @pytest.mark.asyncio
    async def test_duplicate_doc_type_and_status_raises(self, monkeypatch):
        """Two sources with same (document_type, ready_status) → RuntimeError.

        Exercises the real _discover_source_plugins_async via monkeypatch
        on firnline_core.plugins.discover_plugins and check_requirements.
        """
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        # PluginHost calls discover_plugins from firnline_core.plugins
        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(
                active=[("a", _SourceA()), ("b", _SourceB())]
            ),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []
        monkeypatch.setattr(
            "firnline_core.plugins.check_requirements",
            _noop_check,
        )

        with pytest.raises(RuntimeError, match="collision"):
            await _discover_source_plugins_async(tdb, "main", _test_logger)

    @pytest.mark.asyncio
    async def test_different_doc_types_no_collision(self, monkeypatch):
        """Two sources with different (document_type, ready_status) → OK."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(
                active=[("a", _SourceA()), ("b", _SourceDifferent())]
            ),
        )

        async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
            return []
        monkeypatch.setattr(
            "firnline_core.plugins.check_requirements",
            _noop_check,
        )

        sources = await _discover_source_plugins_async(tdb, "main", _test_logger)
        assert len(sources) == 2


# ---------------------------------------------------------------------------
# 3. Broken entry points → fatal
# ---------------------------------------------------------------------------


class TestBrokenEntryPoints:
    @pytest.mark.asyncio
    async def test_broken_extractor_entry_point_fatal(self, monkeypatch):
        """Broken entry point in extractor group → RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(
                failed=[("broken_ext", "ImportError: no module 'nope'")]
            ),
        )

        with pytest.raises(RuntimeError, match="failed to load"):
            await _discover_extractor_plugins_async(tdb, "main", _test_logger)

    @pytest.mark.asyncio
    async def test_broken_source_entry_point_fatal(self, monkeypatch):
        """Broken entry point in source group → RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(
                failed=[("broken_src", "ValueError: bad")]
            ),
        )

        with pytest.raises(RuntimeError, match="failed to load"):
            await _discover_source_plugins_async(tdb, "main", _test_logger)


# ---------------------------------------------------------------------------
# 4. Zero active extractors → fatal
# ---------------------------------------------------------------------------


class TestZeroActiveExtractors:
    @pytest.mark.asyncio
    async def test_zero_active_extractors_fatal(self, monkeypatch):
        """No active extractor plugins after selection → RuntimeError."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        class _PluginWithReq:
            name = "plugin_with_req"
            requires = [ModuleRequirement(name="x", range=">=1.0.0")]

            def proposal_models(self):
                return [_TestTaskProposal]

            def prompt_snippet(self):
                return ""

            async def linking_context(self, tdb, *, index=None, branch=""):
                return ""

            async def build_documents(self, proposal, ctx):
                return []

        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            lambda group: DiscoveryResult(
                active=[("a", _PluginWithReq()), ("b", _PluginWithReq())]
            ),
        )

        async def _all_fail(tdb, reqs, branch="main", registry=None, required_classes=None):
            violations: list[str] = []
            for req in reqs:
                violations.append(f"module '{req.name}' not installed")
            return violations
        monkeypatch.setattr(
            "firnline_core.plugins.check_requirements",
            _all_fail,
        )

        with pytest.raises(RuntimeError, match="No active"):
            await _discover_extractor_plugins_async(tdb, "main", _test_logger)


# ---------------------------------------------------------------------------
# 5. System prompt contains all plugin snippets + JSON-like schema
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def test_prompt_contains_core_rules(self):
        """System prompt includes core extraction hygiene rules."""
        ctx = build_extraction_context([_PluginA(), _PluginB()])
        assert "extraction assistant" in ctx.system_prompt.lower()
        assert "do not translate" in ctx.system_prompt.lower()
        assert "Today is" not in ctx.system_prompt
        assert "Europe/Zurich" not in ctx.system_prompt

    def test_prompt_contains_all_plugin_snippets(self):
        """Each plugin's prompt_snippet() appears in the system prompt."""
        ctx = build_extraction_context([_PluginA(), _PluginB()])
        assert "Plugin A" in ctx.system_prompt
        assert "Extract tasks" in ctx.system_prompt
        assert "Plugin B" in ctx.system_prompt
        assert "Extract events" in ctx.system_prompt

    def test_prompt_contains_json_schema_reference(self):
        """Prompt references JSON output format."""
        ctx = build_extraction_context([_PluginA()])
        assert "json" in ctx.system_prompt.lower()
        assert "Plugin A" in ctx.system_prompt

    def test_prompt_contains_actual_schema_content(self):
        """Prompt from PlanningPlugin contains known field names from each proposal model."""
        try:
            from firnline_ext_time_management.extract import TimeManagementPlugin
        except ImportError:
            pytest.skip("extension pending kernel migration")
        ctx = build_extraction_context([TimeManagementPlugin()])
        prompt = ctx.system_prompt
        assert "estimated_duration" in prompt
        assert "location_name" in prompt
        assert "email" in prompt
        assert "kind" in prompt
        assert "proposals" in prompt


# ---------------------------------------------------------------------------
# 6. Parse dispatch by kind: unknown-kind item collected as error
# ---------------------------------------------------------------------------


class TestParseDispatch:
    def test_known_kinds_dispatched_correctly(self):
        """Items with known kinds are validated against the right model."""
        kind_map = {"task": _TestTaskProposal, "event": _TestEventProposal}
        raw = json.dumps(
            {
                "proposals": [
                    {"kind": "task", "name": "Buy milk"},
                    {"kind": "event", "name": "Meeting", "date": "2026-07-10T09:00:00Z"},
                ],
                "reasoning": "test",
                "confidence": 0.9,
            }
        )
        result = parse_extraction(raw, kind_to_model=kind_map)
        assert len(result.proposals) == 2
        assert isinstance(result.proposals[0], _TestTaskProposal)
        assert isinstance(result.proposals[1], _TestEventProposal)
        assert result.proposals[0].name == "Buy milk"
        assert result.proposals[1].name == "Meeting"

    def test_unknown_kind_skipped_with_error(self):
        """Unknown kind → item skipped, parse errors logged, other items survive."""
        kind_map = {"task": _TestTaskProposal}
        raw = json.dumps(
            {
                "proposals": [
                    {"kind": "task", "name": "Valid"},
                    {"kind": "unknown_xyz", "name": "Should be skipped"},
                    {"kind": "task", "name": "Also valid"},
                ],
                "reasoning": "test",
                "confidence": 0.9,
            }
        )
        result = parse_extraction(raw, kind_to_model=kind_map)
        assert len(result.proposals) == 2
        assert result.proposals[0].name == "Valid"
        assert result.proposals[1].name == "Also valid"

    def test_invalid_item_for_known_kind_collected_as_error(self):
        """Item with correct kind but invalid fields → skipped, others survive."""
        kind_map = {"task": _TestTaskProposal}
        raw = json.dumps(
            {
                "proposals": [
                    {"kind": "task"},
                    {"kind": "task", "name": "Good"},
                ],
                "reasoning": "test",
                "confidence": 0.9,
            }
        )
        result = parse_extraction(raw, kind_to_model=kind_map)
        assert len(result.proposals) == 1
        assert result.proposals[0].name == "Good"

    def test_bare_array_with_known_kinds(self):
        """Bare JSON array with items dispatched by kind."""
        kind_map = {"task": _TestTaskProposal, "event": _TestEventProposal}
        raw = json.dumps(
            [
                {"kind": "task", "name": "Task 1"},
                {"kind": "event", "name": "Event 1", "date": None},
            ]
        )
        result = parse_extraction(raw, kind_to_model=kind_map)
        assert len(result.proposals) == 2
        assert result.confidence == 0.7
        assert isinstance(result.proposals[0], _TestTaskProposal)

    def test_non_dict_proposal_skipped(self):
        """Non-dict items in proposals array are skipped."""
        kind_map = {"task": _TestTaskProposal}
        raw = json.dumps(
            {
                "proposals": [
                    "not a dict",
                    {"kind": "task", "name": "Good"},
                ],
                "reasoning": "test",
                "confidence": 0.5,
            }
        )
        result = parse_extraction(raw, kind_to_model=kind_map)
        assert len(result.proposals) == 1
        assert result.proposals[0].name == "Good"


# ---------------------------------------------------------------------------
# 7. Source plugin skipped when requirements unmet
# ---------------------------------------------------------------------------


class _SourceWithRequirement:
    name = "source_with_req"
    document_type = "Captured"
    ready_status = "new"
    done_status = "processed"
    failed_status = "failed"
    requires = [ModuleRequirement(name="missing_module", range=">=2.0.0")]

    def text(self, doc):
        return doc.get("content", "")

    def reference_time(self, doc):
        from datetime import datetime, timezone
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class _SourceNoRequirement:
    name = "source_no_req"
    document_type = "Captured"
    ready_status = "transcribed"
    done_status = "processed"
    failed_status = "failed"
    requires: list[ModuleRequirement] = []

    def text(self, doc):
        return doc.get("transcription", "")

    def reference_time(self, doc):
        from datetime import datetime, timezone
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class TestSourceRequirementSkipping:
    @pytest.mark.asyncio
    async def test_source_with_unmet_requirement_is_skipped(self):
        """Source with unmet module requirement → skipped, others active."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        discovered = DiscoveryResult(
            active=[
                ("with_req", _SourceWithRequirement()),
                ("no_req", _SourceNoRequirement()),
            ]
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
            result = await select_plugins(tdb, discovered, strict=False)
            skipped_names = [n for n, _ in result.skipped]
            active_names = [n for n, _ in result.active]

            assert "with_req" in skipped_names
            assert "no_req" in active_names
            assert len(result.active) == 1
        finally:
            plug_mod.check_requirements = _orig_check


# ---------------------------------------------------------------------------
# 8. strict_plugins — skipped plugin + strict → startup fails; non-strict starts
# ---------------------------------------------------------------------------


class TestStrictPlugins:
    @pytest.mark.asyncio
    async def test_strict_source_skipped_raises(self, monkeypatch):
        """strict=True: skipped source plugin raises RuntimeError via select_plugins."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        discovered = DiscoveryResult(
            active=[("with_req", _SourceWithRequirement())]
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
            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                await select_plugins(tdb, discovered, strict=True)
        finally:
            plug_mod.check_requirements = _orig_check

    @pytest.mark.asyncio
    async def test_nonstrict_source_skipped_allows_start(self, monkeypatch):
        """strict=False: skipped source is just skipped, no exception."""
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        discovered = DiscoveryResult(
            active=[
                ("with_req", _SourceWithRequirement()),
                ("no_req", _SourceNoRequirement()),
            ]
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
            result = await select_plugins(tdb, discovered, strict=False)
            assert len(result.skipped) == 1
            assert len(result.active) == 1
        finally:
            plug_mod.check_requirements = _orig_check
