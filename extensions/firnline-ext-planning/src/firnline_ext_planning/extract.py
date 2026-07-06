"""Extraction plugin for Task, Event, and Person proposals.

Part of the firnline-ext-planning reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from pydantic import BaseModel, Field

from firnline_core.models import (
    Contact,
    Event,
    EventStatus,
    Location,
    Person,
    Task,
    TaskStatus,
)
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Proposal models
# ---------------------------------------------------------------------------


class TaskProposal(BaseModel):
    kind: Literal["task"] = "task"
    name: str
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    due_date: datetime | None = None


class EventProposal(BaseModel):
    kind: Literal["event"] = "event"
    name: str
    description: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    location_name: str | None = None


class PersonProposal(BaseModel):
    kind: Literal["person"] = "person"
    name: str
    email: str | None = None
    phone: str | None = None


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------

class PlanningPlugin(ExtractorPlugin):
    """Extractor for tasks, events and people."""

    name: str = "planning_people"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=2.0.0 <3.0.0"),
        ModuleRequirement(name="people", range=">=1.1.0 <2.0.0"),
        ModuleRequirement(name="places", range=">=1.0.0 <2.0.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [TaskProposal, EventProposal, PersonProposal]

    def prompt_snippet(self) -> str:
        """Return instruction text (the kernel owns the JSON contract).

        No fields beyond the ``kind`` schema are repeated here — the
        merged schema fence is built by the extraction host.
        """
        return ""

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return additional linking context.

        Person/Location context lines are provided by the people plugin;
        this plugin returns an empty string.
        """
        return ""

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()

        if isinstance(proposal, TaskProposal):
            return [
                Task(
                    name=proposal.name,
                    description=proposal.description,
                    priority=proposal.priority,
                    estimated_duration=proposal.estimated_duration,
                    due_date=proposal.due_date,
                    status=TaskStatus.OPEN,
                    derived_from=ctx.inbox_iri,
                    created_at=now,
                    updated_at=now,
                ).to_tdb()
            ]

        if isinstance(proposal, EventProposal):
            event_doc: dict[str, Any] = Event(
                name=proposal.name,
                description=proposal.description,
                start_datetime=proposal.start_datetime,
                end_datetime=proposal.end_datetime,
                location=None,
                status=EventStatus.OPEN,
                derived_from=ctx.inbox_iri,
                created_at=now,
                updated_at=now,
            ).to_tdb()

            if proposal.location_name:
                loc_iri = await ctx.create_or_link(
                    "Location", proposal.location_name, lambda: None
                )
                if loc_iri:
                    event_doc["location"] = loc_iri

            return [event_doc]

        if isinstance(proposal, PersonProposal):
            person_iri = await ctx.create_or_link(
                "Person", proposal.name, lambda: None
            )
            if person_iri:
                logger.info("person_linked", name=proposal.name, iri=person_iri)
                return []

            contact = None
            if proposal.email or proposal.phone:
                contact = Contact(email=proposal.email, phone=proposal.phone)
            return [Person(name=proposal.name, contact=contact).to_tdb()]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = PlanningPlugin()
