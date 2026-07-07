"""Tests for firnline_core.plugins — requirement checking, discovery, selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from firnline_core.plugins import (
    BuildContext,
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    DeliveryResult,
    DiscoveryResult,
    EntityIndex,
    ModuleRequirement,
    NotificationChannel,
    NotifyContext,
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
            {"name": "inbox", "version": "2.0.0"},
            {"name": "planning", "version": "1.5.0"},
        ]
        reqs = [
            ModuleRequirement(name="inbox", range=">=1.0.0"),
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
        assert violations == [
            "module 'planning' 1.0.0 does not satisfy '>=2.0.0'"
        ]

    async def test_malformed_range(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        reqs = [ModuleRequirement(name="xyz", range="not-a-range")]
        violations = await check_requirements(tdb, reqs)
        assert violations == [
            "module 'xyz' has malformed range 'not-a-range'"
        ]

    async def test_registry_unavailable(self, tdb: AsyncMock) -> None:
        tdb.get_documents.side_effect = TdbError(400, "no such class")
        reqs = [ModuleRequirement(name="inbox", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert len(violations) == 1
        assert "schema module registry not available" in violations[0]
        assert "400" in violations[0]

    async def test_unparseable_registry_version(self, tdb: AsyncMock) -> None:
        """Corrupted registry version emits a distinct violation."""
        tdb.get_documents.return_value = [
            {"name": "inbox", "version": "not.a.version"},
        ]
        reqs = [ModuleRequirement(name="inbox", range=">=1.0.0")]
        violations = await check_requirements(tdb, reqs)
        assert any(
            "has unparseable version" in v for v in violations
        )

    async def test_uses_provided_branch(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        reqs = [ModuleRequirement(name="inbox", range=">=1.0.0")]
        await check_requirements(tdb, reqs, branch="staging")
        tdb.get_documents.assert_called_once_with(
            "SchemaModule", branch="staging"
        )

    async def test_multiple_violations(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = [
            {"name": "planning", "version": "1.0.0"},
        ]
        reqs = [
            ModuleRequirement(name="planning", range=">=2.0.0"),
            ModuleRequirement(name="people", range=">=1.0.0"),
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
        tdb.get_documents.return_value = [
            {"name": "inbox", "version": "1.0.0"}
        ]
        p1 = self._plugin("p1", [ModuleRequirement(name="inbox", range=">=1.0.0")])
        p2 = self._plugin("p2", [])
        discovered = DiscoveryResult(
            active=[("p1", p1), ("p2", p2)], failed=[]
        )
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 2
        assert sel.skipped == []

    async def test_skip_unmet(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        p1 = self._plugin("p1", [ModuleRequirement(name="inbox", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        sel = await select_plugins(tdb, discovered)
        assert sel.active == []
        assert len(sel.skipped) == 1
        assert sel.skipped[0][0] == "p1"
        assert "not installed" in sel.skipped[0][1][0]

    async def test_strict_raises_on_skip(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        p1 = self._plugin("p1", [ModuleRequirement(name="inbox", range=">=1.0.0")])
        discovered = DiscoveryResult(active=[("p1", p1)], failed=[])
        with pytest.raises(RuntimeError, match="Strict plugin mode"):
            await select_plugins(tdb, discovered, strict=True)

    async def test_strict_raises_on_discovery_failure(self, tdb: AsyncMock) -> None:
        tdb.get_documents.return_value = []
        discovered = DiscoveryResult(
            active=[], failed=[("bad_plugin", "ImportError: boom")]
        )
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
        with patch(
            "importlib.metadata.entry_points", return_value=eps
        ):
            result = discover_plugins("firnline.test.group")
        assert len(result.active) == 1
        assert result.active[0] == ("test_plugin", obj)
        assert result.failed == []

    def test_failing_import_isolation(self) -> None:
        def _fail():
            raise ImportError("cannot import plugin")

        eps = [FakeEntryPoint("bad_plugin", _fail)]
        with patch(
            "importlib.metadata.entry_points", return_value=eps
        ):
            result = discover_plugins("firnline.test.group")
        assert result.active == []
        assert len(result.failed) == 1
        assert result.failed[0][0] == "bad_plugin"
        assert "ImportError" in result.failed[0][1]


# ---------------------------------------------------------------------------
# BuildContext
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_default_now_is_datetime_now(self) -> None:
        from datetime import datetime
        ctx = BuildContext(tdb=None, inbox_iri="test/1")
        now = ctx.now()
        assert isinstance(now, datetime)
        assert now.tzinfo is None  # default datetime.now is naive

    def test_custom_now(self) -> None:
        from datetime import datetime, timezone

        fixed = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ctx = BuildContext(tdb=None, inbox_iri="test/1", now=lambda: fixed)
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
            requires = [ModuleRequirement(name="inbox", range=">=1.0.0")]
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
        assert source.requires[0].name == "inbox"


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
        discovered = DiscoveryResult(
            active=[("p1", p1), ("p2", p2)], failed=[]
        )
        sel = await select_plugins(tdb, discovered)
        assert len(sel.active) == 2
        # get_documents should be called exactly once for SchemaModule
        tdb.get_documents.assert_called_once_with("SchemaModule", branch="main")

    async def test_registry_unavailable_per_plugin(self, tdb: AsyncMock) -> None:
        """When registry fetch fails, each plugin gets registry-unavailable violation."""
        tdb.get_documents.side_effect = TdbError(400, "no class")
        p1 = self._plugin("p1", [ModuleRequirement(name="mod1", range=">=1.0.0")])
        p2 = self._plugin("p2", [ModuleRequirement(name="mod2", range=">=1.0.0")])
        discovered = DiscoveryResult(
            active=[("p1", p1), ("p2", p2)], failed=[]
        )
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
# NotificationChannel structural conformance
# ---------------------------------------------------------------------------


class TestNotificationChannelProtocol:
    """A minimal class should satisfy the NotificationChannel Protocol."""

    async def test_isinstance_check(self) -> None:
        class EmailChannel:
            name = "email"
            requires: list[ModuleRequirement] = []

            async def deliver(
                self,
                firing: dict,
                subject: dict | None,
                ctx: NotifyContext,
            ) -> DeliveryResult:
                return DeliveryResult(ok=True, detail="sent")

        channel = EmailChannel()
        assert isinstance(channel, NotificationChannel)

    async def test_deliver_returns_delivery_result(self) -> None:
        class EmailChannel:
            name = "email"
            requires: list[ModuleRequirement] = []

            async def deliver(
                self,
                firing: dict,
                subject: dict | None,
                ctx: NotifyContext,
            ) -> DeliveryResult:
                return DeliveryResult(ok=False, detail="rate limited", retryable=True)

        channel = EmailChannel()
        ctx = NotifyContext(tdb=None, logger=None)
        result = await channel.deliver({"msg": "hi"}, None, ctx)
        assert result.ok is False
        assert result.detail == "rate limited"
        assert result.retryable is True
