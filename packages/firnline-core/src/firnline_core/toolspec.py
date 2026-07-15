"""Framework-neutral tool contract for write-tool plugins.

Handler convention
------------------

Handlers MUST NOT raise exceptions for domain errors.  They return a
plain dict:

    {"ok": True, ...}          – success (extra fields allowed)
    {"ok": False, "error": "<msg>"}  – domain failure

This is the same convention already used by the existing queryd
extension tools, so migration from the legacy ``tools(deps)`` interface
is straightforward.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    """Convention carrier passed to :meth:`ToolSpec.handler`.

    Fields:
        tdb: TerminusDB client (``Any`` — avoids a service dep in firnline-core).
        branch: TDB branch for writes / queries (default ``"main"``).
    """

    tdb: Any  # TdbClient
    branch: str = "main"


@dataclass(frozen=True)
class ToolSpec:
    """A framework-neutral description of a tool that can be called.

    Fields:
        name: Unique tool name (e.g. ``"create_reminder"``).
        description: Human-readable description for the agent / user.
        args_model: Pydantic model describing the tool arguments (schema).
        handler: Async callable ``(args_model, ToolContext) -> dict``
            implementing the tool.  See the module docstring for the
            handler contract.
    """

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Awaitable[dict[str, object]]]

    @property
    def input_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this tool's arguments."""
        return self.args_model.model_json_schema()
