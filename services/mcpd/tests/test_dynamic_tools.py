"""Tests for dynamic tool discovery and function building."""

from __future__ import annotations

import inspect
from typing import Any, Optional

import httpx
import pytest
import respx

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from mcpd.dynamic_tools import build_tool_function, fetch_tool_specs
from mcpd.main import create_app
from mcpd.settings import McpdSettings

# ── Helpers ─────────────────────────────────────────────────────────────────


def _configure_env(monkeypatch):
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "http://test-captured")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    monkeypatch.setenv("MCPD_REQUEST_TIMEOUT_SECONDS", "5")


def _make_create_task_spec() -> dict[str, Any]:
    """A realistic spec similar to CreateTaskArgs."""
    return {
        "name": "create_task",
        "description": "Create a new task",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                },
                "priority": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "default": None,
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "closed"],
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
            },
            "required": ["name", "status"],
        },
    }


def _make_bool_number_spec() -> dict[str, Any]:
    """Spec with boolean, number, and default values."""
    return {
        "name": "toggle_feature",
        "description": "Toggle a feature flag",
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "enabled": {"type": "boolean"},
                "threshold": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "default": 0.5,
                },
            },
            "required": ["feature", "enabled"],
        },
    }


# ── fetch_tool_specs ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_tool_specs_happy_path(monkeypatch, respx_mock: respx.MockRouter):
    """GET /v1/tools returns the tools list."""
    _configure_env(monkeypatch)
    settings = McpdSettings()  # type: ignore[call-arg]
    respx_mock.get("http://test-queryd/v1/tools").respond(
        json={"tools": [{"name": "create_task"}, {"name": "update_task"}]}
    )
    result = await fetch_tool_specs(settings)
    assert len(result) == 2
    assert result[0]["name"] == "create_task"


