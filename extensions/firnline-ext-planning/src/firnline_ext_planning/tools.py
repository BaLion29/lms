"""Queryd write-tool plugin for planning operations (Task, Event).

Provides the pydantic-ai Tool objects for planning write operations.
Imports tracing from ``firnline_core.tooling`` (public kernel contract, L7).
All writes go through the Repository layer (L6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import structlog

from pydantic_ai import RunContext, Tool

from firnline_core.base import _format_datetime
from firnline_core.plugins import ModuleRequirement
from firnline_core.repository import Repository, TransitionError as RepoTransitionError
from firnline_core.tooling import traced
from firnline_ext_planning.models import Task, TaskStatus, EventStatus

_UTC = timezone.utc

log = structlog.get_logger()

_AGENT = "ext:planning"

# ---------------------------------------------------------------------------
# Transitions table (must match schema @metadata.transitions)
# ---------------------------------------------------------------------------

_TASK_TRANSITIONS = {
    "Task": {
        "open": ["planned", "done"],
        "planned": ["open", "done"],
        "done": ["open"],
    },
}

_EVENT_TRANSITIONS = {
    "Event": {
        "open": ["planned", "closed", "cancelled"],
        "planned": ["open", "closed", "cancelled"],
        "closed": ["open"],
        "cancelled": ["open"],
    },
}


def _get_repo(ctx: RunContext[Any], transitions: dict[str, dict[str, list[str]]]) -> Repository:
    tdb = ctx.deps.tdb
    if not isinstance(tdb, Repository):
        return Repository(tdb, transitions=transitions)
    return tdb


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
    repo = _get_repo(ctx, _TASK_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(task_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {task_iri}: {exc}"}

    if doc.get("@type") != "Task":
        return {"ok": False, "error": f"{task_iri} is not a Task (type={doc.get('@type')})"}

    current = doc.get("status", "?")
    log.info("queryd: set_task_status", iri=task_iri, from_status=current, to_status=status)

    try:
        await repo.transition(
            task_iri,
            "status",
            current,
            status,
            agent=_AGENT,
            branch=branch,
        )
    except RepoTransitionError as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": task_iri}


@traced
async def set_event_status(
    ctx: RunContext[Any],
    event_iri: str,
    status: Literal["open", "planned", "closed", "cancelled"],
) -> dict[str, object]:
    """Set the status of an Event document."""
    repo = _get_repo(ctx, _EVENT_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(event_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {event_iri}: {exc}"}

    if doc.get("@type") != "Event":
        return {"ok": False, "error": f"{event_iri} is not an Event (type={doc.get('@type')})"}

    current = doc.get("status", "?")
    log.info("queryd: set_event_status", iri=event_iri, from_status=current, to_status=status)

    try:
        await repo.transition(
            event_iri,
            "status",
            current,
            status,
            agent=_AGENT,
            branch=branch,
        )
    except RepoTransitionError as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": event_iri}


@traced
async def create_task(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    """Create a new Task document."""
    repo = _get_repo(ctx, _TASK_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    now = datetime.now(_UTC)
    task = Task(
        name=name,
        description=description,
        due_date=due_date,
        priority=priority,
        status=TaskStatus.OPEN,
        created_at=now,
        updated_at=now,
    ).to_tdb()

    log.info("queryd: create_task", doc=task)

    try:
        iri = await repo.create(
            task,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@traced
async def update_task(
    ctx: RunContext[Any],
    task_iri: str,
    name: str | None = None,
    description: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    """Update fields of an existing Task.

    Only the provided (non-None) fields are changed; ``updated_at`` is
    always bumped to now.
    """
    repo = _get_repo(ctx, _TASK_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(task_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {task_iri}: {exc}"}

    if doc.get("@type") != "Task":
        return {"ok": False, "error": f"{task_iri} is not a Task (type={doc.get('@type')})"}

    if name is not None:
        doc["name"] = name
    if description is not None:
        doc["description"] = description
    if due_date is not None:
        doc["due_date"] = due_date
    if priority is not None:
        doc["priority"] = priority

    doc["updated_at"] = _format_datetime(datetime.now(timezone.utc))

    log.info("queryd: update_task", iri=task_iri, doc=doc)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: update {task_iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": task_iri}


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class PlanningToolsPlugin:
    """Queryd write-tool plugin for planning operations."""

    name: str = "planning_tools"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=0.1.0 <0.2.0")
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
