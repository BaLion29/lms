"""Queryd write-tool plugin for time-management operations (Task, Event, Routine, Activity).

Provides the pydantic-ai Tool objects for time-management write operations.
Imports tracing from ``firnline_core.tooling`` (public kernel contract, L7).
All writes go through the Repository layer (L6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import structlog

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool

from firnline_core.base import _format_datetime
from firnline_core.generated.core import Provenance
from firnline_core.plugins import ModuleRequirement
from firnline_core.repository import Repository, TransitionError as RepoTransitionError
from firnline_core.tooling import traced
from firnline_core.toolspec import ToolContext, ToolSpec
from firnline_ext_time_management.models import (
    Activity,
    ActivitySpec,
    Area,
    EventStatus,
    Goal,
    GoalStatus,
    Project,
    ProjectStatus,
    Routine,
    RoutineStep,
    Task,
    TaskSpec,
    TaskStatus,
)

_UTC = timezone.utc

log = structlog.get_logger()

_AGENT = "ext:time-management"

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

_PROJECT_TRANSITIONS = {
    "Project": {
        "active": ["on_hold", "completed"],
        "on_hold": ["active"],
        "completed": [],
    },
}

_GOAL_TRANSITIONS = {
    "Goal": {
        "active": ["achieved", "abandoned"],
        "abandoned": ["active"],
    },
}


def _get_repo(ctx: RunContext[Any], transitions: dict[str, dict[str, list[str]]]) -> Repository:
    tdb = ctx.deps.tdb
    if not isinstance(tdb, Repository):
        return Repository(tdb, transitions=transitions)
    return tdb


# ---------------------------------------------------------------------------
# Shared step helper — maps flat step dicts to RoutineStep dicts with oneOf
# ---------------------------------------------------------------------------


def _build_step_dicts(
    steps: list[dict[str, Any]],
    now: datetime,
    provenance: Provenance,
) -> list[dict[str, Any]]:
    """Convert a list of flat step dicts into RoutineStep TDB dicts.

    Each step dict must have:
        name: str
        step_type: "activity" | "task" (default "activity")
        cadence_days: int | None
        description: str | None
        priority: int | None
        estimated_duration: int | None

    Maps to RoutineStep with ActivitySpec or TaskSpec nested per step_type.
    """
    result: list[dict[str, Any]] = []
    for raw_step in steps:
        name = raw_step["name"]
        step_type = raw_step.get("step_type", "activity")
        cadence_days = raw_step.get("cadence_days")
        description = raw_step.get("description")
        priority = raw_step.get("priority")
        estimated_duration = raw_step.get("estimated_duration")

        if step_type == "task":
            spec = TaskSpec(
                name=name,
                description=description,
                priority=priority,
                estimated_duration=estimated_duration,
            )
            step = RoutineStep(
                name=name,
                cadence_days=cadence_days,
                task=spec,
                provenance=provenance,
            )
        else:  # activity
            spec = ActivitySpec(
                name=name,
                description=description,
                priority=priority,
                estimated_duration=estimated_duration,
            )
            step = RoutineStep(
                name=name,
                cadence_days=cadence_days,
                activity=spec,
                provenance=provenance,
            )
        result.append(step.to_tdb())

    return result


# ---------------------------------------------------------------------------
# Args models for ToolSpec
# ---------------------------------------------------------------------------


class SetTaskStatusArgs(BaseModel):
    """Set the status of a Task document."""

    task_iri: str = Field(description="The IRI of the Task to update")
    status: Literal["open", "planned", "done"] = Field(description="The new status for the Task")


class SetEventStatusArgs(BaseModel):
    """Set the status of an Event document."""

    event_iri: str = Field(description="The IRI of the Event to update")
    status: Literal["open", "planned", "closed", "cancelled"] = Field(description="The new status for the Event")


class CreateTaskArgs(BaseModel):
    """Create a new Task document."""

    name: str = Field(description="The name/title of the Task")
    description: str | None = Field(default=None, description="Optional description of the Task")
    due_date: str | None = Field(default=None, description="Optional due date in ISO 8601 format")
    priority: int | None = Field(default=None, description="Optional priority (higher = more important)")


class UpdateTaskArgs(BaseModel):
    """Update fields of an existing Task.

    Only the provided (non-None) fields are changed.
    always bumped to now.
    """

    task_iri: str = Field(description="The IRI of the Task to update")
    name: str | None = Field(default=None, description="New name for the Task")
    description: str | None = Field(default=None, description="New description for the Task")
    due_date: str | None = Field(default=None, description="New due date in ISO 8601 format")
    priority: int | None = Field(default=None, description="New priority (higher = more important)")


class CreateRoutineArgs(BaseModel):
    """Create a new Routine document with ordered steps.

    Each step dict must have:
      - name (str): Step name
      - step_type ("activity"|"task", default "activity"): kind of step
      - cadence_days (int, optional): repeat interval in days
      - description (str, optional)
      - priority (int, optional)
      - estimated_duration (int, optional): in minutes
    """

    name: str = Field(description="The name of the Routine")
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered list of step dicts (see docstring for format)",
    )
    required_context: list[str] | None = Field(default=None, description="Optional list of context tags")


class UpdateRoutineArgs(BaseModel):
    """Update fields of an existing Routine.

    Only the provided (non-None) fields are changed.
    always bumped to now.  When *steps* is provided, the entire steps list
    is replaced.
    """

    routine_iri: str = Field(description="The IRI of the Routine to update")
    name: str | None = Field(default=None, description="New name for the Routine")
    required_context: list[str] | None = Field(default=None, description="New list of required context tags")
    steps: list[dict[str, Any]] | None = Field(
        default=None,
        description="New list of steps (replaces existing). Same format as create_routine.",
    )


class LogActivityArgs(BaseModel):
    """Log a concrete Activity (performed or planned session).

    If *routine_id* is provided, the Activity is linked to that Routine.
    The referenced Routine must exist; otherwise the call fails with an error.
    """

    name: str = Field(description="The name of the Activity")
    start_datetime: str | None = Field(default=None, description="Optional start time in ISO 8601 format")
    end_datetime: str | None = Field(default=None, description="Optional end time in ISO 8601 format")
    description: str | None = Field(default=None, description="Optional description")
    priority: int | None = Field(default=None, description="Optional priority (higher = more important)")
    estimated_duration: int | None = Field(default=None, description="Optional estimated duration in minutes")
    routine_id: str | None = Field(default=None, description="Optional Routine IRI to link this Activity to")


# ---------------------------------------------------------------------------
# Core business logic (_do_ functions — no RunContext, no @traced)
# ---------------------------------------------------------------------------


async def _do_set_task_status(
    task_iri: str,
    status: str,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Set the status of a Task document (core logic)."""
    repo = Repository(tdb, transitions=_TASK_TRANSITIONS) if not isinstance(tdb, Repository) else tdb

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