@pytest.mark.asyncio
async def test_fetch_tool_specs_empty_list(monkeypatch, respx_mock: respx.MockRouter):
    """GET /v1/tools returns an empty tools list (writes disabled)."""
    _configure_env(monkeypatch)
    settings = McpdSettings()  # type: ignore[call-arg]
    respx_mock.get("http://test-queryd/v1/tools").respond(
        json={"tools": []}
    )
    result = await fetch_tool_specs(settings)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_tool_specs_queryd_down(monkeypatch, respx_mock: respx.MockRouter):
    """Connection error → empty list (graceful degradation)."""
    _configure_env(monkeypatch)
    settings = McpdSettings()  # type: ignore[call-arg]
    respx_mock.get("http://test-queryd/v1/tools").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = await fetch_tool_specs(settings)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_tool_specs_http_500(monkeypatch, respx_mock: respx.MockRouter):
    """HTTP 500 → empty list."""
    _configure_env(monkeypatch)
    settings = McpdSettings()  # type: ignore[call-arg]
    respx_mock.get("http://test-queryd/v1/tools").respond(500)
    result = await fetch_tool_specs(settings)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_tool_specs_no_queryd_url(monkeypatch):
    """Empty queryd_url → returns [] immediately without HTTP call."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "http://test-captured")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    settings = McpdSettings()  # type: ignore[call-arg]
    result = await fetch_tool_specs(settings)
    assert result == []


# ── build_tool_function: signature correctness ─────────────────────────────


def test_build_tool_function_signature_create_task():
    """Generated function has the expected parameters, annotations, defaults."""
    _settings = McpdSettings(  # type: ignore[call-arg]
        queryd_url="http://q", queryd_token="t", captured_url="http://c", captured_token="ct"
    )
    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    sig = inspect.signature(fn)
    params = sig.parameters

    # name: required str
    assert params["name"].annotation is str
    assert params["name"].default is inspect.Parameter.empty

    # description: Optional[str], default None
    assert params["description"].annotation == Optional[str]
    assert params["description"].default is None

    # priority: Optional[int], default None
    assert params["priority"].annotation == Optional[int]
    assert params["priority"].default is None

    # status: required Literal
    assert str(params["status"].annotation).startswith("typing.Literal")
    assert params["status"].default is inspect.Parameter.empty

    # steps: Optional[list[dict[str, Any]]], default None
    assert params["steps"].annotation == Optional[list[dict[str, Any]]]
    assert params["steps"].default is None

    # Metadata
    assert fn.__name__ == "create_task"
    assert fn.__doc__ == "Create a new task"

    # All params should be KEYWORD_ONLY
    for p in params.values():
        assert p.kind == inspect.Parameter.KEYWORD_ONLY


def test_build_tool_function_signature_bool_number():
    """Boolean and number types map correctly; non-None defaults preserved."""
    _settings = McpdSettings(  # type: ignore[call-arg]
        queryd_url="http://q", queryd_token="t", captured_url="http://c", captured_token="ct"
    )
    spec = _make_bool_number_spec()
    fn = build_tool_function(spec, _settings)

    sig = inspect.signature(fn)
    params = sig.parameters

    assert params["feature"].annotation is str
    assert params["feature"].default is inspect.Parameter.empty

    assert params["enabled"].annotation is bool
    assert params["enabled"].default is inspect.Parameter.empty

    assert params["threshold"].annotation == Optional[float]
    assert params["threshold"].default == 0.5


# ── Schema round-trip via func_metadata ────────────────────────────────────


def test_schema_round_trip_create_task():
    """func_metadata on the generated function produces the expected JSON schema."""
    _settings = McpdSettings(  # type: ignore[call-arg]
        queryd_url="http://q", queryd_token="t", captured_url="http://c", captured_token="ct"
    )
    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    meta = func_metadata(fn)
    schema = meta.arg_model.model_json_schema()

    # Check top-level
    assert schema["type"] == "object"

    # Required fields
    assert "name" in schema["required"]
    assert "status" in schema["required"]
    assert "description" not in schema["required"]
    assert "priority" not in schema["required"]
    assert "steps" not in schema["required"]

    props = schema["properties"]

    # name → string
    assert props["name"] == {"title": "Name", "type": "string"}

    # description → nullable string
    assert props["description"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert props["description"]["default"] is None

    # priority → nullable integer
    assert props["priority"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]
    assert props["priority"]["default"] is None

    # status → string with enum
    assert props["status"]["type"] == "string"
    assert set(props["status"]["enum"]) == {"open", "in_progress", "closed"}

    # steps → nullable array of objects
    assert props["steps"]["anyOf"] == [
        {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        {"type": "null"},
    ]


def test_schema_round_trip_bool_number():
    """func_metadata round-trip for boolean and number with non-None default."""
    _settings = McpdSettings(  # type: ignore[call-arg]
        queryd_url="http://q", queryd_token="t", captured_url="http://c", captured_token="ct"
    )
    spec = _make_bool_number_spec()
    fn = build_tool_function(spec, _settings)

    meta = func_metadata(fn)
    schema = meta.arg_model.model_json_schema()

    assert schema["required"] == ["feature", "enabled"]
    props = schema["properties"]
    assert props["feature"]["type"] == "string"
    assert props["enabled"]["type"] == "boolean"
    assert props["threshold"]["anyOf"] == [
        {"type": "number"},
        {"type": "null"},
    ]
    assert props["threshold"]["default"] == 0.5


# ── build_tool_function: runtime POST behaviour ────────────────────────────


@pytest.mark.asyncio
async def test_dynamic_tool_posts_correct_payload(monkeypatch, respx_mock: respx.MockRouter):
    """Calling the generated function POSTs only provided non-None args."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    route = respx_mock.post("http://test-queryd/v1/tools/create_task").respond(
        json={"ok": True, "iri": "Task/abc"}
    )

    result = await fn(name="Buy milk", status="open", description="urgent")
    assert result == {"ok": True, "iri": "Task/abc"}
    assert route.call_count == 1

    # Only non-None args should be sent
    sent_body = route.calls.last.request.content.decode()
    import json
    payload = json.loads(sent_body)
    assert payload == {"name": "Buy milk", "status": "open", "description": "urgent"}
    # priority and steps not provided → not sent
    assert "priority" not in payload
    assert "steps" not in payload


