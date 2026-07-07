"""Agent tools for TerminusDB operations exposed via pydantic-ai.

Read tools (always registered): get_schema_details, graphql_query,
get_document, today.  Write tools are contributed by plugins (see
``queryd.plugins``); ``build_tools`` accepts an optional list of
plugin-provided ``Tool`` objects.

Every tool records a ``ToolTraceEntry`` into ``ctx.deps.trace`` via the
``@_traced`` decorator so callers can inspect the complete tool-call
history.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from pydantic_ai import RunContext, Tool

from firnline_core.tdb import TdbClient, TdbError
from firnline_core.tooling import ToolTraceEntry, traced as _kernel_traced
from firnline_core.indexed_client import IndexedClient, IndexedError

from queryd.settings import Settings

log = structlog.get_logger()

ZURICH = ZoneInfo("Europe/Zurich")

# ---------------------------------------------------------------------------
# Re-export ToolTraceEntry (backward compat) + aliased decorator
# ---------------------------------------------------------------------------

_traced = _kernel_traced  # alias for internal use; public contract is firnline_core.tooling

# ---------------------------------------------------------------------------
# Dependency container for pydantic-ai RunContext
# ---------------------------------------------------------------------------


@dataclass
class QuerydDeps:
    """Dependencies injected into every tool via ``RunContext[QuerydDeps]``."""

    tdb: TdbClient
    settings: Settings
    schema_summary: str
    trace: list[ToolTraceEntry] = field(default_factory=list)
    prompt_briefing: str = ""
    tool_calls_used: int = 0


# ---------------------------------------------------------------------------
# GraphQL mutation guard
# ---------------------------------------------------------------------------

# TerminusDB v12.0.6 DOES expose a TerminusMutation type with
# _insertDocuments / _replaceDocuments / _deleteDocuments fields, so
# the guard below is a *load-bearing* security control — otherwise the
# agent could issue writes through GraphQL bypassing the enable_writes
# gate.

# Pattern that strips comments and string literals, leaving only
# structural GraphQL keywords to scan.
_STRIP_PATTERN = re.compile(
    r'""".*?"""'  # triple-quoted strings (non-greedy, dotall)
    r"|"
    r'"(?:[^"\\]|\\.)*"'  # double-quoted strings
    r"|"
    r"'(?:[^'\\]|\\.)*'"  # single-quoted strings (safe belt-and-braces)
    r"|"
    r"#[^\n]*",  # #-style comments to end of line
    re.DOTALL,
)

# Guards against operation definitions starting with mutation/subscription.
# Matches at document start or after a closing brace of a previous operation.
# Known residual false positive: inline fragments like `{ a { b } mutation }`
# (mutation used as a bare field name, which is harmless but syntactically odd).
_HARMFUL_KEYWORDS = re.compile(
    r"(?:^|})\s*(mutation|subscription)\b", re.IGNORECASE | re.MULTILINE
)
_HARMFUL_FUNCTIONS = [
    "_insertDocuments",
    "_replaceDocuments",
    "_deleteDocuments",
]


def _check_graphql(query: str) -> str | None:
    """Return an error message if *query* is dangerous, ``None`` otherwise."""
    stripped = _STRIP_PATTERN.sub(" ", query)
    if m := _HARMFUL_KEYWORDS.search(stripped):
        return f"Query contains prohibited keyword: {m.group()}"
    for func in _HARMFUL_FUNCTIONS:
        if func in stripped:
            return f"Query contains prohibited function: {func}"
    return None


# ---------------------------------------------------------------------------
# Read tools (always registered)
# ---------------------------------------------------------------------------


@_traced
async def get_schema_details(ctx: RunContext[QuerydDeps]) -> str:
    """Return the full TerminusDB schema reference.

    Use this to discover class names, property names, and
    relationships when self-correcting a failed GraphQL query.
    """
    return ctx.deps.schema_summary


@_traced
async def graphql_query(
    ctx: RunContext[QuerydDeps],
    query: str,
    variables: dict[str, Any] | None = None,
) -> str:
    """Execute a read-only GraphQL query against the TerminusDB database.

    Use this for queries the main get_*/list_* tools cannot express
    (aggregations, cross-type joins, path queries).  The query MUST be
    a **query** (not a mutation or subscription) — mutations are
    rejected at this layer even though TerminusDB's GraphQL endpoint
    supports them.
    """
    # ---- mutation guard ------------------------------------------------
    error = _check_graphql(query)
    if error is not None:
        return f"ERROR: {error}"

    # ---- execute with timeout -----------------------------------------
    try:
        async with asyncio.timeout(10):
            result = await ctx.deps.tdb.graphql(query, variables)
    except asyncio.TimeoutError:
        return "ERROR: GraphQL query timed out (10s)"
    except TdbError as exc:
        return f"ERROR: {exc}"

    # ---- serialize & truncate -----------------------------------------
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > 50_000:
        text = (
            text[:50_000] + "\n\u2026[TRUNCATED: response exceeded 50000 chars;"
            " refine your query with limit/filter]"
        )
    return text


@_traced
async def get_document(ctx: RunContext[QuerydDeps], iri: str) -> str:
    """Fetch a single TerminusDB document by IRI (e.g. ``Task/abc``).

    Accepts either short (``Task/abc``) or full
    (``terminusdb:///data/Task/abc``) IRIs.
    """
    try:
        doc = await ctx.deps.tdb.get_document(iri)
    except TdbError as exc:
        return f"ERROR: document not found: {iri} ({exc.status})"

    text = json.dumps(doc, ensure_ascii=False, default=str)
    if len(text) > 50_000:
        text = text[:50_000] + "\n\u2026[TRUNCATED]"
    return text


@_traced
async def today(ctx: RunContext[QuerydDeps]) -> str:
    """Return the current date and time in Europe/Zurich.

    Useful for resolving relative date expressions like "next Monday".
    """
    now = datetime.now(ZURICH)
    iso = now.isoformat(timespec="seconds")
    weekday = now.strftime("%A")
    week = now.isocalendar().week
    return f"{iso} ({weekday}, ISO week {week}, Europe/Zurich)"


# ---------------------------------------------------------------------------
# Indexed-grounded lookup tools (enabled when QUERYD_INDEXED_ENABLED=true)
# ---------------------------------------------------------------------------


@_traced
async def find_entity(
    ctx: RunContext[QuerydDeps],
    text: str,
    classes: list[str] | None = None,
    k: int = 5,
) -> str:
    """Search for known entities matching *text*.

    Use this BEFORE composing a GraphQL query. Never invent IRIs or entity
    names — always ground them here first. This tool returns candidates
    from the actual database as of the current commit.

    Returns a JSON list of candidates with their verified IRIs and scores.
    """
    settings = ctx.deps.settings
    if not settings.indexed_enabled or not settings.indexed_url:
        return "ERROR: index unavailable — fall back to graphql_query with get_schema_details"

    try:
        async with IndexedClient(
            base_url=settings.indexed_url,
            token=settings.indexed_token,
            timeout=settings.indexed_timeout_seconds,
        ) as client:
            candidates = await client.find_entity(
                text, classes=classes, branch=settings.tdb_branch, k=k
            )
    except IndexedError as e:
        return f"ERROR: index unavailable ({e.status}): {e.message} — fall back to graphql_query"

    if not candidates:
        return "No matching entities found."

    result = {"candidates": [
        {
            "iri": c.iri,
            "class": c.class_name,
            "name": c.name,
            "aliases": c.aliases,
            "score": round(c.score, 4),
            "commit_id": c.commit_id,
        }
        for c in candidates
    ]}
    return json.dumps(result, ensure_ascii=False, default=str)


@_traced
async def find_class(ctx: RunContext[QuerydDeps], text: str, k: int = 5) -> str:
    """Search for TerminusDB schema classes matching *text*.

    Use this BEFORE composing a GraphQL query to discover which class
    names exist. Never guess at class names — always ground them here.

    Returns a JSON list of matching class candidates with descriptions.
    """
    settings = ctx.deps.settings
    if not settings.indexed_enabled or not settings.indexed_url:
        return "ERROR: index unavailable — fall back to get_schema_details"

    try:
        async with IndexedClient(
            base_url=settings.indexed_url,
            token=settings.indexed_token,
            timeout=settings.indexed_timeout_seconds,
        ) as client:
            candidates = await client.find_class(text, k=k)
    except IndexedError as e:
        return f"ERROR: index unavailable ({e.status}): {e.message} — fall back to get_schema_details"

    if not candidates:
        return "No matching classes found."

    result = {"candidates": [
        {
            "class": c.class_name,
            "description": c.description,
            "score": round(c.score, 4),
        }
        for c in candidates
    ]}
    return json.dumps(result, ensure_ascii=False, default=str)


@_traced
async def find_field(
    ctx: RunContext[QuerydDeps],
    text: str,
    class_name: str | None = None,
    k: int = 5,
) -> str:
    """Search for class field/property names matching *text*.

    Use this BEFORE composing a GraphQL query to discover which field
    names exist on a class. Never guess at field names — always ground
    them here.  Optionally scope to a specific *class_name*.

    Returns a JSON list of matching field candidates with types.
    """
    settings = ctx.deps.settings
    if not settings.indexed_enabled or not settings.indexed_url:
        return "ERROR: index unavailable — fall back to get_schema_details"

    try:
        async with IndexedClient(
            base_url=settings.indexed_url,
            token=settings.indexed_token,
            timeout=settings.indexed_timeout_seconds,
        ) as client:
            candidates = await client.find_field(text, class_name=class_name, k=k)
    except IndexedError as e:
        return f"ERROR: index unavailable ({e.status}): {e.message} — fall back to get_schema_details"

    if not candidates:
        return "No matching fields found."

    result = {"candidates": [
        {
            "class": c.class_name,
            "field": c.field,
            "type": c.type,
            "description": c.description,
            "score": round(c.score, 4),
        }
        for c in candidates
    ]}
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_READ_TOOLS = [
    Tool(get_schema_details),
    Tool(graphql_query),
    Tool(get_document),
    Tool(today),
    Tool(find_entity),
    Tool(find_class),
    Tool(find_field),
]

# Extension point: future vector-search / RAG tools can be appended here.
# _READ_TOOLS.append(Tool(semantic_search))  # future: vector search service plugs in here


def build_tools(
    settings: Settings,
    plugin_tools: list[Tool] | None = None,
) -> list[Tool]:
    """Return the list of pydantic-ai ``Tool`` objects for *settings*.

    Query tools are always included; *plugin_tools* are only appended
    when ``settings.enable_writes`` is ``True``.
    """
    tools: list[Tool] = list(_READ_TOOLS)
    if settings.enable_writes and plugin_tools:
        tools.extend(plugin_tools)
    return tools
