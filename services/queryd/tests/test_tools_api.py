"""Tests for /v1/tools and /v1/tools/{name} REST endpoints.

Covers: GET listing, POST invocation, auth, validation, error handling,
timeout, and ToolSpec collision detection at startup.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from firnline_core.plugins import (
    DiscoveryResult,
    ModuleRequirement,
    PluginSelection,
)
from firnline_core.toolspec import ToolContext, ToolSpec

from firnline_ext_time_management.tools import plugin as _planning_plugin
from firnline_ext_reminders.tools import plugin as _reminders_plugin

from queryd.app import create_app
from queryd.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"

AUTH = {"Authorization": "Bearer test-token"}
GQL_PATH = f"{TDB_URL}/api/graphql/{ORG}/{TDB_DB}"
DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"


def _make_settings(**overrides) -> Settings:
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


# ---------------------------------------------------------------------------
# Context manager: app with writes enabled and real plugins (mocked discovery)
# ---------------------------------------------------------------------------


@contextmanager
def _app_with_plugins(
    respx_mock: respx.MockRouter,
    plugins: list[tuple[str, object]],
    *,
    enable_writes: bool = True,
) -> Generator[TestClient, None, None]:
    """Yield a TestClient whose lifespan discovers *plugins* via mocked
    discovery/selection, so ToolSpec collection runs during startup.
    """
    respx_mock.get(_tdb_exists_route()).respond(200)
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    settings = _make_settings(enable_writes=enable_writes)

    with patch("firnline_core.plugins.discover_plugins") as mock_disc, \
         patch("firnline_core.plugins.select_plugins") as mock_sel:

        mock_disc.return_value = DiscoveryResult(active=plugins)
        mock_sel.return_value = PluginSelection(active=plugins)
        app = create_app(settings)

        with TestClient(app) as client:
            yield client


# ---------------------------------------------------------------------------
# Context manager: app with ToolSpec override (test seam, no plugin discovery)
# ---------------------------------------------------------------------------


@contextmanager
def _app_with_tool_specs(
    respx_mock: respx.MockRouter,
    specs: dict[str, ToolSpec],
    *,
    enable_writes: bool = True,
) -> Generator[TestClient, None, None]:
    """Yield a TestClient whose app has *specs* injected via the
    ``tool_specs`` test seam — no post-startup state patching.
    """
    respx_mock.get(_tdb_exists_route()).respond(200)
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    settings = _make_settings(enable_writes=enable_writes)
    app = create_app(settings, tool_specs=specs)

    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# GET /v1/tools
# ---------------------------------------------------------------------------


def test_get_tools_lists_all_eight_tools(respx_mock: respx.MockRouter):
    """With writes enabled, GET /v1/tools returns 8 tools sorted by name."""
    plugins = [
        ("time_management", _planning_plugin),
        ("reminders", _reminders_plugin),
    ]
    with _app_with_plugins(respx_mock, plugins) as client:
        resp = client.get("/v1/tools", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    tools = data["tools"]
    assert len(tools) == 8
    names = [t["name"] for t in tools]
    assert names == sorted(names)  # sorted by name
    assert "create_reminder" in names
    assert "create_task" in names
    assert "set_task_status" in names
    assert "log_activity" in names

    # Each tool has name, description, input_schema
    for t in tools:
        assert isinstance(t["name"], str)
        assert isinstance(t["description"], str)
        assert isinstance(t["input_schema"], dict)
        assert "properties" in t["input_schema"] or "type" in t["input_schema"]


def test_get_tools_writes_disabled_returns_empty(respx_mock: respx.MockRouter):
    """With writes disabled, GET /v1/tools returns empty list."""
    plugins = [
        ("time_management", _planning_plugin),
    ]
    with _app_with_plugins(
        respx_mock, plugins, enable_writes=False
    ) as client:
        resp = client.get("/v1/tools", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert data["tools"] == []


def test_get_tools_requires_auth(respx_mock: respx.MockRouter):
    """GET /v1/tools without auth returns 401."""
    plugins = [("time_management", _planning_plugin)]
    with _app_with_plugins(respx_mock, plugins) as client:
        resp = client.get("/v1/tools")
    assert resp.status_code == 401


def test_get_tools_wrong_token(respx_mock: respx.MockRouter):
    """GET /v1/tools with wrong token returns 401."""
    plugins = [("time_management", _planning_plugin)]
    with _app_with_plugins(respx_mock, plugins) as client:
        resp = client.get(
            "/v1/tools",
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/tools/{name}
# ---------------------------------------------------------------------------


def test_post_tools_requires_auth(respx_mock: respx.MockRouter):
    """POST /v1/tools/{name} without auth returns 401."""
    plugins = [("time_management", _planning_plugin)]
    with _app_with_plugins(respx_mock, plugins) as client:
        resp = client.post("/v1/tools/create_task", json={"name": "test"})
    assert resp.status_code == 401


class _HappyArgs(BaseModel):
    name: str
    count: int = 1


async def _happy_handler(args: _HappyArgs, ctx: ToolContext) -> dict[str, object]:
    return {"ok": True, "name": args.name, "count": args.count}


_HAPPY_SPEC = ToolSpec(
    name="happy_tool",
    description="A happy tool",
    args_model=_HappyArgs,
    handler=_happy_handler,
)


def test_post_tools_happy_path(respx_mock: respx.MockRouter):
    """POST /v1/tools/happy_tool with valid args returns ok:True."""
    specs = {"happy_tool": _HAPPY_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/happy_tool",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "test"
    assert data["count"] == 1


def test_post_tools_validation_error(respx_mock: respx.MockRouter):
    """POST /v1/tools/happy_tool with missing required field → 422."""
    specs = {"happy_tool": _HAPPY_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/happy_tool",
            json={},  # missing required 'name'
            headers=AUTH,
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    assert any("name" in str(e.get("loc", [])) for e in detail)


def test_post_tools_unknown_tool(respx_mock: respx.MockRouter):
    """POST /v1/tools/nonexistent → 404."""
    specs = {"happy_tool": _HAPPY_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/nonexistent",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown tool: nonexistent"


def test_post_tools_writes_disabled_returns_404(respx_mock: respx.MockRouter):
    """With writes disabled, every tool is unknown → 404 (no tool-name leak)."""
    specs: dict[str, ToolSpec] = {}
    with _app_with_tool_specs(
        respx_mock, specs, enable_writes=False
    ) as client:
        resp = client.post(
            "/v1/tools/happy_tool",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 404
    assert "unknown tool" in resp.json()["detail"]


class _FailArgs(BaseModel):
    reason: str = "something went wrong"


async def _fail_handler(args: _FailArgs, ctx: ToolContext) -> dict[str, object]:
    return {"ok": False, "error": args.reason}


_FAIL_SPEC = ToolSpec(
    name="fail_tool",
    description="Always fails",
    args_model=_FailArgs,
    handler=_fail_handler,
)


def test_post_tools_ok_false_passthrough(respx_mock: respx.MockRouter):
    """Handler returning ok:False is passed through as 200."""
    specs = {"fail_tool": _FAIL_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/fail_tool",
            json={"reason": "bad input"},
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "bad input"


async def _crash_handler(args: BaseModel, ctx: ToolContext) -> dict[str, object]:
    raise RuntimeError("unexpected failure")


_CRASH_SPEC = ToolSpec(
    name="crash_tool",
    description="Throws unexpectedly",
    args_model=_HappyArgs,
    handler=_crash_handler,
)


def test_post_tools_handler_exception_returns_502(respx_mock: respx.MockRouter):
    """Unexpected handler exception → 502 with sanitised detail."""
    specs = {"crash_tool": _CRASH_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/crash_tool",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "tool execution failed"


def test_post_tools_invalid_json_body(respx_mock: respx.MockRouter):
    """POST with non-JSON body → 422."""
    specs = {"happy_tool": _HAPPY_SPEC}
    with _app_with_tool_specs(respx_mock, specs) as client:
        resp = client.post(
            "/v1/tools/happy_tool",
            content=b"not json",
            headers={**AUTH, "Content-Type": "application/json"},
        )

    assert resp.status_code == 422


async def _slow_handler(args: _HappyArgs, ctx: ToolContext) -> dict[str, object]:
    await asyncio.sleep(1)  # exceeds the 0.05 s timeout
    return {"ok": True}


_SLOW_SPEC = ToolSpec(
    name="slow_tool",
    description="Always times out",
    args_model=_HappyArgs,
    handler=_slow_handler,
)


def test_post_tools_handler_timeout_returns_504(respx_mock: respx.MockRouter):
    """Handler exceeding request_timeout_seconds → 504."""
    specs = {"slow_tool": _SLOW_SPEC}

    respx_mock.get(_tdb_exists_route()).respond(200)
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    settings = _make_settings(enable_writes=True, request_timeout_seconds=0.05)
    app = create_app(
        settings, tool_specs=specs,
    )

    with TestClient(app) as client:
        resp = client.post(
            "/v1/tools/slow_tool",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 504
    assert resp.json()["detail"] == "request timed out"


# ---------------------------------------------------------------------------
# Duplicate ToolSpec name collision at startup
# ---------------------------------------------------------------------------


class _DupArgs(BaseModel):
    x: int = 0


async def _dup_handler(args: _DupArgs, ctx: ToolContext) -> dict[str, object]:
    return {"ok": True}


def test_tool_spec_name_collision_startup_failure(respx_mock: respx.MockRouter):
    """Two plugins returning ToolSpec with the same name → RuntimeError."""
    class _ColliderA:
        name = "plugin_a"
        requires: list[ModuleRequirement] = []

        def tool_specs(self) -> list[Any]:
            return [
                ToolSpec(
                    name="shared_tool",
                    description="A",
                    args_model=_DupArgs,
                    handler=_dup_handler,
                )
            ]

    class _ColliderB:
        name = "plugin_b"
        requires: list[ModuleRequirement] = []

        def tool_specs(self) -> list[Any]:
            return [
                ToolSpec(
                    name="shared_tool",
                    description="B",
                    args_model=_DupArgs,
                    handler=_dup_handler,
                )
            ]

    respx_mock.get(_tdb_exists_route()).respond(200)
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    settings = _make_settings(enable_writes=True)

    plugins = [("a", _ColliderA()), ("b", _ColliderB())]

    with patch("firnline_core.plugins.discover_plugins") as mock_disc, \
         patch("firnline_core.plugins.select_plugins") as mock_sel:

        mock_disc.return_value = DiscoveryResult(active=plugins)
        mock_sel.return_value = PluginSelection(active=plugins)
        app = create_app(settings)

        with pytest.raises(RuntimeError, match="ToolSpec name collision"):
            with TestClient(app):
                pass


# ---------------------------------------------------------------------------
# Healthz reports write_tools
# ---------------------------------------------------------------------------


def test_healthz_reports_write_tools(respx_mock: respx.MockRouter):
    """GET /healthz includes write_tools list when writes are enabled."""
    plugins = [
        ("time_management", _planning_plugin),
        ("reminders", _reminders_plugin),
    ]
    respx_mock.get(DOC_PATH).respond(
        json=[
            {"@id": "SchemaModule/core", "@type": "SchemaModule", "name": "core", "version": "1.0.0"},
        ]
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(enable_writes=True)

    with patch("firnline_core.plugins.discover_plugins") as mock_disc, \
         patch("firnline_core.plugins.select_plugins") as mock_sel:

        mock_disc.return_value = DiscoveryResult(active=plugins)
        mock_sel.return_value = PluginSelection(active=plugins)
        app = create_app(settings)

        with TestClient(app) as client:
            resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.json()
    assert "write_tools" in data
    assert len(data["write_tools"]) == 8
    assert "create_task" in data["write_tools"]
    assert "create_reminder" in data["write_tools"]


def test_healthz_write_tools_empty_when_disabled(respx_mock: respx.MockRouter):
    """GET /healthz write_tools is empty when writes are disabled."""
    plugins = [("time_management", _planning_plugin)]
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(enable_writes=False)

    with patch("firnline_core.plugins.discover_plugins") as mock_disc, \
         patch("firnline_core.plugins.select_plugins") as mock_sel:

        mock_disc.return_value = DiscoveryResult(active=plugins)
        mock_sel.return_value = PluginSelection(active=plugins)
        app = create_app(settings)

        with TestClient(app) as client:
            resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.json()
    assert data["write_tools"] == []


# ---------------------------------------------------------------------------
# ToolSpec override seam: writes-disabled suppresses override
# ---------------------------------------------------------------------------


def test_tool_specs_override_suppressed_when_writes_disabled(
    respx_mock: respx.MockRouter,
):
    """When enable_writes=False, the tool_specs override is suppressed."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    respx_mock.get(DOC_PATH).respond(json=[])
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    settings = _make_settings(enable_writes=False)
    # Pass specs — but writes disabled, so they should be suppressed
    app = create_app(
        settings,
        tool_specs={"happy_tool": _HAPPY_SPEC},
    )

    with TestClient(app) as client:
        resp = client.get("/v1/tools", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["tools"] == []
