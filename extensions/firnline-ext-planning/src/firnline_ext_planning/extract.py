"""Extraction plugin for Task, Event, and Person proposals.

Part of the firnline-ext-planning reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from firnline_core.models import Provenance
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_people.models import Contact, Person
from firnline_ext_places.models import Location
from firnline_ext_planning.models import Event, EventStatus, Task, TaskStatus

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
    produces: list[str] = ["Task", "Event", "Person", "Location"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="people", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="places", range=">=0.1.0 <0.2.0"),
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
        """Return Person and Location names for linking context."""
        lines: list[str] = []
        for name, iri in index.names("Person"):
            lines.append(f"Person|{iri}|{name}")
        for name, iri in index.names("Location"):
            lines.append(f"Location|{iri}|{name}")
        return "\n".join(lines)

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        if isinstance(proposal, TaskProposal):
            task = Task(
                name=proposal.name,
                description=proposal.description,
                priority=proposal.priority,
                estimated_duration=proposal.estimated_duration,
                due_date=proposal.due_date,
                status=TaskStatus.OPEN,
                created_at=now,
                updated_at=now,
                anchor_at=proposal.due_date,
                provenance=Provenance(
                    source=source_iri,
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [task.to_tdb()]

        if isinstance(proposal, EventProposal):
            event = Event(
                name=proposal.name,
                description=proposal.description,
                start_datetime=proposal.start_datetime,
                end_datetime=proposal.end_datetime,
                location=None,
                status=EventStatus.OPEN,
                created_at=now,
                updated_at=now,
                anchor_at=proposal.start_datetime,
                provenance=Provenance(
                    source=source_iri,
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            event_doc = event.to_tdb()

            if proposal.location_name:
                loc_iri = await ctx.ensure_entity(
                    "Location",
                    proposal.location_name,
                    lambda: Location(
                        name=proposal.location_name,
                        created_at=now,
                        updated_at=now,
                        provenance=Provenance(
                            source=source_iri,
                            agent="ingestd",
                            at=now,
                            method="llm_extraction",
                            confidence=confidence,
                        ),
                    ).to_tdb(),
                )
                if loc_iri:
                    event_doc["location"] = loc_iri

            return [event_doc]

        if isinstance(proposal, PersonProposal):
            person_iri = await ctx.ensure_entity(
                "Person",
                proposal.name,
                lambda: Person(
                    name=proposal.name,
                    created_at=now,
                    updated_at=now,
                    contact=(
                        Contact(email=proposal.email, phone=proposal.phone)
                        if (proposal.email or proposal.phone)
                        else None
                    ),
                    provenance=Provenance(
                        source=source_iri,
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                ).to_tdb(),
            )
            if person_iri:
                logger.info("person_linked", name=proposal.name, iri=person_iri)
                return []

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = PlanningPlugin()
