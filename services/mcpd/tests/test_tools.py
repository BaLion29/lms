"""Tests for mcpd tool functions using mocked backends via respx."""

import json

import httpx
import pytest
import respx

from mcpd.main import (
    _raise_for_status,
    _resource_modules,
    _resource_schema,
    _resource_schema_introspection,
    _tool_capture,
    _tool_create_document,
    _tool_find_class,
    _tool_find_entity,
    _tool_find_field,
    _tool_get_document,
    _tool_get_schema,
    _tool_graphql_query,
    _tool_list_modules,
    _tool_update_document,
)
from mcp.server.fastmcp.exceptions import ToolError


# ── Helpers ─────────────────────────────────────────────────────────────────


def _configure_default_env(monkeypatch):
    monkeypatch.setenv("MCPD_QUERYD_URL", "http://test-queryd")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "http://test-captured")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    monkeypatch.setenv("MCPD_REQUEST_TIMEOUT_SECONDS", "5")


# ── graphql_query ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graphql_query_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/graphql").respond(
        json={"data": {"Task": [{"_id": "Task/1", "name": "test"}]}}
    )
    result = await _tool_graphql_query(query="query { Task { _id name } }")
    assert result["data"]["Task"][0]["_id"] == "Task/1"


@pytest.mark.asyncio
async def test_graphql_query_400_mutation_rejected(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/graphql").respond(
        400, json={"detail": "Mutations are not allowed in read-only mode"}
    )
    with pytest.raises(ToolError, match="Mutations are not allowed"):
        await _tool_graphql_query(query="mutation { ... }")


# ── get_document ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_document_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/documents/Task/abc").respond(
        json={"_id": "Task/abc", "name": "Test task"}
    )
    result = await _tool_get_document("Task/abc")
    assert result["_id"] == "Task/abc"


@pytest.mark.asyncio
async def test_get_document_404(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/documents/Task/xyz").respond(404)
    with pytest.raises(ToolError, match="Document not found"):
        await _tool_get_document("Task/xyz")


# ── find_entity ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_entity_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/entity").respond(
        json={"candidates": [{"iri": "Task/1", "class": "Task", "name": "Buy milk"}]}
    )
    result = await _tool_find_entity("milk", classes=["Task"], k=3)
    assert result["candidates"][0]["name"] == "Buy milk"


@pytest.mark.asyncio
async def test_find_entity_503_disabled(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/entity").respond(503)
    with pytest.raises(ToolError, match="Semantic index is disabled"):
        await _tool_find_entity("milk")


# ── find_class ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_class_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/class").respond(
        json={"candidates": [{"name": "Task", "label": "Task"}]}
    )
    result = await _tool_find_class("task", k=3)
    assert result["candidates"][0]["name"] == "Task"


@pytest.mark.asyncio
async def test_find_class_503_disabled(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/class").respond(503)
    with pytest.raises(ToolError, match="Semantic index is disabled"):
        await _tool_find_class("task")


# ── find_field ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_field_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/field").respond(
        json={"candidates": [{"name": "title", "label": "Title"}]}
    )
    result = await _tool_find_field("title", class_name="Task", k=5)
    assert result["candidates"][0]["name"] == "title"


@pytest.mark.asyncio
async def test_find_field_503_disabled(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/find/field").respond(503)
    with pytest.raises(ToolError, match="Semantic index is disabled"):
        await _tool_find_field("title")


# ── get_schema ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_schema_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema").respond(
        json={"summary": "Schema with Task, Project, Note"}
    )
    result = await _tool_get_schema()
    assert "Task" in result


# ── list_modules ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_modules_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/modules").respond(
        json=[
            {"name": "core", "version": "1.0", "origin": "firnline", "description": "Core schema"},
        ]
    )
    result = await _tool_list_modules()
    assert len(result) == 1
    assert result[0]["name"] == "core"


# ── capture ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_success(monkeypatch, respx_mock: respx.MockRouter):
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-captured/v1/capture/note").respond(
        json={"id": "Note/xyz", "kind": "note"}
    )
    result = await _tool_capture("Hello firnline")
    assert result["id"] == "Note/xyz"


# ── create_document ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_document_success(monkeypatch, respx_mock: respx.MockRouter):
    """POST /v1/documents/{class_name} with valid fields → 201, returns iri."""
    _configure_default_env(monkeypatch)
    route = respx_mock.post("http://test-queryd/v1/documents/Task").respond(
        status_code=201, json={"iri": "Task/abc"}
    )
    result = await _tool_create_document(
        class_name="Task", fields={"name": "Review PR", "priority": 3}
    )
    assert result["iri"] == "Task/abc"
    # Verify the request body and default agent header
    assert route.call_count == 1
    req = route.calls.last.request
    assert req.headers["X-Firnline-Agent"] == "ext:mcp"
    assert json.loads(req.read()) == {"name": "Review PR", "priority": 3}


