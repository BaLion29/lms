"""Queryd write-tool plugin for planning operations (Task, Event).

Provides the pydantic-ai Tool objects for planning write operations.
Imports tracing from ``lms_core.tooling`` (public kernel contract, L7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import structlog

from pydantic_ai import RunContext, Tool

from lms_core.models import (
    Task,
    TaskStatus,
    _format_datetime,
)
from lms_core.tdb import TdbError, short_iri
from lms_core.plugins import ModuleRequirement
from lms_core.tooling import traced, now_utc_str

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


@traced
async def set_task_status(
    ctx: RunContext[Any],
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
    doc["updated_at"] = now_utc_str()

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


@traced
async def set_event_status(
    ctx: RunContext[Any],
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
    doc["updated_at"] = now_utc_str()

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


@traced
async def create_task(
    ctx: RunContext[Any],
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


@traced
async def update_task(
    ctx: RunContext[Any],
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
    doc["updated_at"] = now_utc_str()

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
# Plugin class
# ---------------------------------------------------------------------------


class PlanningToolsPlugin:
    """Queryd write-tool plugin for planning operations."""

    name: str = "planning_tools"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=2.0.0 <3.0.0")
    ]

    def tools(self, deps: Any) -> list[Tool]:
        """Return pydantic-ai Tool objects for planning write operations."""
        return [
            Tool(set_task_status),
            Tool(set_event_status),
            Tool(create_task),
            Tool(update_task),
        ]


plugin = PlanningToolsPlugin()
