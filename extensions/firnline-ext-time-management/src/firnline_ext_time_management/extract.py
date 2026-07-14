"""Extraction plugin for Task, Event, Routine, Activity, and Person proposals.

Part of the firnline-ext-time-management reference extension.
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
from firnline_ext_time_management.models import (
    Activity,
    ActivitySpec,
    Event,
    EventStatus,
    Routine,
    RoutineStep,
    Task,
    TaskSpec,
    TaskStatus,
)

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


class RoutineStepSpec(BaseModel):
    """Flat, LLM-friendly shape for a single Routine step.

    The ``step_type`` discriminator is mapped to RoutineStep's
    ``@oneOf`` (ActivitySpec vs TaskSpec) in ``build_documents``.
    """

    name: str
    cadence_days: int | None = None
    step_type: Literal["activity", "task"] = "activity"
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None


class RoutineProposal(BaseModel):
    kind: Literal["routine"] = "routine"
    name: str
    required_context: list[str] | None = None  # context class names (LLM-facing)
    steps: list[RoutineStepSpec]


class ActivityProposal(BaseModel):
    kind: Literal["activity"] = "activity"
    name: str
    description: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    routine_name: str | None = None


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class TimeManagementPlugin(ExtractorPlugin):
    """Extractor for tasks, events, routines, activities and people."""

    name: str = "time_management_extractor"
    # Person and Location are listed for entity-linking/index purposes
    # (this plugin resolves them via ensure_entity but never creates them directly).
    produces: list[str] = ["Task", "Event", "Person", "Location", "Routine", "Activity"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="people", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="places", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [TaskProposal, EventProposal, PersonProposal, RoutineProposal, ActivityProposal]

    def prompt_snippet(self) -> str:
        """Instruction text for the extraction agent.

        The kernel owns the JSON schema fence; this is guidance only.
        """
        return (
            "When the text describes a recurring practice, checklist, or set of steps "
            "(e.g. 'every morning I…', 'my gym routine is…'), propose a Routine with "
            "one or more steps.  Each step must have a step_type ('activity' or 'task') "
            "and can include a cadence_days interval.  "
            "When the text describes a concrete performed or planned session of a routine "
            "or an ad-hoc activity, propose an Activity.  Link activities to existing "
            "routines by name via routine_name when applicable."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return Person, Location, and Routine names for entity linking."""
        lines: list[str] = []
        for name, iri in index.names("Person"):
            lines.append(f"Person|{iri}|{name}")
        for name, iri in index.names("Location"):
            lines.append(f"Location|{iri}|{name}")
        for name, iri in index.names("Routine"):
            lines.append(f"Routine|{iri}|{name}")
        return "\n".join(lines)

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        # ── Task ──────────────────────────────────────────────────────
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
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [task.to_tdb()]

        # ── Event ─────────────────────────────────────────────────────
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
                derived_from=[source_iri],
                provenance=Provenance(
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
                        derived_from=[source_iri],
                        provenance=Provenance(
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

        # ── Person ────────────────────────────────────────────────────
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
                    derived_from=[source_iri],
                    provenance=Provenance(
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

        # ── Routine ───────────────────────────────────────────────────
        if isinstance(proposal, RoutineProposal):
            steps: list[RoutineStep] = []
            for step_spec in proposal.steps:
                if step_spec.step_type == "task":
                    spec = TaskSpec(
                        name=step_spec.name,
                        description=step_spec.description,
                        priority=step_spec.priority,
                        estimated_duration=step_spec.estimated_duration,
                    )
                    step = RoutineStep(
                        name=step_spec.name,
                        cadence_days=step_spec.cadence_days,
                        task=spec,
                        created_at=now,
                        updated_at=now,
                        derived_from=[source_iri],
                        provenance=Provenance(
                            agent="ingestd",
                            at=now,
                            method="llm_extraction",
                            confidence=confidence,
                        ),
                    )
                else:  # activity
                    spec = ActivitySpec(
                        name=step_spec.name,
                        description=step_spec.description,
                        priority=step_spec.priority,
                        estimated_duration=step_spec.estimated_duration,
                    )
                    step = RoutineStep(
                        name=step_spec.name,
                        cadence_days=step_spec.cadence_days,
                        activity=spec,
                        created_at=now,
                        updated_at=now,
                        derived_from=[source_iri],
                        provenance=Provenance(
                            agent="ingestd",
                            at=now,
                            method="llm_extraction",
                            confidence=confidence,
                        ),
                    )
                steps.append(step)

            routine = Routine(
                name=proposal.name,
                required_context=proposal.required_context or [],
                steps=steps,
                created_at=now,
                updated_at=now,
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [routine.to_tdb()]

        # ── Activity ──────────────────────────────────────────────────
        if isinstance(proposal, ActivityProposal):
            activity = Activity(
                name=proposal.name,
                description=proposal.description,
                start_datetime=proposal.start_datetime,
                end_datetime=proposal.end_datetime,
                priority=proposal.priority,
                estimated_duration=proposal.estimated_duration,
                routine=None,
                created_at=now,
                updated_at=now,
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            activity_doc = activity.to_tdb()

            if proposal.routine_name:
                routine_iri = await ctx.ensure_entity(
                    "Routine",
                    proposal.routine_name,
                    lambda: None,  # Do NOT auto-create a Routine from an activity mention
                )
                if routine_iri:
                    activity_doc["routine"] = routine_iri

            return [activity_doc]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = TimeManagementPlugin()
