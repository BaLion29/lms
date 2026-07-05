"""Agent tools for TerminusDB operations exposed via pydantic-ai.

Tools are gated by ``Settings.enable_writes``: query tools are always
registered; mutation tools (which write to TerminusDB) are only
appended when writes are explicitly enabled.

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
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel
from pydantic_ai import RunContext, Tool

from lms_core.models import (
    Reminder,
    Task,
    TaskStatus,
    _format_datetime,
)
from lms_core.tdb import TdbClient, TdbError, short_iri

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
# Write tools (registered only when settings.enable_writes is True)
# ---------------------------------------------------------------------------


def _now_utc_str() -> str:
    """Return current UTC time in ``YYYY-MM-DDTHH:MM:SSZ`` format."""
    return _format_datetime(datetime.now(timezone.utc))


@_traced
async def set_task_status(
    ctx: RunContext[QuerydDeps],
    task_iri: str,
    status: Literal["open", "planned", "done"],
) -> dict[str, object]:
    """Set the status of a Task document."""
    iri = short_iri(task_iri)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await ctx.deps.tdb.get_document(iri, branch=branch)
    except TdbError as exc:
        return {"ok": False, "error": f"document not found: {iri} ({exc.status})"}

    if doc.get("@type") != "Task":
        return {"ok": False, "error": f"{iri} is not a Task (type={doc.get('@type')})"}

    doc["status"] = status
    doc["updated_at"] = _now_utc_str()

    log.info(
        "queryd: set_task_status",
        iri=iri,
        status=status,
        doc=doc,
    )

    try:
        await ctx.deps.tdb.replace_document(
            doc,
            branch=branch,
            message=f"queryd: set status {status} on {iri}",
            author="queryd",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@_traced
async def set_event_status(
    ctx: RunContext[QuerydDeps],
    event_iri: str,
    status: Literal["open", "planned", "closed", "cancelled"],
) -> dict[str, object]:
    """Set the status of an Event document."""
    iri = short_iri(event_iri)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await ctx.deps.tdb.get_document(iri, branch=branch)
    except TdbError as exc:
        return {"ok": False, "error": f"document not found: {iri} ({exc.status})"}

    if doc.get("@type") != "Event":
        return {
            "ok": False,
            "error": f"{iri} is not an Event (type={doc.get('@type')})",
        }

    doc["status"] = status
    doc["updated_at"] = _now_utc_str()

    log.info(
        "queryd: set_event_status",
        iri=iri,
        status=status,
        doc=doc,
    )

    try:
        await ctx.deps.tdb.replace_document(
            doc,
            branch=branch,
            message=f"queryd: set status {status} on {iri}",
            author="queryd",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@_traced
async def create_task(
    ctx: RunContext[QuerydDeps],
    name: str,
    description: str | None = None,
    due_date: datetime | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    """Create a new Task document."""
    now_dt = datetime.now(timezone.utc)
    task = Task(
        name=name,
        description=description,
        due_date=due_date,
        priority=priority,
        status=TaskStatus.OPEN,
        created_at=now_dt,
        updated_at=now_dt,
    )
    doc = task.to_tdb()
    branch = ctx.deps.settings.tdb_branch

    log.info("queryd: create_task", doc=doc)

    try:
        iris = await ctx.deps.tdb.insert_documents(
            [doc],
            branch=branch,
            message=f"queryd: create task {name}",
            author="queryd",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    result_iri = short_iri(iris[0]) if iris else "unknown"
    return {"ok": True, "iri": result_iri}


@_traced
async def create_reminder(
    ctx: RunContext[QuerydDeps],
    name: str,
    description: str | None = None,
    refers_to_iri: str | None = None,
) -> dict[str, object]:
    """Create a new Reminder, optionally linked to a Task or Event.

    When *refers_to_iri* is given, the target MUST exist and have an
    ``@type`` of ``Task`` or ``Event``; otherwise the creation is
    rejected.
    """
    branch = ctx.deps.settings.tdb_branch
    refers_to: str | None = None

    if refers_to_iri is not None:
        siri = short_iri(refers_to_iri)
        try:
            target = await ctx.deps.tdb.get_document(siri, branch=branch)
        except TdbError as exc:
            return {
                "ok": False,
                "error": f"refers_to document not found: {siri} ({exc.status})",
            }
        if target.get("@type") not in ("Task", "Event"):
            return {
                "ok": False,
                "error": f"refers_to {siri} has type {target.get('@type')}, expected Task or Event",
            }
        refers_to = siri

    now_dt = datetime.now(timezone.utc)
    reminder = Reminder(
        name=name,
        description=description,
        refers_to=refers_to,
        created_at=now_dt,
        updated_at=now_dt,
    )
    doc = reminder.to_tdb()

    log.info("queryd: create_reminder", doc=doc)

    try:
        iris = await ctx.deps.tdb.insert_documents(
            [doc],
            branch=branch,
            message=f"queryd: create reminder {name}",
            author="queryd",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    result_iri = short_iri(iris[0]) if iris else "unknown"
    return {"ok": True, "iri": result_iri}


@_traced
async def update_task(
    ctx: RunContext[QuerydDeps],
    task_iri: str,
    name: str | None = None,
    description: str | None = None,
    due_date: datetime | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    """Update fields of an existing Task.

    Only the provided (non-None) fields are changed; ``updated_at`` is
    always bumped to now.
    """
    iri = short_iri(task_iri)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await ctx.deps.tdb.get_document(iri, branch=branch)
    except TdbError as exc:
        return {"ok": False, "error": f"document not found: {iri} ({exc.status})"}

    if doc.get("@type") != "Task":
        return {"ok": False, "error": f"{iri} is not a Task (type={doc.get('@type')})"}

    if name is not None:
        doc["name"] = name
    if description is not None:
        doc["description"] = description
    if due_date is not None:
        doc["due_date"] = _format_datetime(due_date)
    if priority is not None:
        doc["priority"] = priority
    doc["updated_at"] = _now_utc_str()

    log.info("queryd: update_task", iri=iri, doc=doc)

    try:
        await ctx.deps.tdb.replace_document(
            doc,
            branch=branch,
            message=f"queryd: update task {iri}",
            author="queryd",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_READ_TOOLS = [
    Tool(get_schema_details),
    Tool(graphql_query),
    Tool(get_document),
    Tool(today),
]

_WRITE_TOOLS = [
    Tool(set_task_status),
    Tool(set_event_status),
    Tool(create_task),
    Tool(create_reminder),
    Tool(update_task),
]

# Extension point: future vector-search / RAG tools can be appended here.
# _READ_TOOLS.append(Tool(semantic_search))  # future: vector search service plugs in here


def build_tools(settings: Settings) -> list[Tool]:
    """Return the list of pydantic-ai ``Tool`` objects for *settings*.

    Query tools are always included; mutation tools are only appended
    when ``settings.enable_writes`` is ``True``.
    """
    tools: list[Tool] = list(_READ_TOOLS)
    if settings.enable_writes:
        tools.extend(_WRITE_TOOLS)
    return tools
