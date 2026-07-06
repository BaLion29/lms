"""Built-in write-tool plugin for planning operations (Task, Event, Reminder).

Provides the pydantic-ai Tool objects that were previously registered
directly in ``queryd.tools``.  The tool functions are decorated with
``@_traced`` (imported from ``queryd.tools``), preserving byte-identical
iteration-cap and tracing behaviour.

Design choice (documented):
    ``_traced`` is applied *inside* the plugin (on each tool function)
    rather than at registration time, so that the functions are already
    traced when ``Tool(fn)`` wraps them.  This keeps the same decorator
    applied to the same functions as before the refactor — zero
    behavioural difference.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic_ai import RunContext, Tool

from lms_core.models import (
    Reminder,
    Task,
    TaskStatus,
    _format_datetime,
)
from lms_core.tdb import TdbError, short_iri
from lms_core.plugins import ModuleRequirement

from queryd.tools import QuerydDeps, _now_utc_str, _traced  # noqa: F401

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tool functions (verbatim move from queryd.tools)
# ---------------------------------------------------------------------------


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
# Plugin class
# ---------------------------------------------------------------------------


class PlanningToolsPlugin:
    """Built-in queryd write-tool plugin for planning operations."""

    name: str = "planning_tools"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=1.0.0 <2.0.0")
    ]

    def tools(self, deps: Any) -> list[Tool]:
        """Return pydantic-ai Tool objects for planning write operations."""
        return [
            Tool(set_task_status),
            Tool(set_event_status),
            Tool(create_task),
            Tool(create_reminder),
            Tool(update_task),
        ]


plugin = PlanningToolsPlugin()
