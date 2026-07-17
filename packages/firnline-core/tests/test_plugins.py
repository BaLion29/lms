"""Tests for firnline_core.plugins — requirement checking, discovery, selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from firnline_core.plugins import (
    ActionContext,
    ActionExecutor,
    BuildContext,
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    DiscoveryResult,
    EntityIndex,
    ExecutionResult,
    HostPolicy,
    ModuleRequirement,
    PluginHost,
    check_requirements,
    discover_plugins,
    select_plugins,
    validate_plugin,
)
from firnline_core.tdb import TdbError


# ---------------------------------------------------------------------------
# check_requirements
# ---------------------------------------------------------------------------


class TestCheckRequirements:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    async def test_all_satisfied(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "2.0.0"},
            {"name": "planning", "version": "1.5.0"},
        ]
        reqs = [
            ModuleRequirement(name="capture", range=">=1.0.0"),
            ModuleRequirement(name="planning", range=">=1.0.0 <2.0.0"),
        ]
        violations = await check_requirements(tdb, reqs)
        assert violations == []

    async def test_missing_module(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        reqs = [ModuleRequirement(name="nonexistent", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert violations == ["module 'nonexistent' not installed"]

    async def test_out_of_range(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "planning", "version": "1.0.0"},
        ]
        reqs = [ModuleRequirement(name="planning", range=">=2.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert violations == ["module 'planning' 1.0.0 does not satisfy '>=2.0.0'"]

    async def test_malformed_range(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        reqs = [ModuleRequirement(name="xyz", range="not-a-range")]
        violations = await check_requirements(tdb, reqs)
        assert violations == ["module 'xyz' has malformed range 'not-a-range'"]

    async def test_registry_unavailable(self, tdb: AsyncMock) -> None:
        tdb.get_documents.side_effect = TdbError(400, "no such class")
        reqs = [ModuleRequirement(name="capture", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert len(violations) == 1
        assert "schema module registry not available" in violations[0]
        assert "400" in violations[0]

    async def test_unparseable_registry_version(self, tdb: AsyncMock) -> None:
        """Corrupted registry version emits a distinct violation."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "not.a.version"},
        ]
        reqs = [ModuleRequirement(name="capture", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert any("has unparseable version" in v for v in violations)

    async def test_uses_provided_branch(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        reqs = [ModuleRequirement(name="capture", range=">=1.0.0")]
        await check_requirements(tdb, reqs, branch="staging")
        tdb.get_documents.assert_called_once_with("SchemaModule", branch="staging")

    async def test_multiple_violations(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "planning", "version": "1.0.0"},
        ]
        reqs = [
            ModuleRequirement(name="planning", range=">=2.0.0"),
            ModuleRequirement(name="demo", range=">=1.0.0"),
            ModuleRequirement(name="broken", range="!!"),
        ]
        violations = await check_requirements(tdb, reqs)
        assert len(violations) == 3
        assert any("does not satisfy" in v for v in violations)
        assert any("not installed" in v for v in violations)
        assert any("malformed range" in v for v in violations)


# ---------------------------------------------------------------------------
# select_plugins
# ---------------------------------------------------------------------------


class TestSelectPlugins:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    def _plugin(self, name: str, requires: list[ModuleRequirement] | None = None) -> object:
        """Create a minimal plugin-like object."""
        plugin = type(f"Plugin_{name}", (), {})()
        plugin.name = name  # type: ignore[attr-defined]
        plugin.requires = requires or []  # type: ignore[attr-defined]
        return plugin

    async def test_all_active(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [{"name": "capture", "version": "1.0.0"}]
        p1 = self._plugin("p1", [ModuleRequirement(name="capture", range=">=1.0.0")])
        p2 = self._plugin("p2", [])
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 2
        assert sel.skipped == []

    async def test_skip_unmet(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        p1 = self._plugin("p1", [ModuleRequirement(name="capture", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert sel.active == []
        assert len(sel.skipped) == 1
        assert sel.skipped[0][0] == "p1"
        assert "not installed" in sel.skipped[0][1][0]

    async def test_strict_raises_on_skip(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        p1 = self._plugin("p1", [ModuleRequirement(name="capture", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        with pytest.raises(RuntimeError, match="Strict plugin mode"):
            await select_plugins(tdb, discovered, strict=True)

    async def test_strict_raises_on_discovery_failure(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        discovered = DiscoveryResult(active=[], failed=[("bad_plugin", "ImportError: boom")])
        with pytest.raises(RuntimeError, match="Strict plugin mode"):
            await select_plugins(tdb, discovered, strict=True)


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class FakeEntryPoint:
    """Minimal fake matching the importlib.metadata.EntryPoint protocol."""

    def __init__(self, name: str, load_fn) -> None:
        self.name = name
        self._load_fn = load_fn

    def load(self):
        return self._load_fn()


class TestDiscoverPlugins:
    def test_successful_discovery(self) -> None:
        obj = object()
        eps = [FakeEntryPoint("test_plugin", lambda: obj)]
        with patch("importlib.metadata.entry_points", return_value=eps):
            result = discover_plugins("firnline.test.group")
        assert len(result.active) == 1
        assert result.active[0] == ("test_plugin", obj)
        assert result.failed == []

    def test_failing_import_isolation(self) -> None:
        def _fail():
            raise ImportError("cannot import plugin")

        eps = [FakeEntryPoint("bad_plugin", _fail)]
        with patch("importlib.metadata.entry_points", return_value=eps):
            result = discover_plugins("firnline.test.group")
        assert result.active == []
        assert len(result.failed) == 1
        assert result.failed[0][0] == "bad_plugin"
        assert "ImportError" in result.failed[0][1]


# ---------------------------------------------------------------------------
# BuildContext
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_default_now_is_utc_now(self) -> None:
        from datetime import datetime, timezone

        ctx = BuildContext(tdb=None, captured_iri="test/1")
        now = ctx.now()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None  # default utc_now is tz-aware UTC
        assert now.utcoffset() == timezone.utc.utcoffset(None)

    def test_custom_now(self) -> None:
        from datetime import datetime, timezone

        fixed = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ctx = BuildContext(tdb=None, captured_iri="test/1", now=lambda: fixed)
        assert ctx.now() == fixed


# ---------------------------------------------------------------------------
# CaptureHandler / IngestSourcePlugin protocol conformance
# ---------------------------------------------------------------------------


class TestCaptureHandlerProtocol:
    """A minimal class should satisfy the CaptureHandler Protocol."""

    def test_isinstance_check(self) -> None:
        class NoteHandler:
            name = "note_handler"
            kinds = ("note",)
            requires: list[ModuleRequirement] = []

            def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
                return "doc/123"

        handler = NoteHandler()
        # @runtime_checkable verifies the handle method exists
        assert isinstance(handler, CaptureHandler)

    def test_structural_usage(self) -> None:
        class FileHandler:
            name = "file_handler"
            kinds = ("file", "image")
            requires: list[ModuleRequirement] = []

            def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
                assert payload.kind in self.kinds
                return f"doc/{payload.kind}/1"

        handler = FileHandler()
        payload = CapturePayload(kind="file", text="hello")
        ctx = CaptureContext(tdb=None, blob_store=None, logger=None)
        doc_id = handler.handle(payload, ctx)
        assert doc_id == "doc/file/1"


class TestIngestSourcePluginProtocol:
    """A minimal class should satisfy the IngestSourcePlugin Protocol."""

    def test_structural_usage(self) -> None:
        from datetime import datetime, timezone

        class RssIngestSource:
            name = "rss_source"
            requires: list[ModuleRequirement] = []
            document_type = "RssFeedItem"
            ready_status = "ready"
            done_status = "done"
            failed_status = "failed"

            def text(self, doc: dict) -> str:
                return doc.get("body", "")

            def reference_time(self, doc: dict) -> datetime:
                return datetime(2025, 1, 1, tzinfo=timezone.utc)

        source = RssIngestSource()
        # Verify all expected attributes are present
        assert source.name == "rss_source"
        assert source.document_type == "RssFeedItem"
        assert source.ready_status == "ready"
        assert source.done_status == "done"
        assert source.failed_status == "failed"
        assert source.requires == []

        doc = {"body": "extracted text"}
        assert source.text(doc) == "extracted text"

    def test_requires_with_module_requirements(self) -> None:
        from datetime import datetime, timezone

        class MySource:
            name = "my_source"
            requires = [ModuleRequirement(name="capture", range=">=1.0.0")]
            document_type = "MyDoc"
            ready_status = "new"
            done_status = "completed"
            failed_status = "error"

            def text(self, doc: dict) -> str:
                return str(doc)

            def reference_time(self, doc: dict) -> datetime:
                return datetime(2025, 1, 1, tzinfo=timezone.utc)

        source = MySource()
        assert len(source.requires) == 1
        assert source.requires[0].name == "capture"


# ---------------------------------------------------------------------------
# EntityIndex — generic + backward compat
# ---------------------------------------------------------------------------


class TestEntityIndex:
    def test_register_and_lookup(self) -> None:
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/1")
        index.register("Person", "Bob Müller", "Person/2")
        assert index.lookup("Person", "anna meier") == "Person/1"
        assert index.lookup("Person", "BOB MÜLLER") == "Person/2"
        assert index.lookup("Person", "unknown") is None
        assert index.lookup("Location", "any") is None

    def test_names_and_classes(self) -> None:
        index = EntityIndex()
        index.register("Person", "Anna", "Person/1")
        index.register("Person", "Bob", "Person/2")
        index.register("Location", "Zürich", "Location/1")
        assert index.names("Person") == [("Anna", "Person/1"), ("Bob", "Person/2")]
        assert index.names("Location") == [("Zürich", "Location/1")]
        assert sorted(index.classes()) == ["Location", "Person"]


# ---------------------------------------------------------------------------
# validate_plugin
# ---------------------------------------------------------------------------


class TestValidatePlugin:
    def test_valid_plugin_passes(self) -> None:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

            def do_it(self) -> str: ...

        class GoodImpl:
            name = "test"

            def do_it(self) -> str:
                return "done"

        violations = validate_plugin(GoodImpl(), MyProto)
        assert violations == []

    def test_missing_attribute(self) -> None:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

            def do_it(self) -> str: ...

        class BadImpl:
            def do_it(self) -> str:
                return "done"

        violations = validate_plugin(BadImpl(), MyProto)
        assert len(violations) == 1
        assert "missing attribute 'name'" in violations[0]

    def test_missing_method(self) -> None:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

            def do_it(self) -> str: ...

        class BadImpl:
            name = "test"

        violations = validate_plugin(BadImpl(), MyProto)
        assert any("missing method 'do_it'" in v for v in violations)

    def test_method_not_callable(self) -> None:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

            def do_it(self) -> str: ...

        class BadImpl:
            name = "test"
            do_it = "not_a_function"  # type: ignore[assignment]

        violations = validate_plugin(BadImpl(), MyProto)
        assert any("is not callable" in v for v in violations)

    def test_skips_dunders(self) -> None:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

        class Impl:
            name = "ok"

        violations = validate_plugin(Impl(), MyProto)
        assert violations == []


# ---------------------------------------------------------------------------
# select_plugins — registry caching
# ---------------------------------------------------------------------------


class TestSelectPluginsCaching:
    """Test that select_plugins fetches the registry once and passes it down."""

    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    def _plugin(self, name: str, requires: list[ModuleRequirement] | None = None) -> object:
        plugin = type(f"Plugin_{name}", (), {})()
        plugin.name = name  # type: ignore[attr-defined]
        plugin.requires = requires or []  # type: ignore[attr-defined]
        return plugin

    async def test_registry_fetched_once(self, tdb: AsyncMock) -> None:
        """When selecting multiple plugins, get_documents should be called once."""
        tdb.get_documents.return_value = [
            {"name": "mod1", "version": "1.0.0"},
            {"name": "mod2", "version": "2.0.0"},
        ]
        p1 = self._plugin("p1", [ModuleRequirement(name="mod1", range=">=1.0.0")])
        p2 = self._plugin("p2", [ModuleRequirement(name="mod2", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 2
        # get_documents should be called exactly once for SchemaModule
        tdb.get_documents.assert_called_once_with("SchemaModule", branch="main")

    async def test_registry_unavailable_per_plugin(self, tdb: AsyncMock) -> None:
        """When registry fetch fails, each plugin gets registry-unavailable violation."""
        tdb.get_documents.side_effect = TdbError(400, "no class")
        p1 = self._plugin("p1", [ModuleRequirement(name="mod1", range=">=1.0.0")])
        p2 = self._plugin("p2", [ModuleRequirement(name="mod2", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert len(sel.skipped) == 2
        # get_documents still called once (then the TdbError is raised)
        assert tdb.get_documents.call_count == 1

    async def test_select_with_protocol_validation(self, tdb: AsyncMock) -> None:
        """Protocol validation violations cause plugin skip."""
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str
            extra: str  # missing attribute

            def do_it(self) -> str: ...

        class MyPlugin:
            name = "test"
            requires: list[ModuleRequirement] = []

            def do_it(self) -> str:
                return "ok"

        tdb.get_documents.return_value = []
        discovered = DiscoveryResult(active=[("p1", MyPlugin())], failed=[])
        sel = await select_plugins(tdb, discovered, protocol=MyProto)
        assert len(sel.skipped) == 1
        violations = sel.skipped[0][1]
        assert any("missing attribute 'extra'" in v for v in violations)

    async def test_select_strict_with_protocol_violation_raises(self, tdb: AsyncMock) -> None:
        """Strict mode + protocol violation → RuntimeError."""
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class MyProto(Protocol):
            name: str

            def do_it(self) -> str: ...

        class MyPlugin:
            name = "test"
            requires: list[ModuleRequirement] = []

        tdb.get_documents.return_value = []
        discovered = DiscoveryResult(active=[("p1", MyPlugin())], failed=[])
        with pytest.raises(RuntimeError, match="Strict plugin mode"):
            await select_plugins(tdb, discovered, strict=True, protocol=MyProto)


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_defaults(self) -> None:
        r = ExecutionResult(ok=True)
        assert r.ok is True
        assert r.detail == ""
        assert r.retryable is False
        assert r.external_ref is None

    def test_with_external_ref(self) -> None:
        r = ExecutionResult(ok=True, detail="created", external_ref="https://example.com/42")
        assert r.external_ref == "https://example.com/42"

    def test_terminal_failure(self) -> None:
        r = ExecutionResult(ok=False, detail="auth failed", retryable=False)
        assert r.ok is False
        assert r.retryable is False

    def test_retryable_failure(self) -> None:
        r = ExecutionResult(ok=False, detail="timeout", retryable=True)
        assert r.ok is False
        assert r.retryable is True


# ---------------------------------------------------------------------------
# ActionContext defaults
# ---------------------------------------------------------------------------


class TestActionContext:
    def test_now_returns_tz_aware_utc(self) -> None:
        ctx = ActionContext(tdb=None, logger=None)
        now = ctx.now()
        from datetime import timezone

        assert now.tzinfo is not None
        assert now.tzinfo.utcoffset(now) is not None
        assert now.utcoffset() == timezone.utc.utcoffset(None)

    def test_dry_run_default_false(self) -> None:
        ctx = ActionContext(tdb=None, logger=None)
        assert ctx.dry_run is False

    def test_idempotency_key_default_empty(self) -> None:
        ctx = ActionContext(tdb=None, logger=None)
        assert ctx.idempotency_key == ""

    def test_custom_now(self) -> None:
        from datetime import datetime, timezone

        fixed = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ctx = ActionContext(tdb=None, logger=None, now=lambda: fixed)
        assert ctx.now() == fixed

    def test_dry_run_true(self) -> None:
        ctx = ActionContext(tdb=None, logger=None, dry_run=True)
        assert ctx.dry_run is True
        assert ctx.idempotency_key == ""

    def test_idempotency_key_set(self) -> None:
        ctx = ActionContext(tdb=None, logger=None, idempotency_key="key-123")
        assert ctx.idempotency_key == "key-123"


# ---------------------------------------------------------------------------
# Deprecated aliases
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ActionExecutor protocol validation
# ---------------------------------------------------------------------------


class TestActionExecutorProtocol:
    def test_valid_executor_passes_validate(self) -> None:
        class FakeExecutor:
            name = "fake"
            requires: list[ModuleRequirement] = []
            kinds: tuple[str, ...] = ("webhook",)

            async def execute(
                self,
                action: dict,
                firing: dict,
                subject: dict | None,
                ctx: ActionContext,
            ) -> ExecutionResult:
                return ExecutionResult(ok=True)

        violations = validate_plugin(FakeExecutor(), ActionExecutor)
        assert violations == []

    def test_isinstance_check(self) -> None:
        class FakeExecutor:
            name = "fake"
            requires: list[ModuleRequirement] = []
            kinds: tuple[str, ...] = ("webhook",)

            async def execute(
                self,
                action: dict,
                firing: dict,
                subject: dict | None,
                ctx: ActionContext,
            ) -> ExecutionResult:
                return ExecutionResult(ok=True)

        assert isinstance(FakeExecutor(), ActionExecutor)

    def test_missing_kinds_fails_validate(self) -> None:
        class BadExecutor:
            name = "bad"
            requires: list[ModuleRequirement] = []

            async def execute(
                self,
                action: dict,
                firing: dict,
                subject: dict | None,
                ctx: ActionContext,
            ) -> ExecutionResult:
                return ExecutionResult(ok=True)

        violations = validate_plugin(BadExecutor(), ActionExecutor)
        assert any("missing attribute 'kinds'" in v for v in violations)

    def test_missing_execute_fails_validate(self) -> None:
        class BadExecutor:
            name = "bad"
            requires: list[ModuleRequirement] = []
            kinds: tuple[str, ...] = ("webhook",)

        violations = validate_plugin(BadExecutor(), ActionExecutor)
        assert any("missing method 'execute'" in v for v in violations)


# ---------------------------------------------------------------------------
# firnline_core top-level exports
# ---------------------------------------------------------------------------


class TestTopLevelExports:
    def test_new_names_importable_from_firnline_core(self) -> None:
        import firnline_core

        assert hasattr(firnline_core, "ActionContext")
        assert hasattr(firnline_core, "ActionExecutor")
        assert hasattr(firnline_core, "ExecutionResult")


# ---------------------------------------------------------------------------
# check_requirements — required_classes
# ---------------------------------------------------------------------------


class TestCheckRequirementsClasses:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    async def test_required_classes_all_present(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Reminder", "Note"]},
            {"name": "planning", "version": "1.0.0", "exports": ["Task", "Event"]},
        ]
        violations = await check_requirements(tdb, [], required_classes=["Reminder", "Event"])
        assert violations == []

    async def test_required_class_missing(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        violations = await check_requirements(tdb, [], required_classes=["Reminder"])
        assert len(violations) == 1
        assert "class 'Reminder' not exported by any installed module" in violations[0]

    async def test_required_classes_no_exports_field_anywhere(self, tdb: AsyncMock) -> None:
        """Legacy registry: no doc has an 'exports' field."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0"},
            {"name": "planning", "version": "2.0.0"},
        ]
        violations = await check_requirements(tdb, [], required_classes=["Reminder"])
        assert len(violations) == 1
        assert "registry has no exports information" in violations[0]

    async def test_required_classes_none_skips_check(self, tdb: AsyncMock) -> None:
        """required_classes=None means no export check at all."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0"},
        ]
        violations = await check_requirements(tdb, [], required_classes=None)
        assert violations == []

    async def test_required_classes_empty_list_noop(self, tdb: AsyncMock) -> None:
        """required_classes=[] means check exports info but require no specific class."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        violations = await check_requirements(tdb, [], required_classes=[])
        assert violations == []

    async def test_required_classes_empty_list_legacy(self, tdb: AsyncMock) -> None:
        """required_classes=[] with legacy registry — still emits violation."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0"},
        ]
        violations = await check_requirements(tdb, [], required_classes=[])
        assert len(violations) == 1
        assert "registry has no exports information" in violations[0]

    async def test_required_classes_via_registry_injection(self, tdb: AsyncMock) -> None:
        """Use the registry= kwarg to bypass TDB."""
        registry = [
            {"name": "m1", "version": "1.0.0", "exports": ["A", "B"]},
            {"name": "m2", "version": "1.0.0", "exports": ["C"]},
        ]
        violations = await check_requirements(tdb, [], registry=registry, required_classes=["A", "C"])
        assert violations == []
        tdb.get_documents.assert_not_called()

    async def test_required_classes_mixed_with_module_reqs(self, tdb: AsyncMock) -> None:
        """Module reqs + class reqs together."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        reqs = [ModuleRequirement(name="capture", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs, required_classes=["Note"])
        assert violations == []

    async def test_required_classes_missing_and_module_unmet(self, tdb: AsyncMock) -> None:
        """Both a module violation and a class violation in one call."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        reqs = [ModuleRequirement(name="planning", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs, required_classes=["Reminder"])
        assert len(violations) == 2
        assert any("module 'planning' not installed" in v for v in violations)
        assert any("class 'Reminder' not exported" in v for v in violations)


# ---------------------------------------------------------------------------
# select_plugins — requires_classes passthrough
# ---------------------------------------------------------------------------


class TestSelectPluginsRequiresClasses:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    def _plugin(self, name: str, requires=None, requires_classes=None) -> object:
        plugin = type(f"Plugin_{name}", (), {})()
        plugin.name = name  # type: ignore[attr-defined]
        plugin.requires = requires or []  # type: ignore[attr-defined]
        if requires_classes is not None:
            plugin.requires_classes = requires_classes  # type: ignore[attr-defined]
        return plugin

    async def test_requires_classes_satisfied(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Reminder"]},
        ]
        p1 = self._plugin("p1", requires_classes=["Reminder"])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 1
        assert sel.skipped == []

    async def test_requires_classes_violation_skips(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        p1 = self._plugin("p1", requires_classes=["Reminder"])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert sel.active == []
        assert len(sel.skipped) == 1
        assert any("class 'Reminder' not exported" in v for v in sel.skipped[0][1])

    async def test_plugin_without_requires_classes_still_works(self, tdb: AsyncMock) -> None:
        """Plugin without requires_classes attribute is fine."""
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0", "exports": ["Note"]},
        ]
        p1 = self._plugin("p1")  # no requires_classes at all
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 1

    async def test_requires_classes_legacy_registry_skips(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "capture", "version": "1.0.0"},  # no exports
        ]
        p1 = self._plugin("p1", requires_classes=["Reminder"])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert sel.active == []
        assert len(sel.skipped) == 1
        assert any("registry has no exports information" in v for v in sel.skipped[0][1])


# ---------------------------------------------------------------------------
# PluginHost
# ---------------------------------------------------------------------------


class TestPluginHostHappyPath:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        tdb = AsyncMock()
        tdb.get_documents.return_value = []
        return tdb

    def _plugin(self, name: str) -> object:
        class P:
            pass

        p = P()
        p.name = name  # type: ignore[attr-defined]
        p.requires: list[ModuleRequirement] = []  # type: ignore[attr-defined]
        return p

    async def test_happy_path(self, tdb: AsyncMock) -> None:
        p1 = self._plugin("p1")
        p2 = self._plugin("p2")
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        host = PluginHost(group="test.group", protocol=None, tdb=tdb)
        result = await host.start(discovered=discovered)
        assert len(result.active) == 2
        assert result.skipped == []
        assert result.failed == []

    async def test_broken_entry_point_fatal(self, tdb: AsyncMock) -> None:
        discovered = DiscoveryResult(active=[], failed=[("bad_ep", "ImportError: boom")])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(broken_entry_point_fatal=True),
        )
        with pytest.raises(RuntimeError, match="failed to load"):
            await host.start(discovered=discovered)

    async def test_broken_entry_point_non_fatal(self, tdb: AsyncMock) -> None:
        discovered = DiscoveryResult(active=[], failed=[("bad_ep", "ImportError: boom")])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(broken_entry_point_fatal=False),
        )
        result = await host.start(discovered=discovered)
        assert result.active == []
        assert result.failed == [("bad_ep", "ImportError: boom")]

    async def test_zero_active_fatal(self, tdb: AsyncMock) -> None:
        discovered = DiscoveryResult(active=[], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(zero_active_fatal=True),
        )
        with pytest.raises(RuntimeError, match="No active plugins"):
            await host.start(discovered=discovered)

    async def test_zero_active_non_fatal(self, tdb: AsyncMock) -> None:
        discovered = DiscoveryResult(active=[], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(zero_active_fatal=False),
        )
        result = await host.start(discovered=discovered)
        assert result.active == []


class TestPluginHostCollisions:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        tdb = AsyncMock()
        tdb.get_documents.return_value = []
        return tdb

    def _plugin(self, name: str, keys: list[str]) -> object:
        class P:
            pass

        p = P()
        p.name = name  # type: ignore[attr-defined]
        p.requires: list[ModuleRequirement] = []  # type: ignore[attr-defined]
        p.keys = keys  # type: ignore[attr-defined]
        return p

    async def test_collision_raises(self, tdb: AsyncMock) -> None:
        p1 = self._plugin("p1", ["key_a", "key_b"])
        p2 = self._plugin("p2", ["key_b", "key_c"])
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        host = PluginHost(group="test.group", protocol=None, tdb=tdb)
        with pytest.raises(RuntimeError, match="collision"):
            await host.start(
                discovered=discovered,
                collision_key=lambda p: p.keys,  # type: ignore[attr-defined]
            )

    async def test_no_collision(self, tdb: AsyncMock) -> None:
        p1 = self._plugin("p1", ["key_a"])
        p2 = self._plugin("p2", ["key_b"])
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        host = PluginHost(group="test.group", protocol=None, tdb=tdb)
        result = await host.start(
            discovered=discovered,
            collision_key=lambda p: p.keys,  # type: ignore[attr-defined]
        )
        assert len(result.active) == 2


class TestPluginHostGracefulDegradation:
    @pytest.fixture
    def tdb(self) -> AsyncMock:
        return AsyncMock()

    def _plugin(self, name: str) -> object:
        class P:
            pass

        p = P()
        p.name = name  # type: ignore[attr-defined]
        p.requires: list[ModuleRequirement] = []  # type: ignore[attr-defined]
        return p

    async def test_tdb_unavailable_fatal(self, tdb: AsyncMock) -> None:
        tdb.get_documents.side_effect = TdbError(500, "connection refused")
        p1 = self._plugin("p1")
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(tdb_unavailable_fatal=True),
        )
        with pytest.raises(TdbError, match="connection refused"):
            await host.start(discovered=discovered)

    async def test_tdb_unavailable_graceful(self, tdb: AsyncMock) -> None:
        tdb.get_documents.side_effect = TdbError(500, "connection refused")
        p1 = self._plugin("p1")
        p2 = self._plugin("p2")
        discovered = DiscoveryResult(active=[("p1", p1), ("p2", p2)], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(tdb_unavailable_fatal=False),
        )
        result = await host.start(discovered=discovered)
        assert result.active == []
        assert len(result.skipped) == 2
        assert all("registry unavailable" in v for _, violations in result.skipped for v in violations)

    async def test_tdb_unavailable_graceful_non_tdb_error(self, tdb: AsyncMock) -> None:
        """Graceful degradation also catches non-TdbError exceptions (e.g. network)."""
        tdb.get_documents.side_effect = ConnectionError("no route to host")
        p1 = self._plugin("p1")
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(tdb_unavailable_fatal=False),
        )
        result = await host.start(discovered=discovered)
        assert result.active == []
        assert len(result.skipped) == 1
        assert "registry unavailable" in result.skipped[0][1][0]


class TestPluginHostPolicyMatrix:
    """Combinations of policy flags."""

    @pytest.fixture
    def tdb(self) -> AsyncMock:
        tdb = AsyncMock()
        tdb.get_documents.return_value = []
        return tdb

    def _plugin(self, name: str) -> object:
        class P:
            pass

        p = P()
        p.name = name  # type: ignore[attr-defined]
        p.requires: list[ModuleRequirement] = []  # type: ignore[attr-defined]
        return p

    async def test_strict_skipped_raises(self, tdb: AsyncMock) -> None:
        """When strict=True and a plugin has unmet requirements, RuntimeError."""

        class PWithReq:
            name = "p1"
            requires = [ModuleRequirement(name="missing", range=">=1.0.0")]

        discovered = DiscoveryResult(active=[("p1", PWithReq())], failed=[])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(strict=True),
        )
        with pytest.raises(RuntimeError, match="Strict plugin mode"):
            await host.start(discovered=discovered)

    async def test_broken_ep_non_fatal_zero_active_fatal(self, tdb: AsyncMock) -> None:
        """Broken EP tolerated, but then zero active is fatal."""
        discovered = DiscoveryResult(active=[], failed=[("bad", "error")])
        host = PluginHost(
            group="test.group",
            protocol=None,
            tdb=tdb,
            policy=HostPolicy(
                broken_entry_point_fatal=False,
                zero_active_fatal=True,
            ),
        )
        with pytest.raises(RuntimeError, match="No active plugins"):
            await host.start(discovered=discovered)

    async def test_registry_prefetch(self, tdb: AsyncMock) -> None:
        """Pre-fetched registry is passed through, TDB not called."""
        p1 = self._plugin("p1")
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        host = PluginHost(group="test.group", protocol=None, tdb=tdb)
        registry = [{"name": "m1", "version": "1.0.0"}]
        result = await host.start(discovered=discovered, registry=registry)
        assert len(result.active) == 1
        tdb.get_documents.assert_not_called()


class TestPluginHostLogEvents:
    """Verify that PluginHost emits the expected log event names."""

    @pytest.fixture
    def tdb(self) -> AsyncMock:
        tdb = AsyncMock()
        tdb.get_documents.return_value = []
        return tdb

    def _plugin(self, name: str) -> object:
        class P:
            pass

        p = P()
        p.name = name  # type: ignore[attr-defined]
        p.requires: list[ModuleRequirement] = []  # type: ignore[attr-defined]
        return p

    async def test_log_events_on_happy_path(self, tdb: AsyncMock) -> None:
        """Verify startup_complete event is emitted."""
        p1 = self._plugin("p1")
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        import logging

        class CollectHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records: list[logging.LogRecord] = []

            def emit(self, record: logging.LogRecord) -> None:
                self.records.append(record)

        handler = CollectHandler()
        log_stream = logging.getLogger("firnline_core.plugins")
        log_stream.setLevel(logging.DEBUG)
        log_stream.addHandler(handler)
        try:
            host = PluginHost(group="test.group", protocol=None, tdb=tdb)
            await host.start(discovered=discovered)
        finally:
            log_stream.removeHandler(handler)

        msgs = [r.getMessage() for r in handler.records]
        assert any("plugin_startup_complete" in m for m in msgs)

    async def test_log_skipped_plugin(self, tdb: AsyncMock) -> None:
        """Plugin with unmet requirement gets a 'plugin_skipped' log event."""

        class PWithReq:
            name = "p1"
            requires = [ModuleRequirement(name="missing", range=">=1.0.0")]

        discovered = DiscoveryResult(active=[("p1", PWithReq())], failed=[])
        import logging

        class CollectHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records: list[logging.LogRecord] = []

            def emit(self, record: logging.LogRecord) -> None:
                self.records.append(record)

        handler = CollectHandler()
        log_stream = logging.getLogger("firnline_core.plugins")
        log_stream.setLevel(logging.WARNING)
        log_stream.addHandler(handler)
        try:
            host = PluginHost(group="test.group", protocol=None, tdb=tdb)
            await host.start(discovered=discovered)
        finally:
            log_stream.removeHandler(handler)

        msgs = [r.getMessage() for r in handler.records]
        assert any("plugin_skipped" in m for m in msgs)

    async def test_log_broken_entry_point_non_fatal(self, tdb: AsyncMock) -> None:
        """Non-fatal broken EP logs a warning."""
        discovered = DiscoveryResult(active=[], failed=[("bad", "ImportError: nope")])
        import logging

        class CollectHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records: list[logging.LogRecord] = []

            def emit(self, record: logging.LogRecord) -> None:
                self.records.append(record)

        handler = CollectHandler()
        log_stream = logging.getLogger("firnline_core.plugins")
        log_stream.setLevel(logging.WARNING)
        log_stream.addHandler(handler)
        try:
            host = PluginHost(
                group="test.group",
                protocol=None,
                tdb=tdb,
                policy=HostPolicy(broken_entry_point_fatal=False),
            )
            await host.start(discovered=discovered)
        finally:
            log_stream.removeHandler(handler)

        msgs = [r.getMessage() for r in handler.records]
        assert any("plugin_load_failed" in m for m in msgs)
