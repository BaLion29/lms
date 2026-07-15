"""Tests for queryd plugin discovery, selection, capability awareness,
and healthz extension — updated for PluginHost migration.

Since ``app.py`` now uses ``firnline_core.plugins.PluginHost``, tests
mock ``firnline_core.plugins.discover_plugins`` and
``firnline_core.plugins.select_plugins`` (which PluginHost calls internally).
Collisions are caught by PluginHost's ``collision_key`` mechanism.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from fastapi.testclient import TestClient

from firnline_core.plugins import (
    DiscoveryResult,
    ModuleRequirement,
    PluginSelection,
)

from queryd.app import create_app
from queryd.settings import Settings
from firnline_ext_time_management.tools import plugin as _planning_plugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"


def _settings(**overrides) -> Settings:
    defaults: dict[str, object] = dict(
        api_token="test-token",
        tdb_db=TDB_DB,
        tdb_password="x",
        tdb_url=TDB_URL,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _tdb_exists_route() -> str:
    return f"{TDB_URL}/api/db/admin/{TDB_DB}"


def _mock_schema_module(name: str, version: str) -> dict:
    return {"@id": f"SchemaModule/{name}", "@type": "SchemaModule", "name": name, "version": version}


# ---------------------------------------------------------------------------
# Plugin with unmet requirement skipped + warning; strict mode fails fast
# ---------------------------------------------------------------------------


class _FakePluginMissingModule:
    """A plugin whose module requirement is never satisfied."""
    name = "fake_plugin"
    requires = [ModuleRequirement(name="nonexistent", range=">=1.0.0")]

    def tool_specs(self):
        return []


def test_unmet_requirement_skipped_with_warning(respx_mock: respx.MockRouter):
    """When the module registry exists but doesn't have the required
    module, the plugin is skipped with a warning — service still starts."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"
    respx_mock.get(DOC_PATH).respond(
        json=[_mock_schema_module("core", "1.0.0")]
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("fake", _FakePluginMissingModule())],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[],
                skipped=[("fake", ["module 'nonexistent' not installed"])],
            )

            settings = _settings(enable_writes=True)
            app = create_app(settings)

            with TestClient(app) as client:
                resp = client.get("/healthz")
            assert resp.status_code == 200


def test_strict_mode_fails_fast_on_skipped(respx_mock: respx.MockRouter):
    """strict_plugins=True raises RuntimeError when a plugin is skipped
    due to unmet requirements."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("fake", _FakePluginMissingModule())],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:

            async def _fake_select(tdb, discovered, *, strict=False, branch="main", protocol=None, registry=None):
                if strict:
                    raise RuntimeError(
                        "Strict plugin mode: skipped=['fake'], failed=[]"
                    )
                return PluginSelection(
                    active=[],
                    skipped=[("fake", ["module 'nonexistent' not installed"])],
                )

            mock_select.side_effect = _fake_select

            settings = _settings(enable_writes=True, strict_plugins=True)

            # create_app only builds the app; the lifespan runs on
            # first request / TestClient context entry.
            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                with TestClient(create_app(settings)):
                    pass


# ---------------------------------------------------------------------------
# ENABLE_WRITES=false suppresses plugin tools
# ---------------------------------------------------------------------------


def test_enable_writes_false_suppresses_plugins(respx_mock: respx.MockRouter):
    """When ENABLE_WRITES=false, write-tool plugins are suppressed even
    if discovered — but plugin names are still reported in healthz."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("time_management", _planning_plugin)],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("time_management", _planning_plugin)],
            )

            settings = _settings(enable_writes=False)
            app = create_app(settings)

            with TestClient(app) as client:
                resp = client.get("/healthz")
            assert resp.status_code == 200
            # Plugins are discovered and reported but tools are suppressed
            assert resp.json()["plugins"] == ["time_management_tools"]


# ---------------------------------------------------------------------------
# Briefing contains module list (mock registry)
# ---------------------------------------------------------------------------


