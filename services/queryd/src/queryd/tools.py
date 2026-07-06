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
import functools
import inspect
import json
import re
import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel
from pydantic_ai import RunContext, Tool

from lms_core.models import _format_datetime
from lms_core.tdb import TdbClient, TdbError

from queryd.settings import Settings

log = structlog.get_logger()

ZURICH = ZoneInfo("Europe/Zurich")

# ---------------------------------------------------------------------------
# Shared request / response models
# ---------------------------------------------------------------------------


class ToolTraceEntry(BaseModel):
    """Single tool invocation recorded for observability."""

    tool: str
    input: dict[str, object]
    output_summary: str


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
# Tracing wrapper
# ---------------------------------------------------------------------------


def _traced(func):
    """Decorator: append exactly one ``ToolTraceEntry`` per tool call.

    Traced functions must accept ``ctx: RunContext[QuerydDeps]`` as
    their **first positional argument**.  All remaining keyword
    arguments are recorded in the trace entry (values longer than 200
    chars are truncated).
    """
    sig = inspect.signature(func)
    # Parameter names after 'ctx' (the first positional param)
    param_names = [
        p
        for p in sig.parameters
        if p != "ctx"
        and sig.parameters[p].kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx: RunContext[QuerydDeps] = args[0]

        # Soft iteration cap: refuse execution if budget exhausted.
        ctx.deps.tool_calls_used += 1
        _BUDGET_EXHAUSTED = (
            "Tool-call budget exhausted. "
            "Answer the user now with the information you already have."
        )
        if ctx.deps.tool_calls_used > ctx.deps.settings.max_tool_iterations:
            # Record the refusal as a trace entry for debuggability.
            ctx.deps.trace.append(
                ToolTraceEntry(
                    tool=func.__name__,
                    input={},
                    output_summary="budget exhausted",
                )
            )
            # Return a suitable value for the tool's declared output type.
            # Write tools return dict; read tools return str.
            return_hint = inspect.signature(func).return_annotation
            if return_hint is dict or typing.get_origin(return_hint) is dict:
                return {"ok": False, "error": _BUDGET_EXHAUSTED}
            return _BUDGET_EXHAUSTED

        # Merge positional and keyword args into a single kwargs dict
        # for tracing purposes.
        all_kwargs: dict[str, Any] = dict(kwargs)
        for i, name in enumerate(param_names):
            if name not in all_kwargs and i < len(args) - 1:
                all_kwargs[name] = args[i + 1]

        input_dict: dict[str, object] = {}
        for k, v in all_kwargs.items():
            s = str(v)
            if len(s) > 200:
                s = s[:200] + "\u2026"
            input_dict[k] = s

        result = await func(*args, **kwargs)

        # Derive a one-line output summary.
        if isinstance(result, str):
            if result.startswith("ERROR: "):
                output = f"error: {result[7:][:120]}"
            else:
                output = f"{len(result)} chars"
        elif isinstance(result, dict):
            if result.get("ok"):
                output = f"ok iri={result.get('iri', '?')}"
            else:
                output = f"error: {str(result.get('error', 'unknown'))[:120]}"
        else:
            output = str(result)[:120]

        ctx.deps.trace.append(
            ToolTraceEntry(tool=func.__name__, input=input_dict, output_summary=output)
        )
        return result

    return wrapper


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
# Shared utility (also used by write-tool plugins)
# ---------------------------------------------------------------------------


def _now_utc_str() -> str:
    """Return current UTC time in ``YYYY-MM-DDTHH:MM:SSZ`` format."""
    return _format_datetime(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_READ_TOOLS = [
    Tool(get_schema_details),
    Tool(graphql_query),
    Tool(get_document),
    Tool(today),
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
