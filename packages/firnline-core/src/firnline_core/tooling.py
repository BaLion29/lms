"""Public kernel contracts for tool tracing (queryd ↔ extension seam).

Provides ``ToolTraceEntry`` (the trace record model), ``now_utc_str``
(UTC timestamp helper), and ``traced`` (a decorator that appends a
``ToolTraceEntry`` to ``ctx.deps.trace`` on every tool call).

Design law L7: Extensions import from ``firnline_core.tooling``, never from
queryd internals.  queryd itself also imports from here.
"""

from __future__ import annotations

import functools
import inspect
import typing
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from firnline_core.models import _format_datetime

# ---------------------------------------------------------------------------
# ToolTraceEntry
# ---------------------------------------------------------------------------


class ToolTraceEntry(BaseModel):
    """Single tool invocation recorded for observability."""

    tool: str
    input: dict[str, object]
    output_summary: str


# ---------------------------------------------------------------------------
# now_utc_str
# ---------------------------------------------------------------------------


def now_utc_str() -> str:
    """Return current UTC time in ``YYYY-MM-DDTHH:MM:SSZ`` format."""
    return _format_datetime(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# traced decorator
# ---------------------------------------------------------------------------


def traced(func):
    """Decorator: append exactly one ``ToolTraceEntry`` per tool call.

    Traced functions must accept ``ctx: RunContext[Any]`` as their
    **first positional argument**.  The decorator duck-types access to
    ``ctx.deps`` (``trace`` list, ``tool_calls_used``, ``settings``) so
    it works with both ``QuerydDeps`` and test doubles.

    All remaining keyword/positional arguments are recorded in the trace
    entry (values longer than 200 chars are truncated).
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
        ctx = args[0]  # RunContext

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
            ToolTraceEntry(
                tool=func.__name__, input=input_dict, output_summary=output
            )
        )
        return result

    return wrapper
