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
from firnline_core.logging import configure_logging
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
            resp = await client.post(
                "/v1/capture/note",
                content=text,
                headers={"Content-Type": "text/plain"},
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.json()


async def _tool_create_document(
    class_name: str, fields: dict[str, Any], agent: str | None = None
) -> dict[str, Any]:
    """Create a structured document of a known schema class directly — no LLM extraction.

    Use this when you already know the exact field values for a document.
    Unlike ``capture`` (which routes free text through LLM extraction), this
    tool writes a structured document straight to the knowledge graph.  Use
    ``get_schema`` to discover available classes and their fields before
    calling this tool.

    Args:
        class_name: The document class name (e.g. ``Task``, ``Person``).  Must
            match an existing schema class exactly (case-sensitive).
        fields: A JSON object whose keys are the class field names as defined
            in the schema.  Do **not** include ``@type`` or ``@id`` — both are
            server-assigned from the class name and must not appear in the body.
        agent: Optional provenance agent identity string.  Grammar:
            ``service:<name>``, ``user:<name>``, or ``ext:<name>``.  When
            omitted the call is attributed to ``ext:mcp`` so the origin is
            correctly recorded as an external agent.

    Returns:
        A dict with the single key ``iri`` whose value is the created
        document's IRI (e.g. ``{"iri": "Task/abc123"}``).
    """
    settings = _get_settings()
    async with _build_client(
        settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds
    ) as client:
        headers = {"X-Firnline-Agent": agent} if agent else {"X-Firnline-Agent": "ext:mcp"}
        try:
            resp = await client.post(
                f"/v1/documents/{class_name}", json=fields, headers=headers
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ToolError(str(e)) from None
        _raise_for_status(resp)
        return resp.json()


async def _tool_update_document(
    iri: str, fields: dict[str, Any], agent: str | None = None
) -> dict[str, Any]:
    """Update an existing document's fields directly — no LLM extraction.

    Use this to modify a document when you know the exact field values to
    change.  Only the fields you provide are updated; all other fields
    remain unchanged.  The ``@type`` and ``@id`` of the document cannot
    be changed.  Use ``get_document`` to inspect the current state before
    calling this tool, and ``get_schema`` to discover which fields exist.

    Args:
        iri: The document IRI (e.g. ``Task/abc123``).
        fields: A JSON object containing only the fields you want to
            update (partial update).  Do **not** include ``@type`` or
            ``@id`` — both are immutable.
        agent: Optional provenance agent identity string.  Grammar:
            ``service:<name>``, ``user:<name>``, or ``ext:<name>``.  When
            omitted the call is attributed to ``ext:mcp``.

    Returns:
        A dict with the single key ``iri`` whose value is the updated
        document's IRI (e.g. ``{"iri": "Task/abc123"}``).
    """
    settings = _get_settings()
    async with _build_client(
        settings.queryd_url, settings.queryd_token, settings.request_timeout_seconds
    ) as client:
        headers = {"X-Firnline-Agent": agent} if agent else {"X-Firnline-Agent": "ext:mcp"}
        iri_stripped = iri.strip("/")
        try:
            resp = await client.put(
                f"/v1/documents/{iri_stripped}", json=fields, headers=headers
            )
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


# ── Dynamic tool registration helpers ────────────────────────────────────────


def _register_dynamic_tools(mcp: Any, settings: McpdSettings, specs: list[dict[str, Any]]) -> int:
    """Register dynamic tool specs with *mcp*.  Returns count of newly registered tools.

    Skips specs whose names collide with already-registered tools (static or
    previously-registered dynamic).
    """
    existing_names = {t.name for t in mcp._tool_manager.list_tools()}
    registered = 0
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
        registered += 1
    return registered


async def _register_dynamic_tools_with_retry(
    mcp: Any,
    settings: McpdSettings,
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
) -> None:
    """Fetch and register queryd write tools with retry-backoff.

    Only called via a background task from the lifespan.  Logs a warning
    if all attempts are exhausted without a successful fetch.
    """
    for attempt in range(max_attempts):
        try:
            specs = await fetch_tool_specs(settings)
        except Exception:  # pragma: no cover — safety net
            logger.warning(
                "Dynamic tool fetch attempt %d/%d raised",
                attempt + 1,
                max_attempts,
                exc_info=True,
            )
            if attempt == max_attempts - 1:
                logger.warning(
                    "Failed to fetch dynamic tools after %d attempts",
                    max_attempts,
                )
                return
        else:
            if specs:
                registered = _register_dynamic_tools(mcp, settings, specs)
                if registered:
                    logger.info(
                        "Registered %d dynamic tool(s) via background fetch",
                        registered,
                    )
            return  # success — empty list is still success

        if attempt < max_attempts - 1:
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)


# ── App construction ────────────────────────────────────────────────────────


def create_mcp_component(
    settings: McpdSettings | None = None,
) -> tuple[Any, Any, Any]:
    """Build the MCP sub-application for embedding in a combined app.

    Returns ``(asgi_app, lifespan, mcp)`` where *asgi_app* is a Starlette
    app containing a ``/healthz`` route and the MCP streamable HTTP
    application mounted at the root, *lifespan* is an async context
    manager that runs the MCP session manager and starts a background
    task for dynamic tool registration, and *mcp* is the FastMCP
    instance (useful for tests that inspect registered tools).

    Does **not** call ``configure_logging`` — the host is responsible
    for configuring logging.
    """
    global _settings
    if settings is None:
        settings = McpdSettings()  # type: ignore[call-arg]
    _settings = settings

    mcp = FastMCP(
        "firnline",
        json_response=True,
        stateless_http=True,
        streamable_http_path="/",
        instructions=(
            "Firnline is a personal knowledge system. Use the provided tools to query "
            "documents, search the schema, run GraphQL queries, and write new "
            "knowledge. All read operations go through queryd. Unstructured writes "
            "go through captured; structured writes go through create_document. "
            "When queryd has write-tool plugins enabled, additional structured write "
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
    mcp.tool()(_tool_create_document)
    mcp.tool()(_tool_update_document)

    # Register resources (static — no async deps needed)
    mcp.resource("firnline://schema")(_resource_schema)
    mcp.resource("firnline://schema/introspection")(_resource_schema_introspection)
    mcp.resource("firnline://modules")(_resource_modules)

    # ── Best-effort synchronous dynamic tool fetch ────────────────────────
    # Works when queryd is already reachable (standalone mode, tests).
    # Falls back to the lifespan retry on ConnectError (in-process apid mode).
    _dynamic_registered = False
    if settings.enable_queryd_tools:
        try:
            specs = asyncio.run(fetch_tool_specs(settings))
        except RuntimeError:
            logger.warning(
                "Cannot fetch dynamic tools: event loop already running. "
                "Skipping queryd tool registration."
            )
            specs = []
        else:
            if specs:
                _register_dynamic_tools(mcp, settings, specs)
            _dynamic_registered = True

    # ── Build the inner ASGI app (MCP + healthz) ─────────────────────────
    mcp_streamable = mcp.streamable_http_app()

    # ── Health check endpoint ────────────────────────────────────────────
    async def healthz(request):
        return JSONResponse({"status": "ok"})

    # ── Wrap MCP streamable + /healthz in a Starlette ────────────────────
    wrapped = Starlette(
        routes=[
            Route("/healthz", healthz),
            Mount("/", mcp_streamable),
        ],
    )

    # ── Lifespan for the outer caller (includes session + dynamic tools) ──
    @contextlib.asynccontextmanager
    async def lifespan(app: Any):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())

            # If the synchronous fetch didn't register any dynamic tools
            # (e.g. in-process deployment where queryd isn't listening yet),
            # start a background retry task.
            _dynamic_task: asyncio.Task | None = None
            if settings.enable_queryd_tools and not _dynamic_registered:
                _dynamic_task = asyncio.create_task(
                    _register_dynamic_tools_with_retry(mcp, settings)
                )

            try:
                yield
            finally:
                if _dynamic_task is not None:
                    _dynamic_task.cancel()
                    try:
                        await _dynamic_task
                    except asyncio.CancelledError:
                        pass

    return wrapped, lifespan, mcp


def create_app(settings: McpdSettings | None = None) -> Starlette:
    """Build the Starlette application with MCP + healthz.

    Accepts an optional *settings* instance.  When omitted a fresh
    ``McpdSettings()`` is constructed so that the function remains usable
    as a uvicorn ASGI factory (e.g. ``uvicorn.run("mcpd.main:create_app")``).
    """
    if settings is None:
        settings = McpdSettings()  # type: ignore[call-arg]

    # ── Configure structlog ─────────────────────────────────────────────────
    configure_logging(settings.log_level)

    asgi_app, mcp_lifespan, mcp = create_mcp_component(settings)

    # ── Mount MCP + healthz (healthz is provided by create_mcp_component) ───
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp_lifespan(app):
            yield

    app = Starlette(
        routes=[
            Mount("/", asgi_app),
        ],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mcp = mcp
    return app


def main() -> None:
    """Run the MCP daemon via uvicorn."""
    import uvicorn

    settings = McpdSettings()  # type: ignore[call-arg]
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