async def _do_set_event_status(
    event_iri: str,
    status: str,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Set the status of an Event document (core logic)."""
    repo = Repository(tdb, transitions=_EVENT_TRANSITIONS) if not isinstance(tdb, Repository) else tdb

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


async def _do_create_task(
    name: str,
    description: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Task document (core logic)."""
    repo = Repository(tdb, transitions=_TASK_TRANSITIONS) if not isinstance(tdb, Repository) else tdb

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    task = Task(
        name=name,
        description=description,
        due_date=due_date,
        priority=priority,
        status=TaskStatus.OPEN,
        provenance=prov,
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


async def _do_update_task(
    task_iri: str,
    name: str | None = None,
    description: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Update fields of an existing Task (core logic).

    Only the provided (non-None) fields are changed.
    always bumped to now.
    """
    repo = Repository(tdb, transitions=_TASK_TRANSITIONS) if not isinstance(tdb, Repository) else tdb

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

    log.info("queryd: update_task", iri=task_iri, doc=doc)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: update {task_iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": task_iri}


async def _do_create_routine(
    name: str,
    steps: list[dict[str, Any]],
    required_context: list[str] | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Routine document with ordered steps (core logic).

    Each step dict must have:
      - name (str): Step name
      - step_type ("activity"|"task", default "activity"): kind of step
      - cadence_days (int, optional): repeat interval in days
      - description (str, optional)
      - priority (int, optional)
      - estimated_duration (int, optional): in minutes
    """
    repo = Repository(tdb, transitions={}) if not isinstance(tdb, Repository) else tdb

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")

    try:
        step_docs = _build_step_dicts(steps, now, prov)
    except Exception as exc:
        return {"ok": False, "error": f"invalid steps: {exc}"}

    routine = Routine(
        name=name,
        required_context=required_context or [],
        steps=step_docs,
        provenance=prov,
    ).to_tdb()

    log.info("queryd: create_routine", doc=routine)

    try:
        iri = await repo.create(
            routine,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


async def _do_update_routine(
    routine_iri: str,
    name: str | None = None,
    required_context: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Update fields of an existing Routine (core logic).

    Only the provided (non-None) fields are changed.
    always bumped to now.  When *steps* is provided, the entire steps list
    is replaced.
    """
    repo = Repository(tdb, transitions={}) if not isinstance(tdb, Repository) else tdb

    try:
        doc = await repo.get_document(routine_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {routine_iri}: {exc}"}

    if doc.get("@type") != "Routine":
        return {"ok": False, "error": f"{routine_iri} is not a Routine (type={doc.get('@type')})"}

    if name is not None:
        doc["name"] = name
    if required_context is not None:
        doc["required_context"] = required_context
    if steps is not None:
        now = datetime.now(timezone.utc)
        prov = Provenance(agent=_AGENT, at=now, method="tool_call")
        try:
            doc["steps"] = _build_step_dicts(steps, now, prov)
        except Exception as exc:
            return {"ok": False, "error": f"invalid steps: {exc}"}

    log.info("queryd: update_routine", iri=routine_iri, doc=doc)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: update {routine_iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": routine_iri}


# ---------------------------------------------------------------------------
# Tool functions — Project
# ---------------------------------------------------------------------------


@traced
async def create_project(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    target_date: str | None = None,
) -> dict[str, object]:
    """Create a new Project document with status=active.

    In PARA, a Project is a series of Tasks linked to a desired Outcome.
    Link Tasks to the Project via ``assign_contexts``.
    """
    repo = _get_repo(ctx, _PROJECT_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    project = Project(
        name=name,
        description=description,
        target_date=target_date,
        status=ProjectStatus.ACTIVE,
        provenance=prov,
    ).to_tdb()

    log.info("queryd: create_project", doc=project)

    try:
        iri = await repo.create(
            project,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@traced
async def update_project(
    ctx: RunContext[Any],
    project_iri: str,
    name: str | None = None,
    description: str | None = None,
    target_date: str | None = None,
) -> dict[str, object]:
    """Update fields of an existing Project.

    Only the provided (non-None) fields are changed.
    always bumped to now.  Status changes must go through
    ``set_project_status``.
    """
    repo = _get_repo(ctx, _PROJECT_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(project_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {project_iri}: {exc}"}

    if doc.get("@type") != "Project":
        return {"ok": False, "error": f"{project_iri} is not a Project (type={doc.get('@type')})"}

    if name is not None:
        doc["name"] = name
    if description is not None:
        doc["description"] = description
    if target_date is not None:
        doc["target_date"] = target_date

    log.info("queryd: update_project", iri=project_iri, doc=doc)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: update {project_iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": project_iri}


@traced
async def set_project_status(
    ctx: RunContext[Any],
    project_iri: str,
    status: Literal["active", "on_hold", "completed"],
) -> dict[str, object]:
    """Set the status of a Project document.

    Active projects can be put on-hold or completed.  On-hold projects
    can be re-activated.  Completed projects are terminal.
    """
    repo = _get_repo(ctx, _PROJECT_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(project_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {project_iri}: {exc}"}

    if doc.get("@type") != "Project":
        return {"ok": False, "error": f"{project_iri} is not a Project (type={doc.get('@type')})"}

    current = doc.get("status", "?")
    log.info("queryd: set_project_status", iri=project_iri, from_status=current, to_status=status)

    if current == "completed":
        return {"ok": False, "error": f"Cannot transition from terminal status 'completed' on {project_iri}"}

    try:
        await repo.transition(
            project_iri,
            "status",
            current,
            status,
            agent=_AGENT,
            branch=branch,
        )
    except RepoTransitionError as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": project_iri}


# ---------------------------------------------------------------------------
# Tool functions — Goal
# ---------------------------------------------------------------------------


@traced
async def create_goal(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    success_criteria: str | None = None,
    target_date: str | None = None,
) -> dict[str, object]:
    """Create a new Goal document with status=active.

    In PARA, a Goal is an aspirational Outcome.  Use ``assign_contexts``
    to link a Project to a Goal, or a Goal to an Area.
    """
    repo = _get_repo(ctx, _GOAL_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    goal = Goal(
        name=name,
        description=description,
        success_criteria=success_criteria,
        target_date=target_date,
        status=GoalStatus.ACTIVE,
        provenance=prov,
    ).to_tdb()

    log.info("queryd: create_goal", doc=goal)

    try:
        iri = await repo.create(
            goal,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@traced
async def set_goal_status(
    ctx: RunContext[Any],
    goal_iri: str,
    status: Literal["active", "achieved", "abandoned"],
) -> dict[str, object]:
    """Set the status of a Goal document.

    Active goals can be marked achieved or abandoned.  Abandoned goals
    can be re-activated.  Achieved goals are terminal.
    """
    repo = _get_repo(ctx, _GOAL_TRANSITIONS)
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(goal_iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {goal_iri}: {exc}"}

    if doc.get("@type") != "Goal":
        return {"ok": False, "error": f"{goal_iri} is not a Goal (type={doc.get('@type')})"}

    current = doc.get("status", "?")
    log.info("queryd: set_goal_status", iri=goal_iri, from_status=current, to_status=status)

    if current == "achieved":
        return {"ok": False, "error": f"Cannot transition from terminal status 'achieved' on {goal_iri}"}

    try:
        await repo.transition(
            goal_iri,
            "status",
            current,
            status,
            agent=_AGENT,
            branch=branch,
        )
    except RepoTransitionError as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": goal_iri}


# ---------------------------------------------------------------------------
# Tool functions — Area
# ---------------------------------------------------------------------------


@traced
async def create_area(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
) -> dict[str, object]:
    """Create a new Area document.

    In PARA, an Area is a domain of ongoing responsibility without an end
    date.  Areas are uniquely identified by name (Lexical key).  Use
    ``assign_contexts`` to link a Project or Goal to an Area.
    """
    repo = _get_repo(ctx, {})
    branch = ctx.deps.settings.tdb_branch

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    area = Area(
        name=name,
        description=description,
        provenance=prov,
    ).to_tdb()

    log.info("queryd: create_area", doc=area)

    try:
        iri = await repo.create(
            area,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


# ---------------------------------------------------------------------------
# Tool functions — Contexts (generic)
# ---------------------------------------------------------------------------

# Entity types that carry a ``contexts`` field and can be linked to Context
# documents (Area, Project, Goal, etc.).
_CONTEXTABLE_TYPES = frozenset({
    "Task", "Event", "Project", "Goal", "Routine", "Activity", "Area",
})


@traced
async def assign_contexts(
    ctx: RunContext[Any],
    iri: str,
    context_iris: list[str],
) -> dict[str, object]:
    """Add Context IRIs to an entity's ``contexts`` set.

    Use this to link a Task to a Project (PARA: move a task into a project),
    a Project to an Area or Goal, or any entity to a relevant context.
    Duplicate IRIs already present are silently skipped.  Each context IRI
    must reference an existing document.
    """
    repo = _get_repo(ctx, {})
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {iri}: {exc}"}

    doc_type = doc.get("@type", "")
    if doc_type not in _CONTEXTABLE_TYPES:
        return {
            "ok": False,
            "error": f"{iri} (type={doc_type}) does not support contexts",
        }

    if doc.get("archived_at"):
        return {"ok": False, "error": f"Cannot modify archived document: {iri}"}

    # Validate each context IRI exists
    for ctx_iri in context_iris:
        try:
            await repo.get_document(ctx_iri, branch=branch)
        except Exception as exc:
            return {"ok": False, "error": f"context document not found: {ctx_iri}: {exc}"}

    existing: list[str] = doc.get("contexts", [])
    updated = list(dict.fromkeys(existing + context_iris))  # dedupe preserving order
    doc["contexts"] = updated

    log.info("queryd: assign_contexts", iri=iri, added=context_iris, contexts=updated)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: assign_contexts {iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


@traced
async def remove_contexts(
    ctx: RunContext[Any],
    iri: str,
    context_iris: list[str],
) -> dict[str, object]:
    """Remove Context IRIs from an entity's ``contexts`` set.

    Inverse of ``assign_contexts``.  IRIs that are not currently linked
    are silently ignored.  The entity itself is not deleted.
    """
    repo = _get_repo(ctx, {})
    branch = ctx.deps.settings.tdb_branch

    try:
        doc = await repo.get_document(iri, branch=branch)
    except Exception as exc:
        return {"ok": False, "error": f"document not found: {iri}: {exc}"}

    doc_type = doc.get("@type", "")
    if doc_type not in _CONTEXTABLE_TYPES:
        return {
            "ok": False,
            "error": f"{iri} (type={doc_type}) does not support contexts",
        }

    if doc.get("archived_at"):
        return {"ok": False, "error": f"Cannot modify archived document: {iri}"}

    existing: list[str] = doc.get("contexts", [])
    remove_set = set(context_iris)
    updated = [c for c in existing if c not in remove_set]
    doc["contexts"] = updated

    log.info("queryd: remove_contexts", iri=iri, removed=context_iris, contexts=updated)

    try:
        await repo.tdb.insert_documents([doc], branch=branch, message=f"queryd: remove_contexts {iri}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


# ---------------------------------------------------------------------------
# Tool functions — Activity
# ---------------------------------------------------------------------------

async def _do_log_activity(
    name: str,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    estimated_duration: int | None = None,
    routine_id: str | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Log a concrete Activity (core logic).

    If *routine_id* is provided, the Activity is linked to that Routine.
    The referenced Routine must exist; otherwise the call fails with an error.
    """
    repo = Repository(tdb, transitions={}) if not isinstance(tdb, Repository) else tdb

    # Validate routine reference if provided
    if routine_id is not None:
        try:
            routine_doc = await repo.get_document(routine_id, branch=branch)
        except Exception as exc:
            return {"ok": False, "error": f"routine not found: {routine_id}: {exc}"}
        if routine_doc.get("@type") != "Routine":
            return {"ok": False, "error": f"{routine_id} is not a Routine (type={routine_doc.get('@type')})"}

    now = datetime.now(_UTC)
    prov = Provenance(agent=_AGENT, at=now, method="tool_call")
    activity = Activity(
        name=name,
        description=description,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        priority=priority,
        estimated_duration=estimated_duration,
        routine=routine_id,
        provenance=prov,
    ).to_tdb()

    log.info("queryd: log_activity", doc=activity)

    try:
        iri = await repo.create(
            activity,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


# ---------------------------------------------------------------------------
# Legacy pydantic-ai tool wrappers (@traced, RunContext — keep unchanged)
# ---------------------------------------------------------------------------


@traced
async def set_task_status(
    ctx: RunContext[Any],
    task_iri: str,
    status: Literal["open", "planned", "done"],
) -> dict[str, object]:
    """Set the status of a Task document."""
    return await _do_set_task_status(
        task_iri, status,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


@traced
async def set_event_status(
    ctx: RunContext[Any],
    event_iri: str,
    status: Literal["open", "planned", "closed", "cancelled"],
) -> dict[str, object]:
    """Set the status of an Event document."""
    return await _do_set_event_status(
        event_iri, status,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


@traced
async def create_task(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    """Create a new Task document."""
    return await _do_create_task(
        name, description, due_date, priority,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


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

    Only the provided (non-None) fields are changed.
    always bumped to now.
    """
    return await _do_update_task(
        task_iri, name, description, due_date, priority,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


@traced
async def create_routine(
    ctx: RunContext[Any],
    name: str,
    steps: list[dict[str, Any]],
    required_context: list[str] | None = None,
) -> dict[str, object]:
    """Create a new Routine document with ordered steps.

    Each step dict must have:
      - name (str): Step name
      - step_type ("activity"|"task", default "activity"): kind of step
      - cadence_days (int, optional): repeat interval in days
      - description (str, optional)
      - priority (int, optional)
      - estimated_duration (int, optional): in minutes
    """
    return await _do_create_routine(
        name, steps, required_context,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


@traced
async def update_routine(
    ctx: RunContext[Any],
    routine_iri: str,
    name: str | None = None,
    required_context: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    """Update fields of an existing Routine.

    Only the provided (non-None) fields are changed.
    always bumped to now.  When *steps* is provided, the entire steps list
    is replaced.
    """
    return await _do_update_routine(
        routine_iri, name, required_context, steps,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


@traced
async def log_activity(
    ctx: RunContext[Any],
    name: str,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    estimated_duration: int | None = None,
    routine_id: str | None = None,
) -> dict[str, object]:
    """Log a concrete Activity (performed or planned session).

    If *routine_id* is provided, the Activity is linked to that Routine.
    The referenced Routine must exist; otherwise the call fails with an error.
    """
    return await _do_log_activity(
        name, start_datetime, end_datetime, description, priority, estimated_duration, routine_id,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


# ---------------------------------------------------------------------------
# ToolSpec handlers
# ---------------------------------------------------------------------------


async def _handle_set_task_status(args: SetTaskStatusArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_set_task_status(args.task_iri, args.status, tdb=ctx.tdb, branch=ctx.branch)


async def _handle_set_event_status(args: SetEventStatusArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_set_event_status(args.event_iri, args.status, tdb=ctx.tdb, branch=ctx.branch)


async def _handle_create_task(args: CreateTaskArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_task(
        args.name, args.description, args.due_date, args.priority,
        tdb=ctx.tdb, branch=ctx.branch,
    )


async def _handle_update_task(args: UpdateTaskArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_update_task(
        args.task_iri, args.name, args.description, args.due_date, args.priority,
        tdb=ctx.tdb, branch=ctx.branch,
    )


async def _handle_create_routine(args: CreateRoutineArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_routine(
        args.name, args.steps, args.required_context,
        tdb=ctx.tdb, branch=ctx.branch,
    )


async def _handle_update_routine(args: UpdateRoutineArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_update_routine(
        args.routine_iri, args.name, args.required_context, args.steps,
        tdb=ctx.tdb, branch=ctx.branch,
    )


async def _handle_log_activity(args: LogActivityArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_log_activity(
        args.name, args.start_datetime, args.end_datetime, args.description,
        args.priority, args.estimated_duration, args.routine_id,
        tdb=ctx.tdb, branch=ctx.branch,
    )


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class TimeManagementToolsPlugin:
    """Queryd write-tool plugin for time-management operations."""

    name: str = "time_management_tools"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.1.0 <0.2.0")
    ]

    def tools(self, deps: Any) -> list[Tool]:
        """Return pydantic-ai Tool objects for time-management write operations."""
        return [
            Tool(set_task_status),
            Tool(set_event_status),
            Tool(create_task),
            Tool(update_task),
            Tool(create_routine),
            Tool(update_routine),
            Tool(log_activity),
            Tool(create_project),
            Tool(update_project),
            Tool(set_project_status),
            Tool(create_goal),
            Tool(set_goal_status),
            Tool(create_area),
            Tool(assign_contexts),
            Tool(remove_contexts),
        ]

    def tool_specs(self) -> list[ToolSpec]:
        """Return framework-neutral ToolSpec objects for time-management write operations."""
        return [
            ToolSpec(
                name="set_task_status",
                description=set_task_status.__doc__ or "Set the status of a Task document.",
                args_model=SetTaskStatusArgs,
                handler=_handle_set_task_status,
            ),
            ToolSpec(
                name="set_event_status",
                description=set_event_status.__doc__ or "Set the status of an Event document.",
                args_model=SetEventStatusArgs,
                handler=_handle_set_event_status,
            ),
            ToolSpec(
                name="create_task",
                description=create_task.__doc__ or "Create a new Task document.",
                args_model=CreateTaskArgs,
                handler=_handle_create_task,
            ),
            ToolSpec(
                name="update_task",
                description=update_task.__doc__ or "Update fields of an existing Task.",
                args_model=UpdateTaskArgs,
                handler=_handle_update_task,
            ),
            ToolSpec(
                name="create_routine",
                description=create_routine.__doc__ or "Create a new Routine document.",
                args_model=CreateRoutineArgs,
                handler=_handle_create_routine,
            ),
            ToolSpec(
                name="update_routine",
                description=update_routine.__doc__ or "Update fields of an existing Routine.",
                args_model=UpdateRoutineArgs,
                handler=_handle_update_routine,
            ),
            ToolSpec(
                name="log_activity",
                description=log_activity.__doc__ or "Log a concrete Activity.",
                args_model=LogActivityArgs,
                handler=_handle_log_activity,
            ),
        ]


plugin = TimeManagementToolsPlugin()