@pytest.mark.asyncio
async def test_create_document_custom_agent(monkeypatch, respx_mock: respx.MockRouter):
    """Explicit agent overrides the default ext:mcp header."""
    _configure_default_env(monkeypatch)
    route = respx_mock.post("http://test-queryd/v1/documents/Task").respond(
        status_code=201, json={"iri": "Task/xyz"}
    )
    result = await _tool_create_document(
        class_name="Task",
        fields={"name": "test"},
        agent="user:basti",
    )
    assert result["iri"] == "Task/xyz"
    req = route.calls.last.request
    assert req.headers["X-Firnline-Agent"] == "user:basti"


@pytest.mark.asyncio
async def test_create_document_422_propagates_detail(monkeypatch, respx_mock: respx.MockRouter):
    """422 body invalid (schema rejection) detail reaches the calling agent."""
    _configure_default_env(monkeypatch)
    detail_msg = 'Field "priority" must be an integer, got string'
    respx_mock.post("http://test-queryd/v1/documents/Task").respond(
        status_code=422, json={"detail": detail_msg}
    )
    with pytest.raises(ToolError, match=detail_msg):
        await _tool_create_document(
            class_name="Task", fields={"name": "test", "priority": "high"}
        )


@pytest.mark.asyncio
async def test_create_document_connection_error(monkeypatch, respx_mock: respx.MockRouter):
    """Connection errors are caught and raised as ToolError."""
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/documents/Task").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(ToolError, match="Connection refused"):
        await _tool_create_document(
            class_name="Task", fields={"name": "test"}
        )


@pytest.mark.asyncio
async def test_create_document_400_bad_class_name(monkeypatch, respx_mock: respx.MockRouter):
    """400 for unknown class_name propagates actionable detail to the caller."""
    _configure_default_env(monkeypatch)
    detail_msg = "Invalid class name: 'BogusClass'"
    respx_mock.post("http://test-queryd/v1/documents/BogusClass").respond(
        status_code=400, json={"detail": detail_msg}
    )
    with pytest.raises(ToolError, match=detail_msg):
        await _tool_create_document(
            class_name="BogusClass", fields={"name": "test"}
        )


@pytest.mark.asyncio
async def test_create_document_error_never_leaks_token(monkeypatch, respx_mock: respx.MockRouter):
    """When create_document fails with a 500, the queryd token must never leak."""
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-queryd/v1/documents/Task").respond(
        500, json={"detail": "Internal server error"}
    )
    with pytest.raises(ToolError) as exc_info:
        await _tool_create_document(
            class_name="Task", fields={"name": "test"}
        )
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Internal server error" in error_msg


# ── update_document ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_document_success(monkeypatch, respx_mock: respx.MockRouter):
    """PUT /v1/documents/{iri} with valid fields → 200, returns iri."""
    _configure_default_env(monkeypatch)
    route = respx_mock.put("http://test-queryd/v1/documents/Task/abc").respond(
        status_code=200, json={"iri": "Task/abc"}
    )
    result = await _tool_update_document(
        iri="Task/abc", fields={"name": "Updated", "priority": 2}
    )
    assert result["iri"] == "Task/abc"
    assert route.call_count == 1
    req = route.calls.last.request
    assert req.headers["X-Firnline-Agent"] == "ext:mcp"
    assert json.loads(req.read()) == {"name": "Updated", "priority": 2}


@pytest.mark.asyncio
async def test_update_document_custom_agent(monkeypatch, respx_mock: respx.MockRouter):
    """Explicit agent overrides the default ext:mcp header."""
    _configure_default_env(monkeypatch)
    route = respx_mock.put("http://test-queryd/v1/documents/Task/xyz").respond(
        status_code=200, json={"iri": "Task/xyz"}
    )
    result = await _tool_update_document(
        iri="Task/xyz",
        fields={"name": "test"},
        agent="user:basti",
    )
    assert result["iri"] == "Task/xyz"
    req = route.calls.last.request
    assert req.headers["X-Firnline-Agent"] == "user:basti"


@pytest.mark.asyncio
async def test_update_document_strips_leading_trailing_slash(monkeypatch, respx_mock: respx.MockRouter):
    """Leading/trailing slashes on the IRI are stripped."""
    _configure_default_env(monkeypatch)
    route = respx_mock.put("http://test-queryd/v1/documents/Task/abc").respond(
        status_code=200, json={"iri": "Task/abc"}
    )
    result = await _tool_update_document(
        iri="/Task/abc/", fields={"name": "test"}
    )
    assert result["iri"] == "Task/abc"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_update_document_404_not_found(monkeypatch, respx_mock: respx.MockRouter):
    """404 from queryd propagates to ToolError with detail."""
    _configure_default_env(monkeypatch)
    respx_mock.put("http://test-queryd/v1/documents/Task/nope").respond(
        404, json={"detail": "Document not found: Task/nope"}
    )
    with pytest.raises(ToolError, match="Document not found"):
        await _tool_update_document(iri="Task/nope", fields={"name": "test"})


