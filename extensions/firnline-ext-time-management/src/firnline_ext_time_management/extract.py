"""Extraction plugin for Task, Event, Routine, Activity, Person, and PARA proposals.

Part of the firnline-ext-time-management reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from firnline_core.models import Provenance, Tag
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_people.models import Contact, Person
from firnline_ext_places.models import Location
from firnline_ext_time_management.models import (
    Activity,
    ActivitySpec,
    Area,
    Event,
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
    project_name: str | None = None
    area_name: str | None = None


class EventProposal(BaseModel):
    kind: Literal["event"] = "event"
    name: str
    description: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    location_name: str | None = None
    project_name: str | None = None
    area_name: str | None = None


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


class ProjectProposal(BaseModel):
    """LLM proposes a Project when the text describes a bounded outcome.

    Projects are finite: they have a clear end state (e.g. "redesign the
    garden by June").  They belong to an Area (ongoing responsibility) and
    may contribute to a Goal (desired world-state).
    """

    kind: Literal["project"] = "project"
    name: str
    description: str | None = None
    target_date: datetime | None = None
    area_name: str | None = None
    goal_name: str | None = None


class AreaProposal(BaseModel):
    """LLM proposes an Area when the text describes an ongoing responsibility.

    Areas have no end date — they are continuous spheres of accountability
    (e.g. "Health", "Finances", "Team leadership").  They are keyed by name
    (Lexical) so duplicate names refer to the same Area.
    """

    kind: Literal["area"] = "area"
    name: str
    description: str | None = None


class GoalProposal(BaseModel):
    """LLM proposes a Goal when the text describes a desired future world-state.

    Goals are horizon outcomes (e.g. "Run a marathon", "Save 50k for a
    house down-payment").  They have a target date and success criteria
    that describe when the goal is achieved.
    """

    kind: Literal["goal"] = "goal"
    name: str
    description: str | None = None
    target_date: datetime | None = None
    success_criteria: str | None = None


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class TimeManagementPlugin(ExtractorPlugin):
    """Extractor for tasks, events, routines, activities and people."""

    name: str = "time_management_extractor"
    # Person and Location are listed for entity-linking/index purposes
    # (this plugin resolves them via ensure_entity but never creates them directly).
    produces: list[str] = ["Task", "Event", "Person", "Location", "Routine", "Activity", "Project", "Area", "Goal"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.2.0 <0.3.0"),
        ModuleRequirement(name="people", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="places", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [
            TaskProposal, EventProposal, PersonProposal,
            RoutineProposal, ActivityProposal,
            ProjectProposal, AreaProposal, GoalProposal,
        ]

    def prompt_snippet(self) -> str:
        """Instruction text for the extraction agent.

        The kernel owns the JSON schema fence; this is guidance only.
        """
        return (
            "When the text describes a recurring practice, checklist, or set of steps "
            "(e.g. 'every morning I…', 'my gym routine is…'), propose a Routine with "
            "one or more steps.  Each step MUST have a 'name' (a short label for the "
            "step).  Optional step fields: 'description', 'cadence_days' (interval in "
            "days), 'priority' (integer), 'estimated_duration' (minutes as integer), "
            "and 'step_type' ('activity' or 'task', defaults to 'activity').  "
            "A Routine's 'required_context' field, if present, is a list of context "
            "name strings (e.g. ['Home', 'Work']).  "
            "When the text describes a concrete performed or planned session of a routine "
            "or an ad-hoc activity, propose an Activity.  Link activities to existing "
            "routines by name via routine_name when applicable.\n\n"
            "PARA semantics (Projects, Areas, Goals):\n"
            "- Projects are bounded outcomes with a clear end — they finish "
            "(e.g. 'redesign the garden by June', 'publish the quarterly report'). "
            "Propose a Project when the text introduces a named initiative with a "
            "completion target.\n"
            "- Areas are ongoing responsibilities without an end date — they are "
            "continuous spheres of accountability (e.g. 'Health', 'Finances', "
            "'Team leadership').  Propose an Area when the text describes a "
            "standing domain of responsibility.\n"
            "- Goals are desired horizon world-states (e.g. 'run a marathon', "
            "'save 50k for a house down-payment').  Propose a Goal when the text "
            "describes an aspirational outcome.  Goals have a target_date and "
            "success_criteria.\n"
            "- Tasks should be linked to a Project or Area via project_name / area_name "
            "when the text implies the task belongs to that project or area.\n"
            "- Events should be linked to a Project or Area via project_name / area_name "
            "when the text implies the event belongs to that project or area.\n"
            "- Projects should be linked to an Area (via area_name) and/or Goal "
            "(via goal_name) when the text describes that relationship."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return Person, Location, Routine, Project, Area, and Goal names for entity linking."""
        lines: list[str] = []
        for name, iri in index.names("Person"):
            lines.append(f"Person|{iri}|{name}")
        for name, iri in index.names("Location"):
            lines.append(f"Location|{iri}|{name}")
        for name, iri in index.names("Routine"):
            lines.append(f"Routine|{iri}|{name}")
        for name, iri in index.names("Project"):
            lines.append(f"Project|{iri}|{name}")
        for name, iri in index.names("Area"):
            lines.append(f"Area|{iri}|{name}")
        for name, iri in index.names("Goal"):
            lines.append(f"Goal|{iri}|{name}")
        return "\n".join(lines)

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        # ── helper: resolve a name to a context IRI ──────────────────
        async def _resolve_context(type_name: str, name: str | None) -> str | None:
            """Look up *name* as an existing *type_name* entity.

            Returns the IRI if found, ``None`` otherwise.
            Never auto-creates (factory returns ``None``).
            """
            if not name:
                return None
            return await ctx.ensure_entity(type_name, name, lambda: None)

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
            task_doc = task.to_tdb()

            # Wire project / area context links
            contexts: list[str] = []
            project_iri = await _resolve_context("Project", proposal.project_name)
            if project_iri:
                contexts.append(project_iri)
            area_iri = await _resolve_context("Area", proposal.area_name)
            if area_iri:
                contexts.append(area_iri)
            if contexts:
                task_doc["contexts"] = contexts

            return [task_doc]

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

            # Wire project / area context links
            contexts: list[str] = []
            project_iri = await _resolve_context("Project", proposal.project_name)
            if project_iri:
                contexts.append(project_iri)
            area_iri = await _resolve_context("Area", proposal.area_name)
            if area_iri:
                contexts.append(area_iri)
            if contexts:
                event_doc["contexts"] = contexts

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

            # Resolve required_context names → IRIs (Context references)
            required_iri_list: list[str] = []
            for ctx_name in (proposal.required_context or []):
                iri: str | None = None
                for ctx_type in ("Project", "Area", "Goal"):
                    iri = await _resolve_context(ctx_type, ctx_name)
                    if iri:
                        break
                if not iri:
                    # Fall back to Tag (most generic Context subclass)
                    iri = await ctx.ensure_entity(
                        "Tag",
                        ctx_name,
                        lambda n=ctx_name: Tag(
                            name=n,
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
                if iri:
                    required_iri_list.append(iri)

            routine = Routine(
                name=proposal.name,
                required_context=required_iri_list,
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

        # ── Project ───────────────────────────────────────────────────
        if isinstance(proposal, ProjectProposal):
            project = Project(
                name=proposal.name,
                description=proposal.description,
                target_date=proposal.target_date,
                status=ProjectStatus.ACTIVE,
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
            project_doc = project.to_tdb()

            # Wire area / goal context links
            contexts: list[str] = []
            area_iri = await _resolve_context("Area", proposal.area_name)
            if area_iri:
                contexts.append(area_iri)
            goal_iri = await _resolve_context("Goal", proposal.goal_name)
            if goal_iri:
                contexts.append(goal_iri)
            if contexts:
                project_doc["contexts"] = contexts

            return [project_doc]

        # ── Area ──────────────────────────────────────────────────────
        if isinstance(proposal, AreaProposal):
            area_iri = await ctx.ensure_entity(
                "Area",
                proposal.name,
                lambda: Area(
                    name=proposal.name,
                    description=proposal.description,
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
            if area_iri:
                logger.info("area_linked", name=proposal.name, iri=area_iri)
            return []

        # ── Goal ──────────────────────────────────────────────────────
        if isinstance(proposal, GoalProposal):
            goal = Goal(
                name=proposal.name,
                description=proposal.description,
                success_criteria=proposal.success_criteria,
                target_date=proposal.target_date,
                status=GoalStatus.ACTIVE,
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
            return [goal.to_tdb()]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = TimeManagementPlugin()
