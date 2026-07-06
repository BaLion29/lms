"""Extraction plugin for Reminder proposals.

Part of the firnline-ext-reminders reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from firnline_core.models import Reminder
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement


# ---------------------------------------------------------------------------
# Proposal model
# ---------------------------------------------------------------------------


class ReminderProposal(BaseModel):
    kind: Literal["reminder"] = "reminder"
    name: str
    description: str | None = None


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------

class ReminderExtractPlugin(ExtractorPlugin):
    """Extractor for reminders only."""

    name: str = "reminder_extract"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="reminders", range=">=1.0.0 <2.0.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [ReminderProposal]

    def prompt_snippet(self) -> str:
        """Return instruction text (the kernel owns the JSON contract)."""
        return ""

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        return ""

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        now = ctx.now()

        if isinstance(proposal, ReminderProposal):
            return [
                Reminder(
                    name=proposal.name,
                    description=proposal.description,
                    refers_to=None,
                    trigger=None,
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