@pytest.mark.asyncio
async def test_update_document_422_propagates_detail(monkeypatch, respx_mock: respx.MockRouter):
    """422 body invalid detail reaches the calling agent."""
    _configure_default_env(monkeypatch)
    detail_msg = 'Field "priority" must be an integer, got string'
    respx_mock.put("http://test-queryd/v1/documents/Task/abc").respond(
        422, json={"detail": detail_msg}
    )
    with pytest.raises(ToolError, match=detail_msg):
        await _tool_update_document(
            iri="Task/abc", fields={"priority": "high"}
        )


@pytest.mark.asyncio
async def test_update_document_connection_error(monkeypatch, respx_mock: respx.MockRouter):
    """Connection errors are caught and raised as ToolError."""
    _configure_default_env(monkeypatch)
    respx_mock.put("http://test-queryd/v1/documents/Task/abc").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(ToolError, match="Connection refused"):
        await _tool_update_document(iri="Task/abc", fields={"name": "test"})


@pytest.mark.asyncio
async def test_update_document_error_never_leaks_token(monkeypatch, respx_mock: respx.MockRouter):
    """When update_document fails with a 500, the queryd token must never leak."""
    _configure_default_env(monkeypatch)
    respx_mock.put("http://test-queryd/v1/documents/Task/abc").respond(
        500, json={"detail": "Internal server error"}
    )
    with pytest.raises(ToolError) as exc_info:
        await _tool_update_document(iri="Task/abc", fields={"name": "test"})
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Internal server error" in error_msg


# ── Connection error handling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backend_connection_error(monkeypatch, respx_mock: respx.MockRouter):
    """Connection errors are caught and raised as sanitized ToolError."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(ToolError, match="Connection refused"):
        await _tool_get_schema()


# ── Sanitized error — no token leak ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_error_never_leaks_token(monkeypatch, respx_mock: respx.MockRouter):
    """When the backend returns an HTTP error, the token must never appear."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema").respond(
        500, json={"detail": "Internal server error"}
    )
    with pytest.raises(ToolError) as exc_info:
        await _tool_get_schema()
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg


@pytest.mark.asyncio
async def test_connect_error_never_leaks_token(monkeypatch, respx_mock: respx.MockRouter):
    """When connection fails, the token must never appear in the error message."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(ToolError) as exc_info:
        await _tool_get_schema()
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg


@pytest.mark.asyncio
async def test_capture_error_never_leaks_token(monkeypatch, respx_mock: respx.MockRouter):
    """Errors from the captured backend also sanitize token."""
    _configure_default_env(monkeypatch)
    respx_mock.post("http://test-captured/v1/capture/note").respond(
        500, json={"detail": "Boom"}
    )
    with pytest.raises(ToolError) as exc_info:
        await _tool_capture("test")
    error_msg = str(exc_info.value)
    assert "c-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "Boom" in error_msg


# ── _raise_for_status unit ──────────────────────────────────────────────────


def test_raise_for_status_extracts_detail():
    """_raise_for_status uses the backend 'detail' field for the error message."""
    import httpx
    resp = httpx.Response(500, json={"detail": "custom backend error"}, request=httpx.Request("GET", "http://x"))
    with pytest.raises(ToolError, match="custom backend error"):
        _raise_for_status(resp)


def test_raise_for_status_no_detail_falls_back_to_status():
    """When no 'detail' key, falls back to HTTP status code message."""
    import httpx
    resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    with pytest.raises(ToolError, match="HTTP 503"):
        _raise_for_status(resp)


# ── Resource callbacks (async) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_schema(monkeypatch, respx_mock: respx.MockRouter):
    """firnline://schema returns the schema summary."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema").respond(
        json={"summary": "Schema summary text"}
    )
    result = await _resource_schema()
    assert "Schema summary text" == result


@pytest.mark.asyncio
async def test_resource_schema_introspection(monkeypatch, respx_mock: respx.MockRouter):
    """firnline://schema/introspection returns raw introspection JSON."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema/introspection").respond(
        text='{"data":{"__schema":{}}}'
    )
    result = await _resource_schema_introspection()
    assert "__schema" in result


@pytest.mark.asyncio
async def test_resource_modules(monkeypatch, respx_mock: respx.MockRouter):
    """firnline://modules returns the modules JSON array."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/modules").respond(
        json=[{"name": "core", "version": "1.0"}]
    )
    result = await _resource_modules()
    parsed = json.loads(result)
    assert parsed[0]["name"] == "core"


@pytest.mark.asyncio
async def test_resource_error_is_sanitized(monkeypatch, respx_mock: respx.MockRouter):
    """Resource HTTP errors are sanitized like tool errors."""
    _configure_default_env(monkeypatch)
    respx_mock.get("http://test-queryd/v1/schema/introspection").respond(500, json={"detail": "fail"})
    with pytest.raises(ToolError) as exc_info:
        await _resource_schema_introspection()
    error_msg = str(exc_info.value)
    assert "q-token" not in error_msg
    assert "Bearer" not in error_msg
    assert "fail" in error_msg
