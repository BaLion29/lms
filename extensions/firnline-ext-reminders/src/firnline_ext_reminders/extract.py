"""Extraction plugin for Reminder proposals.

Part of the firnline-ext-reminders reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from firnline_core.models import OneShotTrigger
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_ext_reminders.models import Reminder


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
    produces: list[str] = ["Reminder", "OneShotTrigger"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="reminders", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="triggers", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [ReminderProposal]

    def prompt_snippet(self) -> str:
        return ""

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        return ""

    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict[str, Any]]:
        now = ctx.now()
        docs: list[dict[str, Any]] = []

        if not isinstance(proposal, ReminderProposal):
            return []

        trigger_iri: str | None = None

        if proposal.fire_at is not None:
            trigger_id = f"OneShotTrigger/{uuid4().hex}"
            trigger_doc = OneShotTrigger(
                id_=trigger_id,
                name=f"Reminder: {proposal.name}",
                enabled=True,
                fire_at=proposal.fire_at,
                provenance={
                    "agent": "ext:reminders",
                    "at": now,
                    "method": "llm_extraction",
                },
            ).to_tdb()
            docs.append(trigger_doc)
            trigger_iri = trigger_id

        reminder_doc = Reminder(
            name=proposal.name,
            description=proposal.description,
            refers_to=None,
            trigger=trigger_iri,
            provenance={
                "agent": "ext:reminders",
                "at": now,
                "method": "llm_extraction",
            },
        ).to_tdb()
        docs.append(reminder_doc)
        return docs


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = ReminderExtractPlugin()
