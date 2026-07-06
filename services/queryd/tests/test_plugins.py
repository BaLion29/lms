"""Tests for queryd plugin discovery, selection, capability awareness,
and healthz extension."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from pydantic_ai import Tool
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from lms_core.plugins import (
    DiscoveryResult,
    ModuleRequirement,
    PluginSelection,
)

from queryd.app import create_app, _collect_plugin_tools
from queryd.settings import Settings
from queryd.plugins.planning_tools import plugin as _planning_plugin

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
        llm_base_url="http://llm.test",
        llm_api_key="sk-test",
        llm_model="test-model",
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

    def tools(self, deps):
        return [Tool(lambda: "nope")]


def test_unmet_requirement_skipped_with_warning(respx_mock):
    """When the module registry exists but doesn't have the required
    module, the plugin is skipped with a warning — service still starts."""
    respx_mock.get(f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main").respond(
        json=[_mock_schema_module("core", "1.0.0")]
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("fake", _FakePluginMissingModule())],
        )
        with patch("queryd.app.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[],
                skipped=[("fake", ["module 'nonexistent' not installed"])],
            )

            settings = _settings(enable_writes=True)
            model = FunctionModel(
                function=lambda messages, info: ModelResponse(
                    parts=[TextPart(content="ok")]
                )
            )
            app = create_app(settings, model=model)

            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                resp = client.post(
                    "/v1/chat",
                    json={"messages": [{"role": "user", "content": "hello"}]},
                    headers={"Authorization": "Bearer test-token"},
                )
            assert resp.status_code == 200


def test_strict_mode_fails_fast_on_skipped(respx_mock):
    """strict_plugins=True raises RuntimeError when a plugin is skipped
    due to unmet requirements."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("fake", _FakePluginMissingModule())],
        )
        with patch("queryd.app.select_plugins") as mock_select:

            async def _fake_select(tdb, discovered, *, strict=False, branch="main"):
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
            model = FunctionModel(
                function=lambda messages, info: ModelResponse(
                    parts=[TextPart(content="ok")]
                )
            )

            from fastapi.testclient import TestClient

            # create_app only builds the app; the lifespan runs on
            # first request / TestClient context entry.
            with pytest.raises(RuntimeError, match="Strict plugin mode"):
                with TestClient(create_app(settings, model=model)):
                    pass


# ---------------------------------------------------------------------------
# ENABLE_WRITES=false suppresses plugin tools
# ---------------------------------------------------------------------------


def test_enable_writes_false_suppresses_plugins(respx_mock):
    """When ENABLE_WRITES=false, write-tool plugins are suppressed even
    if discovered."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("planning", _planning_plugin)],
        )

        settings = _settings(enable_writes=False)
        model = FunctionModel(
            function=lambda messages, info: ModelResponse(
                parts=[TextPart(content="ok")]
            )
        )
        app = create_app(settings, model=model)

        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            resp = client.get("/healthz")
        assert resp.status_code == 200
        # Plugins should be empty (suppressed)
        assert resp.json()["plugins"] == []


# ---------------------------------------------------------------------------
# Tool name collision fatal
# ---------------------------------------------------------------------------


class _CollidingPlugin:
    name = "collider"
    requires: list[ModuleRequirement] = []

    def tools(self, deps):
        return [Tool(lambda: "ok", name="get_document")]  # collides with core read tool


def test_tool_name_collision_with_core_fatal(respx_mock):
    """Registering a plugin tool with the same name as a core read tool
    raises RuntimeError."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("collider", _CollidingPlugin())],
        )
        with patch("queryd.app.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("collider", _CollidingPlugin())],
            )

            settings = _settings(enable_writes=True)

            from fastapi.testclient import TestClient

            with pytest.raises(RuntimeError, match="Tool name collision"):
                with TestClient(create_app(settings)):
                    pass


