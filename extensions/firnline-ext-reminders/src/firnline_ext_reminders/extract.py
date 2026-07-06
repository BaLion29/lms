"""Extraction plugin for Reminder proposals.

Part of the firnline-ext-reminders reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from firnline_core.generated.triggers import OneShotTrigger
from firnline_core.models import Reminder
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri


# ---------------------------------------------------------------------------
# Proposal model
# ---------------------------------------------------------------------------


class ReminderProposal(BaseModel):
    kind: Literal["reminder"] = "reminder"
    name: str
    description: str | None = None
    fire_at: datetime | None = Field(
        default=None,
        description=(
            "When the reminder should fire (absolute ISO-8601 datetime with UTC offset, "
            "e.g. `+02:00` or `Z`). Only set if the note explicitly specifies a time. "
            "Resolve relative expressions (e.g. 'tomorrow at 9') against the note-creation "
            "time given in the prompt. Offset-less values are interpreted as UTC."
        ),
    )


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class ReminderExtractPlugin(ExtractorPlugin):
    """Extractor for reminders only."""

    name: str = "reminder_extract"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="reminders", range=">=1.0.0 <2.0.0"),
        ModuleRequirement(name="triggers", range=">=1.1.0 <2.0.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [ReminderProposal]

    def prompt_snippet(self) -> str:
        """Return instruction text (the kernel owns the JSON contract)."""
        return ""

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        return ""

    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict[str, Any]]:
        now = ctx.now()

        if isinstance(proposal, ReminderProposal):
            trigger_iri: str | None = None

            if proposal.fire_at is not None:
                # The LLM may emit naive (offset-less) datetimes.  Treat
                # naive as UTC so they round-trip predictably — consistent
                # with triggerd's _parse_iso_datetime convention and with
                # TdbDateTime's _format_datetime serialization (both assume
                # naive == UTC).
                trigger_doc = OneShotTrigger(
                    name=f"Reminder: {proposal.name}",
                    enabled=True,
                    fire_at=proposal.fire_at,
                    created_at=now,
                    updated_at=now,
                )
                # NOTE: This trigger is committed before the main Reminder batch
                # insert.  If the later insert fails the trigger becomes an
                # orphan — the same trade-off as the locations side-insert in
                # ingestd's pipeline.
                iris = await ctx.tdb.insert_documents(
                    [trigger_doc.to_tdb()],
                    branch=ctx.branch,
                    message=f"ingestd: OneShotTrigger for reminder '{proposal.name}'",
                )
                trigger_iri = short_iri(iris[0])

            return [
                Reminder(
                    name=proposal.name,
                    description=proposal.description,
                    refers_to=None,
                    trigger=trigger_iri,
                    derived_from=ctx.inbox_iri,
                    created_at=now,
                    updated_at=now,
                ).to_tdb()
            ]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = ReminderExtractPlugin()
