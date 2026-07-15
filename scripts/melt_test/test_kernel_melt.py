"""Kernel melt tests — verify every service boots with zero extensions installed.

All tests are database-free: TdbClient is replaced with AsyncMock, and
entry-point discovery is monkeypatched to return empty where needed.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _make_async_select(result):
    """Return an async function matching select_plugins' signature."""

    async def _inner(tdb, discovered, *, strict=False, branch="main", protocol=None, registry=None):
        if strict and result.skipped:
            skipped_names = [n for n, _ in result.skipped]
            raise RuntimeError(
                f"Strict plugin mode: skipped={skipped_names}, failed=[]"
            )
        return result

    return _inner


# ---------------------------------------------------------------------------
# 1. ingestd — Pipeline with zero source + zero extractor plugins
# ---------------------------------------------------------------------------


class TestIngestdMelt:
    """Pipeline completes a cycle with zero plugins."""

    @pytest.mark.asyncio
    async def test_pipeline_cycle_zero_plugins(self) -> None:
        from ingestd.pipeline import Pipeline
        from ingestd.settings import Settings
        from ingestd.extraction import ExtractionContext

        tdb = AsyncMock()
        tdb.graphql.return_value = {}
        tdb.get_documents = AsyncMock(return_value=[])
        tdb.get_documents_by_status = AsyncMock(return_value=[])

        agent = AsyncMock()

        settings = Settings(tdb_db="test", tdb_password="test")  # type: ignore[call-arg]

        extraction_ctx = ExtractionContext(
            system_prompt="",
            kind_to_model={},
            kind_to_plugin={},
            plugins=[],
        )

        pipeline = Pipeline(
            tdb=tdb,
            agent=agent,
            settings=settings,
            source_plugins=[],
            extraction_ctx=extraction_ctx,
        )

        await pipeline.run_cycle()

        # No exceptions = pass. Cycle completed with zero items.
        assert True


# ---------------------------------------------------------------------------
# 2. triggerd — Engine with zero evaluators
# ---------------------------------------------------------------------------


class TestTriggerdMelt:
    """Engine completes a cycle with zero evaluator plugins."""

    @pytest.mark.asyncio
    async def test_engine_cycle_zero_evaluators(self) -> None:
        from triggerd.engine import Engine
        from triggerd.settings import Settings
        from firnline_core.repository import Repository

        tdb = AsyncMock()
        tdb.get_schema = AsyncMock(return_value=[])  # no trigger types
        tdb.changes_since = AsyncMock(return_value=([], "head"))
        tdb.get_documents = AsyncMock(return_value=[])

        settings = Settings(tdb_db="test", tdb_password="x")  # type: ignore[call-arg]

        engine = Engine(
            repo=Repository(tdb),
            settings=settings,
            evaluators=[],
        )

        await engine.run_cycle()

        # No evaluators, no trigger types → cycle completes with
        # triggers_scanned=0, no firings.
        assert True


# ---------------------------------------------------------------------------
# 3. queryd — render_schema_summary with kernel-only introspection
# ---------------------------------------------------------------------------


