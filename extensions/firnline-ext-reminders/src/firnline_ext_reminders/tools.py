"""Queryd write-tool plugin for reminder operations.

Provides the pydantic-ai Tool object for create_reminder.
Imports tracing from ``firnline_core.tooling`` (public kernel contract, L7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from pydantic_ai import RunContext, Tool

from firnline_core.models import Provenance
from firnline_core.tdb import TdbError, short_iri
from firnline_core.plugins import ModuleRequirement
from firnline_core.tooling import traced

from firnline_ext_reminders.models import Reminder

log = structlog.get_logger()

# Simple in-plugin cache for Remindable-inheriting types, keyed by branch.
# Per-tool-call resolution is fine — this is a small cache to avoid
# repeated schema fetches within a single call, not a module-level singleton.
_remindable_cache: dict[str, set[str]] = {}


async def _get_remindable_types(tdb: Any, branch: str) -> set[str]:
    """Return the set of @type values that inherit ``Remindable`` on *branch*.

    Fetches the raw schema from TerminusDB and inspects ``@inherits`` lists.
    Cached per *branch*; falls back to permissive on missing/unknown schema.
    """
    cached = _remindable_cache.get(branch)
    if cached is not None:
        return cached

    try:
        raw_schema = await tdb.get_schema(branch)
    except Exception:
        # Schema not available → permissive fallback
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


# ---------------------------------------------------------------------------
# Tool function
# ---------------------------------------------------------------------------


@traced
async def create_reminder(
    ctx: RunContext[Any],
    name: str,
    description: str | None = None,
    refers_to_iri: str | None = None,
) -> dict[str, object]:
    """Create a new Reminder, optionally linked to a Remindable entity.

    When *refers_to_iri* is given, the target MUST exist and its ``@type``
    must inherit ``Remindable`` (checked against the live schema).  Falls
    back to permissive if the schema is unavailable — TerminusDB range
    validation will reject invalid references anyway.
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

        remindable_types = await _get_remindable_types(ctx.deps.tdb, branch)
        if remindable_types and target.get("@type") not in remindable_types:
            return {
                "ok": False,
                "error": (f"refers_to {siri} has type {target.get('@type')}, expected a type inheriting Remindable"),
            }
        refers_to = siri

    now_dt = datetime.now(timezone.utc)
    reminder = Reminder(
        name=name,
        description=description,
        refers_to=refers_to,
        created_at=now_dt,
        updated_at=now_dt,
        provenance=Provenance(agent="queryd", method="tool_call", source=None, at=now_dt),
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


plugin = ReminderToolsPlugin()
