"""Queryd write-tool plugin for reminder operations.

Provides the pydantic-ai Tool object for create_reminder.
Imports tracing from ``firnline_core.tooling`` (public kernel contract, L7).
All writes go through the Repository layer (L6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool

from firnline_core.plugins import ModuleRequirement
from firnline_core.repository import Repository
from firnline_core.tooling import traced
from firnline_core.toolspec import ToolContext, ToolSpec

from firnline_ext_reminders.models import Reminder

log = structlog.get_logger()

_AGENT = "ext:reminders"

# Simple in-plugin cache for Remindable-inheriting types, keyed by branch.
_remindable_cache: dict[str, set[str]] = {}


async def _get_remindable_types(tdb: Any, branch: str) -> set[str]:
    """Return the set of @type values that inherit ``Remindable`` on *branch*."""
    cached = _remindable_cache.get(branch)
    if cached is not None:
        return cached

    try:
        raw_schema = await tdb.get_schema(branch)
    except Exception:
        return set()

    remindable: set[str] = set()
    for entry in raw_schema:
        if not isinstance(entry, dict):
            continue
        inherits = entry.get("@inherits")
        if isinstance(inherits, list) and "Remindable" in inherits:
            cls_id = entry.get("@id")
            if isinstance(cls_id, str):
                remindable.add(cls_id)

    _remindable_cache[branch] = remindable
    return remindable


def _get_repo(ctx: RunContext[Any]) -> Repository:
    tdb = ctx.deps.tdb
    if not isinstance(tdb, Repository):
        return Repository(tdb)
    return tdb


# ---------------------------------------------------------------------------
# Args model for ToolSpec
# ---------------------------------------------------------------------------


class CreateReminderArgs(BaseModel):
    """Create a new Reminder, optionally linked to a Remindable entity."""

    name: str = Field(description="The name/short text of the Reminder")
    description: str | None = Field(default=None, description="Optional longer description")
    refers_to_iri: str | None = Field(default=None, description="Optional IRI of a Remindable entity to link to")


# ---------------------------------------------------------------------------
# Core business logic (_do_ function — no RunContext, no @traced)
# ---------------------------------------------------------------------------


async def _do_create_reminder(
    name: str,
    description: str | None = None,
    refers_to_iri: str | None = None,
    *,
    tdb: Any,
    branch: str,
) -> dict[str, object]:
    """Create a new Reminder (core logic), optionally linked to a Remindable entity."""
    repo = Repository(tdb) if not isinstance(tdb, Repository) else tdb
    refers_to: str | None = None

    if refers_to_iri is not None:
        try:
            target = await repo.get_document(refers_to_iri, branch=branch)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"refers_to document not found: {refers_to_iri}: {exc}",
            }

        remindable_types = await _get_remindable_types(repo.tdb, branch)
        if remindable_types and target.get("@type") not in remindable_types:
            return {
                "ok": False,
                "error": (f"refers_to {refers_to_iri} has type {target.get('@type')}, "
                          f"expected a type inheriting Remindable"),
            }
        refers_to = refers_to_iri

    now = datetime.now(timezone.utc)
    reminder = Reminder(
        name=name,
        description=description,
        refers_to=refers_to,
    ).to_tdb()

    log.info("queryd: create_reminder", doc=reminder)

    try:
        iri = await repo.create(
            reminder,
            agent=_AGENT,
            method="tool_call",
            branch=branch,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "iri": iri}


# ---------------------------------------------------------------------------
# Legacy pydantic-ai tool wrapper (@traced, RunContext — keep unchanged)
# ---------------------------------------------------------------------------


@traced
async def create_reminder(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    refers_to_iri: str | None = None,
) -> dict[str, object]:
    """Create a new Reminder, optionally linked to a Remindable entity."""
    return await _do_create_reminder(
        name, description, refers_to_iri,
        tdb=ctx.deps.tdb,
        branch=ctx.deps.settings.tdb_branch,
    )


# ---------------------------------------------------------------------------
# ToolSpec handler
# ---------------------------------------------------------------------------


async def _handle_create_reminder(args: CreateReminderArgs, ctx: ToolContext) -> dict[str, object]:
    return await _do_create_reminder(
        args.name, args.description, args.refers_to_iri,
        tdb=ctx.tdb, branch=ctx.branch,
    )


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class ReminderToolsPlugin:
    """Queryd write-tool plugin for reminder operations."""

    name: str = "reminder_tools"
    requires: list[ModuleRequirement] = [ModuleRequirement(name="reminders", range=">=0.1.0 <0.2.0")]

    def tools(self, deps: Any) -> list[Tool]:
        """Return pydantic-ai Tool objects for reminder write operations."""
        return [Tool(create_reminder)]

    def tool_specs(self) -> list[ToolSpec]:
        """Return framework-neutral ToolSpec objects for reminder write operations."""
        return [
            ToolSpec(
                name="create_reminder",
                description=create_reminder.__doc__ or "Create a new Reminder.",
                args_model=CreateReminderArgs,
                handler=_handle_create_reminder,
            ),
        ]


plugin = ReminderToolsPlugin()