class TestQuerydMelt:
    """Schema summary renders correctly with only kernel types."""

    def test_render_schema_summary_kernel_only(self) -> None:
        from queryd.schema_briefing import render_schema_summary

        # Synthetic introspection with only kernel classes:
        # Captured, TriggerFiring + their enums.
        introspection: dict[str, Any] = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": {"name": "TerminusMutation"},
                "types": [
                    # --- Query type ---
                    {
                        "name": "Query",
                        "kind": "OBJECT",
                        "fields": [],
                    },
                    # --- Captured ---
                    {
                        "name": "Captured",
                        "kind": "OBJECT",
                        "fields": [
                            {"name": "_id", "type": {"name": "ID", "kind": "SCALAR"}},
                            {"name": "content", "type": {"name": "String", "kind": "SCALAR"}},
                            {"name": "status", "type": {"name": "CapturedStatus", "kind": "ENUM"}},
                        ],
                    },
                    # --- TriggerFiring ---
                    {
                        "name": "TriggerFiring",
                        "kind": "OBJECT",
                        "fields": [
                            {"name": "_id", "type": {"name": "ID", "kind": "SCALAR"}},
                            {"name": "trigger", "type": {"name": "String", "kind": "SCALAR"}},
                            {"name": "fired_at", "type": {"name": "DateTime", "kind": "SCALAR"}},
                            {"name": "status", "type": {"name": "FiringStatus", "kind": "ENUM"}},
                        ],
                    },
                    # --- Enums ---
                    {
                        "name": "CapturedStatus",
                        "kind": "ENUM",
                        "fields": None,
                        "enumValues": [
                            {"name": "new"},
                            {"name": "transcribed"},
                            {"name": "processed"},
                            {"name": "failed"},
                            {"name": "archived"},
                        ],
                    },
                    {
                        "name": "FiringStatus",
                        "kind": "ENUM",
                        "fields": None,
                        "enumValues": [
                            {"name": "pending"},
                            {"name": "notified"},
                            {"name": "acknowledged"},
                            {"name": "snoozed"},
                            {"name": "expired"},
                        ],
                    },
                ],
            }
        }

        summary = render_schema_summary(introspection)

        # Must be non-empty and contain key elements.
        assert "Captured" in summary
        assert "TriggerFiring" in summary
        assert "FiringStatus" in summary
        assert len(summary) > 200  # substantial output


# ---------------------------------------------------------------------------
# 4. captured — built-in handlers only
# ---------------------------------------------------------------------------


class TestCapturedMelt:
    """Captured app works with only built-in handlers."""

    def test_note_capture_succeeds_with_builtin_handler(self, monkeypatch) -> None:
        from unittest.mock import AsyncMock

        from fastapi.testclient import TestClient

        from captured.app import create_app
        from captured.handlers import captured_note_handler
        from captured.settings import Settings
        from firnline_core.plugins import (
            DiscoveryResult,
            PluginSelection,
        )

        # Fake TdbClient — returns a valid IRI on insert
        fake_tdb = AsyncMock()
        fake_tdb.insert_documents = AsyncMock(
            return_value=["terminusdb:///data/Captured/test1"]
        )
        fake_tdb.db_exists = AsyncMock(return_value=True)
        fake_tdb.get_documents = AsyncMock(return_value=[])

        import captured.app as app_mod
        monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: fake_tdb)

        # captured.app now uses PluginHost internally, which calls
        # discover_plugins / select_plugins from firnline_core.plugins.
        import firnline_core.plugins as core_plugins

        monkeypatch.setattr(
            core_plugins,
            "discover_plugins",
            lambda group: DiscoveryResult(
                active=[("captured_note", captured_note_handler)],
                failed=[],
            ),
        )
        monkeypatch.setattr(
            core_plugins,
            "select_plugins",
            _make_async_select(
                PluginSelection(
                    active=[("captured_note", captured_note_handler)],
                    skipped=[],
                )
            ),
        )

        settings = Settings(api_token="melt-token", tdb_db="test", tdb_password="x")  # type: ignore[call-arg]
        app = create_app(settings)

        with TestClient(app) as client:
            # Note capture succeeds
            resp = client.post(
                "/v1/capture/note",
                content="melt test note",
                headers={
                    "Content-Type": "text/plain",
                    "Authorization": "Bearer melt-token",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["kind"] == "note"
            assert "id" in data

    def test_unknown_kind_returns_404_with_hint(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import AsyncMock

        from fastapi.testclient import TestClient

        from captured.app import create_app
        from captured.handlers import captured_note_handler
        from captured.settings import Settings
        from firnline_core.plugins import (
            DiscoveryResult,
            PluginSelection,
        )

        monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))

        fake_tdb = AsyncMock()
        fake_tdb.insert_documents = AsyncMock(return_value=["fake-iri"])
        fake_tdb.db_exists = AsyncMock(return_value=True)
        fake_tdb.get_documents = AsyncMock(return_value=[])

        import captured.app as app_mod
        monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: fake_tdb)

        import firnline_core.plugins as core_plugins

        monkeypatch.setattr(
            core_plugins,
            "discover_plugins",
            lambda group: DiscoveryResult(
                active=[("captured_note", captured_note_handler)],
                failed=[],
            ),
        )
        monkeypatch.setattr(
            core_plugins,
            "select_plugins",
            _make_async_select(
                PluginSelection(
                    active=[("captured_note", captured_note_handler)],
                    skipped=[],
                )
            ),
        )

        settings = Settings(api_token="melt-token", tdb_db="test", tdb_password="x")  # type: ignore[call-arg]
        app = create_app(settings)

        with TestClient(app) as client:
            resp = client.post(
                "/v1/capture/file",
                files={"file": ("test.txt", b"hi", "text/plain")},
                data={"kind": "unknown-kind"},
                headers={"Authorization": "Bearer melt-token"},
            )
            assert resp.status_code == 404
            detail = resp.json()["detail"]
            assert "no handler for kind" in detail["message"]
            assert "hint" in detail
            assert "Install a captured handler" in detail["hint"]