def test_briefing_includes_module_list(respx_mock: respx.MockRouter):
    """When the module registry responds, the schema summary is available."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"
    GQL_PATH = f"{TDB_URL}/api/graphql/admin/{TDB_DB}"

    # Mock get_documents (for module registry)
    respx_mock.get(DOC_PATH).respond(
        json=[_mock_schema_module("core", "1.1.0"), _mock_schema_module("planning", "1.0.0")]
    )
    # Mock introspection
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "mutationType": {"name": "TerminusMutation"},
                    "types": [],
                }
            }
        }
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _settings()
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.get(
            "/v1/schema",
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200

    # Check that the schema summary is not empty
    summary = resp.json()["summary"]
    assert len(summary) > 0


# ---------------------------------------------------------------------------
# Healthz reports modules + active plugins
# ---------------------------------------------------------------------------


def test_healthz_reports_modules_and_plugins(respx_mock: respx.MockRouter):
    """When the module registry responds, /healthz includes module
    versions and active plugin names."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"

    # Mock get_documents (for module registry — will be called multiple times)
    respx_mock.get(DOC_PATH).respond(
        json=[_mock_schema_module("core", "1.1.0"), _mock_schema_module("time_management", "0.1.0")]
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _settings(enable_writes=True)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("time_management", _planning_plugin)],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("time_management", _planning_plugin)],
            )

            app = create_app(settings)

            with TestClient(app) as client:
                resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.json()
    assert data["terminusdb"] == "up"
    assert "modules" in data
    assert data["modules"]["core"] == "1.1.0"
    assert data["modules"]["time_management"] == "0.1.0"
    assert "plugins" in data
    assert "time_management_tools" in data["plugins"]


# ---------------------------------------------------------------------------
# Registry-unavailable degradation
# ---------------------------------------------------------------------------


def test_registry_unavailable_graceful_degradation(respx_mock: respx.MockRouter):
    """When the module registry throws TdbError, the service starts
    with modules omitted and healthz reports empty modules.
    PluginHost handles the unavailable registry gracefully via
    tdb_unavailable_fatal=False."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"

    # get_documents raises TdbError (simulating missing SchemaModule class)
    respx_mock.get(DOC_PATH).respond(status_code=404, text="not found")
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _settings()
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.json()
    assert data["terminusdb"] == "up"
    # modules should be empty (degraded gracefully)
    assert data["modules"] == {}
    # plugins should be empty (no write plugins active)
    assert data["plugins"] == []


# ---------------------------------------------------------------------------
# strict_plugins enforcement works regardless of enable_writes
# ---------------------------------------------------------------------------


def test_strict_fails_with_writes_disabled(respx_mock: respx.MockRouter):
    """strict_plugins=True + unmet requirement → fatal even when
    enable_writes=False."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("fake", _FakePluginMissingModule())],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:

            async def _fake_select(tdb, discovered, *, strict=False, branch="main", protocol=None, registry=None):
                if strict:
                    raise RuntimeError(
                        "Strict plugin mode: skipped=['fake'], failed=[]"
                    )
                return PluginSelection(
                    active=[],
                    skipped=[("fake", ["module 'nonexistent' not installed"])],
                )

            mock_select.side_effect = _fake_select

            settings = _settings(enable_writes=False, strict_plugins=True)

            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                with TestClient(create_app(settings)):
                    pass


def test_nonstrict_writes_disabled_allows_skipped(respx_mock: respx.MockRouter):
    """enable_writes=False + non-strict: skipped plugins are tolerated,
    app starts, only active (post-selection) plugins reported in healthz."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("firnline_core.plugins.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("time_management", _planning_plugin), ("fake", _FakePluginMissingModule())],
        )
        with patch("firnline_core.plugins.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("time_management", _planning_plugin)],
                skipped=[("fake", ["module 'nonexistent' not installed"])],
            )

            settings = _settings(enable_writes=False, strict_plugins=False)
            app = create_app(settings)

            with TestClient(app) as client:
                resp = client.get("/healthz")
            assert resp.status_code == 200
            # Only active (post-selection) plugins reported; skipped are not listed
            assert set(resp.json()["plugins"]) == {"time_management_tools"}