@pytest.mark.asyncio
async def test_dynamic_tool_posts_falsy_values(monkeypatch, respx_mock: respx.MockRouter):
    """Falsy values (0, False) are sent because they are non-None."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_bool_number_spec()
    fn = build_tool_function(spec, _settings)

    route = respx_mock.post("http://test-queryd/v1/tools/toggle_feature").respond(
        json={"ok": True}
    )

    result = await fn(feature="dark_mode", enabled=False, threshold=0.0)
    assert result == {"ok": True}

    import json
    payload = json.loads(route.calls.last.request.content.decode())
    assert payload == {"feature": "dark_mode", "enabled": False, "threshold": 0.0}


@pytest.mark.asyncio
async def test_dynamic_tool_skips_none_values(monkeypatch, respx_mock: respx.MockRouter):
    """None values for optional fields are not sent."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    route = respx_mock.post("http://test-queryd/v1/tools/create_task").respond(
        json={"ok": True, "iri": "Task/xyz"}
    )

    result = await fn(name="Task 1", status="open", description=None, priority=None)
    assert result == {"ok": True, "iri": "Task/xyz"}

    import json
    payload = json.loads(route.calls.last.request.content.decode())
    assert "description" not in payload
    assert "priority" not in payload
    assert payload == {"name": "Task 1", "status": "open"}


# ── Error handling / token-leak sanitation ─────────────────────────────────


@pytest.mark.asyncio
async def test_dynamic_tool_http_422_sanitized(monkeypatch, respx_mock: respx.MockRouter):
    """HTTP 422 validation error → sanitized ToolError (no token leak)."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    respx_mock.post("http://test-queryd/v1/tools/create_task").respond(
        422, json={"detail": "Validation error: name too short"}
    )

    with pytest.raises(ToolError) as exc_info:
        await fn(name="x", status="open")
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Validation error" in error_msg


@pytest.mark.asyncio
async def test_dynamic_tool_http_500_sanitized(monkeypatch, respx_mock: respx.MockRouter):
    """HTTP 500 → sanitized ToolError (no token leak)."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    respx_mock.post("http://test-queryd/v1/tools/create_task").respond(
        500, json={"detail": "Internal error"}
    )

    with pytest.raises(ToolError) as exc_info:
        await fn(name="test", status="open")
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Internal error" in error_msg