# ---------------------------------------------------------------------------
# 5. effectd — zero channels
# ---------------------------------------------------------------------------


class TestEffectdMelt:
    """EffectEngine completes a cycle with zero channel plugins."""

    @pytest.mark.asyncio
    async def test_run_cycle_zero_channels(self) -> None:
        from effectd.engine import EffectEngine
        from firnline_core.repository import Repository

        tdb = AsyncMock()
        tdb.get_documents_by_status = AsyncMock(return_value=[])

        repo = Repository(tdb)

        engine = EffectEngine(
            repo=repo,
            channels=[],  # zero channels → idles
        )

        await engine.run_cycle()

        # No exceptions, writes nothing.
        tdb.insert_documents.assert_not_called()
        tdb.replace_document.assert_not_called()


# ---------------------------------------------------------------------------
# 6. discovery melt — empty entry-point groups
# ---------------------------------------------------------------------------


class TestDiscoveryMelt:
    """Plugin discovery and selection work with zero installed extensions."""

    def test_discover_plugins_returns_empty(self) -> None:

        from firnline_core.plugins import discover_plugins

        target_group = "firnline.melt.nonexistent"

        # Monkeypatch entry_points to return empty for this group.
        # entry_points is imported inside discover_plugins(), so we patch
        # the original source in importlib.metadata.
        with patch(
            "importlib.metadata.entry_points",
            return_value=[],
        ):
            result = discover_plugins(target_group)

        assert isinstance(result.active, list)
        assert isinstance(result.failed, list)
        assert len(result.active) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_select_plugins_empty_discovery(self) -> None:
        from firnline_core.plugins import (
            DiscoveryResult,
            PluginSelection,
            select_plugins,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        discovered = DiscoveryResult(active=[], failed=[])
        selection = await select_plugins(tdb, discovered)

        assert isinstance(selection, PluginSelection)
        assert len(selection.active) == 0
        assert len(selection.skipped) == 0


# ---------------------------------------------------------------------------
# 7. Zero-plugin PluginHost boot tests for all 7 host services
# ---------------------------------------------------------------------------


class TestPluginHostZeroPlugins:
    """Every plugin-hosting service boots through PluginHost with zero plugins."""

    @pytest.mark.asyncio
    async def test_captured_zero_plugin_boot(self) -> None:
        """captured PluginHost start with empty DiscoveryResult (no handlers)."""
        from firnline_core.plugins import (
            CaptureHandler,
            DiscoveryResult,
            HostPolicy,
            PluginHost,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=True,
            tdb_unavailable_fatal=False,
            strict=False,
        )
        host = PluginHost(
            group="firnline.captured.handlers",
            protocol=CaptureHandler,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        result = await host.start(
            collision_key=lambda h: list(h.kinds),
            registry=[],
            discovered=DiscoveryResult(active=[], failed=[]),
        )
        # Zero plugins is NOT fatal for captured (zero_active_fatal=False default)
        assert len(result.active) == 0
        assert len(result.failed) == 0
        assert len(result.skipped) == 0

    @pytest.mark.asyncio
    async def test_ingestd_extractor_zero_plugin_boot(self) -> None:
        """ingestd extractor PluginHost with zero_active_fatal=True raises RuntimeError."""
        from firnline_core.plugins import (
            DiscoveryResult,
            ExtractorPlugin,
            HostPolicy,
            PluginHost,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        # ingestd extractors use zero_active_fatal=True
        policy = HostPolicy(
            broken_entry_point_fatal=True,
            zero_active_fatal=True,
            strict=False,
        )
        host = PluginHost(
            group="firnline.ingestd.extractors",
            protocol=ExtractorPlugin,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        with pytest.raises(RuntimeError, match="No active plugins"):
            await host.start(
                collision_key=lambda p: [],
                registry=[],
                discovered=DiscoveryResult(active=[], failed=[]),
            )

    @pytest.mark.asyncio
    async def test_ingestd_source_zero_plugin_boot(self) -> None:
        """ingestd source PluginHost with zero_active_fatal=True raises RuntimeError."""
        from firnline_core.plugins import (
            DiscoveryResult,
            HostPolicy,
            IngestSourcePlugin,
            PluginHost,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=True,
            zero_active_fatal=True,
            strict=False,
        )
        host = PluginHost(
            group="firnline.ingestd.sources",
            protocol=IngestSourcePlugin,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        with pytest.raises(RuntimeError, match="No active plugins"):
            await host.start(
                collision_key=lambda p: [],
                registry=[],
                discovered=DiscoveryResult(active=[], failed=[]),
            )

    @pytest.mark.asyncio
    async def test_indexed_zero_plugin_boot(self) -> None:
        """indexed PluginHost boots with zero indexer plugins (not fatal)."""
        from firnline_core.plugins import (
            DiscoveryResult,
            HostPolicy,
            IndexerPlugin,
            PluginHost,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=False,
            zero_active_fatal=False,
            strict=False,
        )
        host = PluginHost(
            group="firnline.indexed.indexers",
            protocol=IndexerPlugin,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        result = await host.start(
            collision_key=lambda p: p.indexed_classes(),
            registry=[],
            discovered=DiscoveryResult(active=[], failed=[]),
        )
        assert len(result.active) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_effectd_zero_plugin_boot(self) -> None:
        """effectd PluginHost boots with zero channel plugins (not fatal)."""
        from firnline_core.plugins import (
            DiscoveryResult,
            HostPolicy,
            NotificationChannel,
            PluginHost,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=False,
            zero_active_fatal=False,
        )
        host = PluginHost(
            group="firnline.notifyd.channels",
            protocol=NotificationChannel,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        result = await host.start(
            collision_key=lambda c: [c.name],
            registry=[],
            discovered=DiscoveryResult(active=[], failed=[]),
        )
        assert len(result.active) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_queryd_zero_plugin_boot(self) -> None:
        """queryd PluginHost boots with zero tool plugins (not fatal, tdb_unavailable_fatal=False)."""
        from firnline_core.plugins import (
            DiscoveryResult,
            HostPolicy,
            PluginHost,
            ToolSpecPlugin,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=False,
            zero_active_fatal=False,
            strict=False,
            tdb_unavailable_fatal=False,
        )
        host = PluginHost(
            group="firnline.queryd.tools",
            protocol=ToolSpecPlugin,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        result = await host.start(
            collision_key=lambda p: [t.name for t in p.tool_specs()],
            registry=[],
            discovered=DiscoveryResult(active=[], failed=[]),
        )
        assert len(result.active) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_triggerd_zero_plugin_boot(self) -> None:
        """triggerd PluginHost boots with zero evaluator plugins (not fatal)."""
        from firnline_core.plugins import (
            DiscoveryResult,
            HostPolicy,
            PluginHost,
            TriggerEvaluator,
        )

        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])

        policy = HostPolicy(
            broken_entry_point_fatal=True,
            zero_active_fatal=False,
            strict=False,
        )
        host = PluginHost(
            group="firnline.triggerd.evaluators",
            protocol=TriggerEvaluator,
            tdb=tdb,
            branch="main",
            policy=policy,
        )
        result = await host.start(
            collision_key=lambda ev: ev.trigger_types,
            registry=[],
            discovered=DiscoveryResult(active=[], failed=[]),
        )
        assert len(result.active) == 0
        assert len(result.failed) == 0
