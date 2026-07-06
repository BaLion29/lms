"""Built-in extraction plugin for Task, Event, Reminder, and Person proposals.

Implements the ``ExtractorPlugin`` protocol.  Registered via the
``lms.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import structlog
from pydantic import BaseModel, Field

from lms_core.models import (
    Contact,
    Event,
    EventStatus,
    Location,
    Person,
    Reminder,
    Task,
    TaskStatus,
)
from lms_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Proposal models  (moved verbatim from ingestd.extraction)
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


class ReminderProposal(BaseModel):
    kind: Literal["reminder"] = "reminder"
    name: str
    description: str | None = None


class PersonProposal(BaseModel):
    kind: Literal["person"] = "person"
    name: str
    email: str | None = None
    phone: str | None = None


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------

_JSON_SCHEMA = """{
  "proposals": [
    {
      "kind": "task",
      "name": "<string>",
      "description": "<string or null>",
      "priority": <integer 1-5 or null>,
      "estimated_duration": <minutes or null>,
      "due_date": "<ISO 8601 datetime or null>"
    },
    {
      "kind": "event",
      "name": "<string>",
      "description": "<string or null>",
      "start_datetime": "<ISO 8601 datetime or null>",
      "end_datetime": "<ISO 8601 datetime or null>",
      "location_name": "<string or null>"
    },
    {
      "kind": "reminder",
      "name": "<string>",
      "description": "<string or null>"
    },
    {
      "kind": "person",
      "name": "<string>",
      "email": "<string or null>",
      "phone": "<string or null>"
    }
  ],
  "reasoning": "<string: brief explanation of the extraction>",
  "confidence": <float 0.0 to 1.0>
}"""


class PlanningPeoplePlugin(ExtractorPlugin):
    """Extractor for tasks, events, reminders and people."""

    name: str = "planning_people"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=1.0.0 <2.0.0"),
        ModuleRequirement(name="people", range=">=1.0.0 <2.0.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [TaskProposal, EventProposal, ReminderProposal, PersonProposal]

    def prompt_snippet(self) -> str:
        """Return the JSON schema as a markdown code block.

        The caller prepends the core rules and appends this block so the
        combined prompt is byte-identical to the pre-refactor prompt.
        """
        return f"\n\n```json\n{_JSON_SCHEMA}\n```"

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return additional linking context.

        The pipeline already produces the built-in people/locations block, so
        this plugin returns an empty string — no duplication.
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
                # If loc_iri is None, a new location is needed — the
                # pipeline handles the separate insert-and-fixup step.

            return [event_doc]

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

        if isinstance(proposal, PersonProposal):
            person_iri = await ctx.create_or_link(
                "Person", proposal.name, lambda: None
            )
            if person_iri:
                logger.info("person_linked", name=proposal.name, iri=person_iri)
                return []  # already exists — drop

            contact = None
            if proposal.email or proposal.phone:
                contact = Contact(email=proposal.email, phone=proposal.phone)
            return [Person(name=proposal.name, contact=contact).to_tdb()]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = PlanningPeoplePlugin()