@pytest.mark.asyncio
async def test_dynamic_tool_connect_error_sanitized(monkeypatch, respx_mock: respx.MockRouter):
    """Connection error → sanitized ToolError."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    _settings = McpdSettings()  # type: ignore[call-arg]

    spec = _make_create_task_spec()
    fn = build_tool_function(spec, _settings)

    respx_mock.post("http://test-queryd/v1/tools/create_task").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(ToolError) as exc_info:
        await fn(name="test", status="open")
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Connection refused" in error_msg


# ── build_tool_function: name sanitisation ──────────────────────────────────


def test_build_tool_function_sanitises_hyphenated_name():
    """Tool names with hyphens are converted to valid Python identifiers."""
    _settings = McpdSettings(  # type: ignore[call-arg]
        queryd_url="http://q", queryd_token="t", captured_url="http://c", captured_token="ct"
    )
    spec = {
        "name": "my-tool-name",
        "description": "A tool with hyphens",
        "input_schema": {
            "type": "object",
            "properties": {"arg": {"type": "string"}},
            "required": ["arg"],
        },
    }
    fn = build_tool_function(spec, _settings)
    # The Python function name uses underscores
    assert fn.__name__ == "my_tool_name"
    # But the tool is registered under its original name via mcp.tool(name=...)
    # so the signature check above is fine.
    sig = inspect.signature(fn)
    assert "arg" in sig.parameters


# ── create_app integration tests ───────────────────────────────────────────


def test_create_app_registers_dynamic_tools(monkeypatch, respx_mock: respx.MockRouter):
    """With 2 queryd tool specs, the MCP instance lists 8+2=10 tools."""
    _configure_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/tools").respond(
        json={
            "tools": [
                _make_create_task_spec(),
                _make_bool_number_spec(),
            ]
        }
    )

    app = create_app()
    mcp = app.state.mcp
    tools = mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}

    # 8 static + 2 dynamic = 10
    assert len(tools) == 10, f"Expected 10 tools, got {len(tools)}: {tool_names}"
    assert "create_task" in tool_names
    assert "toggle_feature" in tool_names


def test_create_app_queryd_down_still_starts(monkeypatch, respx_mock: respx.MockRouter):
    """When queryd is unreachable, the app still starts with only static tools."""
    _configure_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/tools").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    app = create_app()
    mcp = app.state.mcp
    tools = mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}

    assert len(tools) == 8, f"Expected 8 static tools, got {len(tools)}: {tool_names}"
    # Static tools are registered under their function names
    for name in ("_tool_graphql_query", "_tool_get_document", "_tool_find_entity",
                 "_tool_find_class", "_tool_find_field", "_tool_get_schema",
                 "_tool_list_modules", "_tool_capture"):
        assert name in tool_names


def test_create_app_name_collision_skipped(monkeypatch, respx_mock: respx.MockRouter):
    """A dynamic tool whose name collides with an already-registered tool is skipped."""
    _configure_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/tools").respond(
        json={
            "tools": [
                {
                    "name": "_tool_capture",  # collides with actual static tool name
                    "description": "Should be skipped",
                    "input_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                _make_create_task_spec(),
            ]
        }
    )

    app = create_app()
    mcp = app.state.mcp
    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]

    # 8 static + 1 dynamic (_tool_capture skipped) = 9
    assert len(tools) == 9, f"Expected 9 tools, got {len(tools)}: {tool_names}"
    assert "create_task" in tool_names
    # The original static _tool_capture is still there; the colliding
    # dynamic tool was not registered.
    assert tool_names.count("_tool_capture") == 1


def test_create_app_disabled_via_setting(monkeypatch, respx_mock: respx.MockRouter):
    """MCPD_ENABLE_QUERYD_TOOLS=false skips fetching entirely."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "http://test-captured")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    monkeypatch.setenv("MCPD_ENABLE_QUERYD_TOOLS", "false")

    app = create_app()
    mcp = app.state.mcp
    tools = mcp._tool_manager.list_tools()

    # Only the 8 static tools; no HTTP call to queryd was made.
    assert len(tools) == 8


def test_create_app_dynamic_tool_metadata(monkeypatch, respx_mock: respx.MockRouter):
    """Dynamic tools have correct name, description, and parameters schema."""
    _configure_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/tools").respond(
        json={"tools": [_make_create_task_spec()]}
    )

    app = create_app()
    mcp = app.state.mcp
    tool = mcp._tool_manager.get_tool("create_task")
    assert tool is not None
    assert tool.name == "create_task"
    assert "Create a new task" in tool.description
    assert tool.is_async is True
    # parameters should be a valid JSON schema
    assert "properties" in tool.parameters
    assert "name" in tool.parameters["properties"]
    assert "required" in tool.parameters
    assert "name" in tool.parameters["required"]


def test_create_app_does_not_call_queryd_when_disabled(monkeypatch, respx_mock: respx.MockRouter):
    """When enable_queryd_tools=False, no GET /v1/tools request is made."""
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "http://test-captured")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    monkeypatch.setenv("MCPD_ENABLE_QUERYD_TOOLS", "false")

    # Don't register a mock — any request would fail the test
    app = create_app()
    mcp = app.state.mcp
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 8
