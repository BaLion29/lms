"""Console entrypoint for mcpd — the MCP server daemon.

Exposes firnline knowledge (documents, schema, semantic search, GraphQL,
capture, and proxied queryd write tools) as MCP tools and resources for
external AI agents.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import httpx
import structlog
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcpd._http import build_client as _build_client
from mcpd._http import raise_for_status as _raise_for_status
from mcpd.dynamic_tools import build_tool_function, fetch_tool_specs
from mcpd.settings import McpdSettings

__all__ = [
    "_build_client",
    "_raise_for_status",
    "create_app",
    "main",
]

logger = structlog.get_logger(__name__)

# ── Settings singleton ──────────────────────────────────────────────────────
# Created once in create_app(); _get_settings() falls back to a fresh instance
# when the singleton is None (useful for tests that monkeypatch env vars).

_settings: McpdSettings | None = None


def _get_settings() -> McpdSettings:
    if _settings is not None:
        return _settings
    return McpdSettings()  # type: ignore[call-arg]


# ── MCP tools ───────────────────────────────────────────────────────────────
# All tools are async and use httpx.AsyncClient to talk to backends.
# Docstrings serve as tool descriptions for LLM consumers.


async def _tool_graphql_query(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a read-only GraphQL query against the firnline knowledge graph.

    This is the most flexible way to query firnline. Use GraphQL introspection
    (via ``get_schema``) to discover available types and fields before writing
    queries. Mutations are rejected by the queryd backend.

    Args:
        query: A GraphQL query string (read-only — mutations will be rejected).
        variables: Optional variable bindings for the query. Defaults to None.
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.post("/v1/graphql", json={"query": query, "variables": variables or {}})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.json()


async def _tool_get_document(iri: str) -> dict[str, Any]:
    """Retrieve a single document by its IRI (identifier).

    The IRI may contain slashes (e.g. ``Task/abc123``). Returns the full document
    dict, or raises an error if the document is not found.

    Args:
        iri: The document IRI (with or without leading/trailing slashes).
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        iri_stripped = iri.strip("/")
        try:
            resp = await client.get(f"/v1/documents/{iri_stripped}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        if resp.status_code == 404:
            raise ToolError(f"Document not found: {iri}")
        _raise_for_status(resp)
        return resp.json()


async def _tool_find_entity(text: str, classes: list[str] | None = None, k: int = 5) -> dict[str, Any]:
    """Semantic search for entities (documents) in the knowledge graph.

    Searches across entity names, aliases, and descriptions using a vector index.
    If the semantic index is disabled on the server, returns a descriptive error.

    Args:
        text: Free-text search query.
        classes: Optional list of class names to filter results by (e.g. ``["Task"]``).
        k: Maximum number of results to return (default 5).
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.post("/v1/find/entity", json={"text": text, "classes": classes, "k": k})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        if resp.status_code == 503:
            raise ToolError("Semantic index is disabled. Enable it by setting QUERYD_INDEXED_ENABLED=true.")
        _raise_for_status(resp)
        return resp.json()


async def _tool_find_class(text: str, k: int = 5) -> dict[str, Any]:
    """Semantic search for document classes in the knowledge graph.

    Useful when you are unsure which class name to use for further queries.

    Args:
        text: Free-text search query describing the class you are looking for.
        k: Maximum number of results to return (default 5).
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.post("/v1/find/class", json={"text": text, "k": k})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        if resp.status_code == 503:
            raise ToolError("Semantic index is disabled. Enable it by setting QUERYD_INDEXED_ENABLED=true.")
        _raise_for_status(resp)
        return resp.json()


async def _tool_find_field(text: str, class_name: str | None = None, k: int = 5) -> dict[str, Any]:
    """Semantic search for fields/properties of document classes.

    Helps discover which fields exist on a class before writing GraphQL queries.

    Args:
        text: Free-text search query describing the field you are looking for.
        class_name: Optional class name to scope the field search to a specific class.
        k: Maximum number of results to return (default 5).
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.post("/v1/find/field", json={"text": text, "class_name": class_name, "k": k})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        if resp.status_code == 503:
            raise ToolError("Semantic index is disabled. Enable it by setting QUERYD_INDEXED_ENABLED=true.")
        _raise_for_status(resp)
        return resp.json()


async def _tool_get_schema() -> str:
    """Return a human-readable summary of the firnline schema.

    Describes available document classes, their fields, and relationships.
    Use this to orient yourself before writing GraphQL queries.
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.get("/v1/schema")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        data = resp.json()
        return data.get("summary", json.dumps(data))


async def _tool_list_modules() -> list[dict[str, Any]]:
    """List all installed schema modules with their metadata.

    Returns a list of modules with name, version, origin, description, exports, etc.
    Use this to understand what knowledge domains are covered by the current firnline instance.
    """
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.get("/v1/modules")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.json()


async def _tool_capture(text: str) -> dict[str, Any]:
    """Capture new text into firnline as a note.

    This is the primary write path — it creates a new text note document via the
    captured service and returns the document ID.

    Args:
        text: The text content to capture.
    """
    settings = _get_settings()
    async with _build_client(settings.captured_url, settings.captured_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.post("/v1/capture/note", json={"text": text})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.json()


# ── Resource callbacks (async, invoked inside the MCP event loop) ───────────


async def _resource_schema() -> str:
    """firnline://schema — human-readable schema summary."""
    return await _tool_get_schema()


async def _resource_schema_introspection() -> str:
    """firnline://schema/introspection — raw introspection JSON."""
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.get("/v1/schema/introspection")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.text


async def _resource_modules() -> str:
    """firnline://modules — JSON list of installed modules."""
    settings = _get_settings()
    async with _build_client(settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds) as client:
        try:
            resp = await client.get("/v1/modules")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.text


# ── App construction ────────────────────────────────────────────────────────


def create_app() -> Starlette:
    """Build the Starlette application with MCP + healthz."""
    global _settings
    settings = McpdSettings()  # type: ignore[call-arg]
    _settings = settings

    # ── Configure structlog ─────────────────────────────────────────────────
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    mcp = FastMCP(
        "firnline",
        json_response=True,
        stateless_http=True,
        instructions=(
            "Firnline is a personal knowledge system. Use the provided tools to query "
            "documents, search the schema, run GraphQL queries, and capture new "
            "knowledge. All read operations go through queryd. The capture tool "
            "writes to captured. When queryd has writes enabled, structured write "
            "tools (e.g. create_task, update_task, log_activity) are proxied from "
            "queryd and listed alongside the built-in tools."
        ),
    )

    # Register static tools
    mcp.tool()(_tool_graphql_query)
    mcp.tool()(_tool_get_document)
    mcp.tool()(_tool_find_entity)
    mcp.tool()(_tool_find_class)
    mcp.tool()(_tool_find_field)
    mcp.tool()(_tool_get_schema)
    mcp.tool()(_tool_list_modules)
    mcp.tool()(_tool_capture)

    # Register dynamic tools from queryd (when enabled)
    if settings.enable_queryd_tools:
        try:
            specs = asyncio.run(fetch_tool_specs(settings))
        except RuntimeError:
            # Event loop already running (e.g. inside a test fixture or
            # nested app construction).  Skip dynamic registration gracefully
            # instead of crashing.
            logger.warning(
                "Cannot fetch dynamic tools: event loop already running. "
                "Skipping queryd tool registration."
            )
            specs = []

        # Query the ToolManager for names already registered so we never
        # accidentally overwrite (or warn-duplicate) a static tool.
        existing_names = {t.name for t in mcp._tool_manager.list_tools()}

        for spec in specs:
            tool_name = spec.get("name", "")
            if not tool_name:
                logger.warning("Skipping dynamic tool spec without a name")
                continue
            if tool_name in existing_names:
                logger.warning(
                    "Skipping dynamic tool %s: name collides with existing tool",
                    tool_name,
                )
                continue
            try:
                fn = build_tool_function(spec, settings)
            except Exception:
                logger.warning(
                    "Failed to build function for dynamic tool %s",
                    tool_name,
                    exc_info=True,
                )
                continue
            mcp.tool(name=tool_name, description=spec.get("description", ""))(fn)
            existing_names.add(tool_name)
            logger.info("Registered dynamic tool: %s", tool_name)

    # Register resources
    mcp.resource("firnline://schema")(_resource_schema)
    mcp.resource("firnline://schema/introspection")(_resource_schema_introspection)
    mcp.resource("firnline://modules")(_resource_modules)

    # ── Health check ────────────────────────────────────────────────────────
    async def healthz(request):
        return JSONResponse({"status": "ok"})

    # ── Mount MCP + healthz on a Starlette app ──────────────────────────────
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            yield

    app = Starlette(
        routes=[
            Route("/healthz", healthz),
            Mount("/", mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mcp = mcp
    return app


def main() -> None:
    """Run the MCP daemon via uvicorn."""
    import uvicorn

    settings = _get_settings()
    app = create_app()
    uvicorn.run(app, host=settings.host, port=settings.port)
