"""Extraction plugin for Decision, Problem, and Question proposals.

Part of the firnline-ext-deliberation reference extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from firnline_core.models import Provenance
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_deliberation.models import (
    ConsideredOption,
    Decision,
    DecisionStatus,
    Problem,
    ProblemStatus,
    Question,
    QuestionStatus,
)


# ---------------------------------------------------------------------------
# Proposal models
# ---------------------------------------------------------------------------


class ConsideredOptionProposal(BaseModel):
    name: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None


class DecisionProposal(BaseModel):
    kind: Literal["decision"] = "decision"
    title: str
    context: list[str] = Field(default_factory=list)  # IRI refs to Context entities
    decision: str
    consequences: str | None = None
    status: Literal["draft", "proposed", "accepted"] = "draft"
    options: list[ConsideredOptionProposal] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)  # IRI refs to Problem entities


class ProblemProposal(BaseModel):
    kind: Literal["problem"] = "problem"
    title: str
    description: str | None = None
    status: Literal["open", "investigating"] = "open"
    impact: str | None = None


class QuestionProposal(BaseModel):
    kind: Literal["question"] = "question"
    question: str
    answer: str | None = None
    status: Literal["open", "answered"] = "open"


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class DeliberationExtractor(ExtractorPlugin):
    """Extractor for decisions, problems, and questions."""

    name: str = "deliberation_extractor"
    produces: list[str] = ["Decision", "Problem", "Question"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="deliberation", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [DecisionProposal, ProblemProposal, QuestionProposal]

    def prompt_snippet(self) -> str:
        """Instruction text for the extraction agent.

        The kernel owns the JSON schema fence; this is guidance only.
        """
        return (
            "Extract decisions, problems, and questions from the text.\n\n"
            "When the text records a clear choice, acceptance, or rejection of a "
            "course of action, propose a Decision.  Include the decision statement, "
            "a short title, the current status (draft, proposed, or accepted), and "
            "any options that were considered with their pros/cons.  "
            "Use the 'context' field (list of IRI strings) to reference existing "
            "Context entities that informed this decision.  "
            "Use the 'addresses' field (list of IRI strings) to reference existing "
            "Problem entities that this decision addresses.\n\n"
            "When the text describes a problem, issue, challenge, or obstacle, "
            "propose a Problem.  Include a title, an optional description and impact "
            "assessment, and a status of 'open' or 'investigating'.\n\n"
            "When the text poses an open question, uncertainty, or request for "
            "clarification, propose a Question.  Include the question text, an "
            "optional answer if one is provided in the text, and a status of "
            "'open' or 'answered'.\n\n"
            "Prefer referencing existing known entities rather than proposing "
            "duplicates.  Multiple proposals of the same kind can be returned."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return existing Decision, Problem, and Question names for entity linking."""
        parts: list[str] = []

        decisions = index.names("Decision")
        if decisions:
            names = ", ".join(f"{name} <{iri}>" for name, iri in decisions)
            parts.append(f"Existing decisions: {names}")

        problems = index.names("Problem")
        if problems:
            names = ", ".join(f"{name} <{iri}>" for name, iri in problems)
            parts.append(f"Existing problems: {names}")

        questions = index.names("Question")
        if questions:
            names = ", ".join(f"{name} <{iri}>" for name, iri in questions)
            parts.append(f"Existing questions: {names}")

        if not parts:
            return ""
        return "; ".join(parts)

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a single proposal into TerminusDB document dicts."""
        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        # ── Decision ────────────────────────────────────────────────
        if isinstance(proposal, DecisionProposal):
            options = [
                ConsideredOption(
                    name=opt.name,
                    pros=opt.pros,
                    cons=opt.cons,
                    rejection_reason=opt.rejection_reason,
                )
                for opt in proposal.options
            ]

            decision = Decision(
                title=proposal.title,
                decision=proposal.decision,
                status=DecisionStatus(proposal.status),
                context=proposal.context,
                consequences=proposal.consequences,
                options=options,
                addresses=proposal.addresses,
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [decision.to_tdb()]

        # ── Problem ─────────────────────────────────────────────────
        if isinstance(proposal, ProblemProposal):
            problem = Problem(
                title=proposal.title,
                description=proposal.description,
                status=ProblemStatus(proposal.status),
                impact=proposal.impact,
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [problem.to_tdb()]

        # ── Question ────────────────────────────────────────────────
        if isinstance(proposal, QuestionProposal):
            question = Question(
                question=proposal.question,
                answer=proposal.answer,
                status=QuestionStatus(proposal.status),
                derived_from=[source_iri],
                provenance=Provenance(
                    agent="ingestd",
                    at=now,
                    method="llm_extraction",
                    confidence=confidence,
                ),
            )
            return [question.to_tdb()]

        return []


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = DeliberationExtractor()