def test_tool_name_collision_across_plugins_fatal(respx_mock):
    """Two plugins registering the same tool name raises RuntimeError."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    class _PluginA:
        name = "a"
        requires: list[ModuleRequirement] = []

        def tools(self, deps):
            return [Tool(lambda: "ok", name="shared_tool")]

    class _PluginB:
        name = "b"
        requires: list[ModuleRequirement] = []

        def tools(self, deps):
            return [Tool(lambda: "ok", name="shared_tool")]

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("a", _PluginA()), ("b", _PluginB())],
        )
        with patch("queryd.app.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("a", _PluginA()), ("b", _PluginB())],
            )

            settings = _settings(enable_writes=True)

            from fastapi.testclient import TestClient

            with pytest.raises(RuntimeError, match="Tool name collision"):
                with TestClient(create_app(settings)):
                    pass


# ---------------------------------------------------------------------------
# Briefing contains module list (mock registry)
# ---------------------------------------------------------------------------


def test_briefing_includes_module_list(respx_mock):
    """When the module registry responds, the prompt briefing includes
    the installed-modules section."""
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
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(
        settings,
        model=model,
        plugin_tools=[],
    )

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200

    # Extract the briefing from app state
    _, prompt_briefing = app.state.briefings
    assert "Installed Schema Modules" in prompt_briefing
    assert "core 1.1.0" in prompt_briefing
    assert "planning 1.0.0" in prompt_briefing


# ---------------------------------------------------------------------------
# Healthz reports modules + active plugins
# ---------------------------------------------------------------------------


def test_healthz_reports_modules_and_plugins(respx_mock):
    """When the module registry responds, /healthz includes module
    versions and active plugin names."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"

    # Mock get_documents (for module registry — will be called twice:
    # once at startup, once by healthz live fetch)
    respx_mock.get(DOC_PATH).respond(
        json=[_mock_schema_module("core", "1.1.0"), _mock_schema_module("planning", "1.0.0")]
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )

    with patch("queryd.app.discover_plugins") as mock_discover:
        mock_discover.return_value = DiscoveryResult(
            active=[("planning", _planning_plugin)],
        )
        with patch("queryd.app.select_plugins") as mock_select:
            mock_select.return_value = PluginSelection(
                active=[("planning", _planning_plugin)],
            )

            app = create_app(settings, model=model)

            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.json()
    assert data["terminusdb"] == "up"
    assert "modules" in data
    assert data["modules"]["core"] == "1.1.0"
    assert data["modules"]["planning"] == "1.0.0"
    assert "plugins" in data
    assert "planning_tools" in data["plugins"]


# ---------------------------------------------------------------------------
# Registry-unavailable degradation
# ---------------------------------------------------------------------------


def test_registry_unavailable_graceful_degradation(respx_mock):
    """When the module registry throws TdbError, the service starts
    with modules omitted and healthz reports empty modules."""
    DOC_PATH = f"{TDB_URL}/api/document/admin/{TDB_DB}/local/branch/main"

    # get_documents raises TdbError (simulating missing SchemaModule class)
    respx_mock.get(DOC_PATH).respond(status_code=404, text="not found")
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _settings()
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    from fastapi.testclient import TestClient

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
# _collect_plugin_tools unit tests
# ---------------------------------------------------------------------------


def test_collect_plugin_tools_empty():
    tools, names = _collect_plugin_tools([], _settings(), MagicMock())
    assert tools == []
    assert names == []


def test_collect_plugin_tools_success():
    tools, names = _collect_plugin_tools(
        [("planning", _planning_plugin)], _settings(enable_writes=True), MagicMock()
    )
    assert len(tools) == 5
    assert names == ["planning_tools"]
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "set_task_status",
        "set_event_status",
        "create_task",
        "create_reminder",
        "update_task",
    }


def test_collect_plugin_tools_name_collision_with_core():
    class _Collider:
        name = "c"
        requires: list[ModuleRequirement] = []

        def tools(self, deps):
            return [Tool(lambda: "ok", name="today")]

    with pytest.raises(RuntimeError, match="Tool name collision"):
        _collect_plugin_tools([("c", _Collider())], _settings(), MagicMock())


def test_collect_plugin_tools_cross_plugin_collision():
    class _A:
        name = "a"
        requires: list[ModuleRequirement] = []

        def tools(self, deps):
            return [Tool(lambda: "ok", name="dupe")]

    class _B:
        name = "b"
        requires: list[ModuleRequirement] = []

        def tools(self, deps):
            return [Tool(lambda: "ok", name="dupe")]

    with pytest.raises(RuntimeError, match="Tool name collision"):
        _collect_plugin_tools([("a", _A()), ("b", _B())], _settings(), MagicMock())
