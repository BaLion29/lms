"""Extraction plugin for Decision proposals.

Part of the firnline-ext-decisions extension.
Implements the ``ExtractorPlugin`` protocol.  Registered via the
``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from firnline_core.models import Provenance
from firnline_core.plugins import BuildContext, ExtractorPlugin, ModuleRequirement
from firnline_core.tdb import short_iri
from firnline_ext_decisions.models import ConsideredOption, Decision, DecisionStatus


# ---------------------------------------------------------------------------
# Proposal models
# ---------------------------------------------------------------------------


class ConsideredOptionProposal(BaseModel):
    """Flat, LLM-friendly representation of a considered alternative."""

    name: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None


class DecisionProposal(BaseModel):
    """LLM proposes a Decision when the text records a choice that was made or is being considered."""

    kind: Literal["decision"] = "decision"
    title: str
    context: str | None = None
    decision: str
    consequences: str | None = None
    status: Literal["draft", "proposed", "accepted"] = "draft"
    options: list[ConsideredOptionProposal] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class DecisionsExtractor(ExtractorPlugin):
    """Extractor for ADR-style decision records."""

    name: str = "decisions_extractor"
    produces: list[str] = ["Decision"]
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="decisions", range=">=0.1.0 <0.2.0"),
    ]

    def proposal_models(self) -> list[type[BaseModel]]:
        return [DecisionProposal]

    def prompt_snippet(self) -> str:
        """Instruction text for the extraction agent.

        The kernel owns the JSON schema fence; this is guidance only.
        """
        return (
            "When the text records a choice that was made or is being considered "
            "(e.g. \"I've decided to…\", \"we chose X over Y because…\", "
            "\"the team decided to adopt…\"), propose a Decision.  Include the "
            "context that led to the decision, the decision itself, any "
            "foreseen consequences, and considered alternatives with their "
            "pros/cons and rejection reasons if stated in the text."
        )

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Return existing Decision titles for entity linking context."""
        entries = index.names("Decision")
        if not entries:
            return ""
        items = ", ".join(f"{name} <{iri}>" for name, iri in entries)
        return f"Existing decisions: {items}"

    async def build_documents(
        self, proposal: BaseModel, ctx: BuildContext
    ) -> list[dict[str, Any]]:
        """Convert a DecisionProposal into a TerminusDB Decision document dict."""
        if not isinstance(proposal, DecisionProposal):
            return []

        now = ctx.now()
        source_iri = short_iri(ctx.captured_iri)
        confidence = getattr(proposal, "confidence", None)

        decision = Decision(
            title=proposal.title,
            context=proposal.context,
            decision=proposal.decision,
            consequences=proposal.consequences,
            status=DecisionStatus(proposal.status),
            options=[
                ConsideredOption(
                    name=opt.name,
                    pros=opt.pros,
                    cons=opt.cons,
                    rejection_reason=opt.rejection_reason,
                )
                for opt in proposal.options
            ],
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

        return [decision.to_tdb()]


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = DecisionsExtractor()
