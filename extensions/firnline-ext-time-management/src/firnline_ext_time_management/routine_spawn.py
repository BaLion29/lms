"""Extraction plugin that spawns concrete Task and Activity instances from a triggered routine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from firnline_core.models import Provenance
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_time_management.models import Activity, Task, TaskStatus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Proposal models
# ---------------------------------------------------------------------------


class SpawnedStepSpec(BaseModel):
    """Flat, LLM-friendly shape for a single routine step to spawn as a concrete instance."""

    name: str
    step_type: Literal["activity", "task"] = "activity"
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    due_date: datetime | None = None  # task steps
    start_datetime: datetime | None = None  # activity steps
    end_datetime: datetime | None = None  # activity steps


class TriggeredRoutineProposal(BaseModel):
    """LLM proposes this when a captured note indicates a routine was triggered/started/invoked
    and its steps should be spawned as concrete Task/Activity instances now."""

    kind: Literal["triggered_routine"] = "triggered_routine"
    routine_name: str
    steps: list[SpawnedStepSpec]


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class TriggeredRoutineExtractor(ExtractorPlugin):
    """Extractor that spawns the tasks and activities of a triggered routine."""

    name: str = "time_management_triggered_routine"
    produces: list[str] = ["Task", "Activity", "Routine"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [TriggeredRoutineProposal]

    def prompt_snippet(self) -> str:
        # Guidance only; NO ```json fences. Mention "triggered", "routine", "activity", "task".
        return (
            "When a captured note indicates that a routine has been triggered, started, or "
            "invoked (e.g. 'I did my morning routine', 'started my weekly review', 'ran my "
            "gym routine today'), propose a triggered_routine. Set 'routine_name' to the "
            "Routine that was triggered, and expand each of its steps into a concrete "
            "instance to spawn now under 'steps'. Each step MUST have a 'name' and a "
            "'step_type' of 'activity' or 'task' (defaults to 'activity'). Optional step "
            "fields: 'description', 'priority' (integer), 'estimated_duration' (minutes as "
            "integer). Task steps may carry a 'due_date' (ISO datetime). Activity steps may "
            "carry 'start_datetime' and 'end_datetime' (ISO datetimes). Only propose a "
            "triggered_routine when the text clearly indicates the routine was actually "
            "triggered or performed — not when merely describing or defining a routine "
            "(use 'routine' for definitions)."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return known Routine names so the LLM can reference the triggered routine by name."""
        lines: list[str] = []
        for name, iri in index.names("Routine"):
            lines.append(f"Routine|{iri}|{name}")
        return "\n".join(lines)

    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict[str, Any]]:
        """Spawn concrete Task/Activity documents from a triggered routine's steps."""
        if not isinstance(proposal, TriggeredRoutineProposal):
            return []

        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        # Resolve the triggered routine by name — lookup only, NEVER auto-create
        # (mirrors ActivityProposal handler: do not create a Routine from a mention).
        routine_iri = await ctx.ensure_entity("Routine", proposal.routine_name, lambda: None)

        docs: list[dict[str, Any]] = []
        for step in proposal.steps:
            if step.step_type == "task":
                task = Task(
                    name=step.name,
                    description=step.description,
                    priority=step.priority,
                    estimated_duration=step.estimated_duration,
                    due_date=step.due_date,
                    status=TaskStatus.OPEN,
                    derived_from=[source_iri],
                    provenance=Provenance(
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                )
                docs.append(task.to_tdb())
            else:  # activity
                activity = Activity(
                    name=step.name,
                    description=step.description,
                    priority=step.priority,
                    estimated_duration=step.estimated_duration,
                    start_datetime=step.start_datetime,
                    end_datetime=step.end_datetime,
                    routine=routine_iri,  # None if not found; to_tdb excludes None
                    derived_from=[source_iri],
                    provenance=Provenance(
                        agent="ingestd",
                        at=now,
                        method="llm_extraction",
                        confidence=confidence,
                    ),
                )
                docs.append(activity.to_tdb())
        return docs


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = TriggeredRoutineExtractor()
