"""Plugin-specific tests for firnline-ext-decisions — proposal parsing, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timezone

from firnline_core.plugins import EntityIndex
from firnline_ext_decisions.extract import (
    ConsideredOptionProposal,
    DecisionProposal,
    DecisionsExtractor,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Proposal model validation
# ---------------------------------------------------------------------------


class TestDecisionProposal:
    def test_minimal_decision(self):
        p = DecisionProposal(title="Use Python", decision="We chose Python for the backend")
        assert p.kind == "decision"
        assert p.title == "Use Python"
        assert p.decision == "We chose Python for the backend"
        assert p.status == "draft"
        assert p.context is None
        assert p.consequences is None
        assert p.options == []

    def test_full_decision(self):
        p = DecisionProposal(
            title="Adopt Rust for core",
            context="Performance issues with Python",
            decision="Rewrite the hot-path in Rust",
            consequences="Need to train the team on Rust",
            status="proposed",
            options=[
                ConsideredOptionProposal(
                    name="Stay with Python",
                    pros=["Familiar", "No migration cost"],
                    cons=["Slow"],
                    rejection_reason="Too slow for our use case",
                ),
                ConsideredOptionProposal(
                    name="Use Go instead",
                    pros=["Fast", "Easy to learn"],
                    cons=["Less ecosystem support"],
                ),
            ],
        )
        assert p.title == "Adopt Rust for core"
        assert p.context == "Performance issues with Python"
        assert p.decision == "Rewrite the hot-path in Rust"
        assert p.consequences == "Need to train the team on Rust"
        assert p.status == "proposed"
        assert len(p.options) == 2
        assert p.options[0].name == "Stay with Python"
        assert p.options[0].pros == ["Familiar", "No migration cost"]
        assert p.options[0].cons == ["Slow"]
        assert p.options[0].rejection_reason == "Too slow for our use case"
        assert p.options[1].rejection_reason is None

    def test_default_status_is_draft(self):
        p = DecisionProposal(title="T", decision="D")
        assert p.status == "draft"

    def test_status_must_be_valid_literal(self):
        from pydantic import ValidationError

        with __import__("pytest").raises(ValidationError):
            DecisionProposal(title="T", decision="D", status="invalid")

    def test_accepted_status_allowed(self):
        p = DecisionProposal(title="T", decision="D", status="accepted")
        assert p.status == "accepted"

    def test_rejected_status_disallowed(self):
        """rejected is not in the Literal — LLM should not propose it."""
        from pydantic import ValidationError

        with __import__("pytest").raises(ValidationError):
            DecisionProposal(title="T", decision="D", status="rejected")


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def setup_method(self):
        self.plugin = DecisionsExtractor()

    def test_name(self):
        assert self.plugin.name == "decisions_extractor"

    def test_produces(self):
        assert self.plugin.produces == ["Decision"]

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {"decisions": ">=0.1.0 <0.2.0"}

    def test_proposal_models_count(self):
        models = self.plugin.proposal_models()
        assert len(models) == 1
        assert models[0].__name__ == "DecisionProposal"

    def test_prompt_snippet_has_no_json_fences(self):
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet

    def test_prompt_snippet_mentions_decision(self):
        snippet = self.plugin.prompt_snippet()
        assert "Decision" in snippet

    def test_linking_context_with_entries(self):
        import asyncio

        index = EntityIndex()
        index.register("Decision", "Adopt Rust", "Decision/adopt_rust")
        index.register("Decision", "Use Python", "Decision/use_python")

        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert "Existing decisions:" in result
        assert "Adopt Rust <Decision/adopt_rust>" in result
        assert "Use Python <Decision/use_python>" in result

    def test_linking_context_empty_index(self):
        import asyncio

        index = EntityIndex()
        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert result == ""


# ---------------------------------------------------------------------------
# Build-document integration tests
# ---------------------------------------------------------------------------


class _FakeBuildContext:
    """Minimal BuildContext double for testing build_documents."""

    def __init__(self, captured_iri: str = "InboxNote/test123"):
        self.captured_iri = captured_iri
        self.tdb = None
        self.branch = "main"

    def now(self) -> datetime:
        return datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


class TestBuildDocuments:
    def setup_method(self):
        self.plugin = DecisionsExtractor()

    async def test_minimal_decision_builds_with_provenance(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use Python",
            decision="We chose Python for the backend",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Decision"
        assert doc["title"] == "Use Python"
        assert doc["decision"] == "We chose Python for the backend"
        assert doc["status"] == "draft"
        assert doc["created_at"] == "2026-07-07T12:00:00Z"
        assert doc["updated_at"] == "2026-07-07T12:00:00Z"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"] == {
            "@type": "Provenance",
            "agent": "ingestd",
            "at": "2026-07-07T12:00:00Z",
            "method": "llm_extraction",
        }

    async def test_full_decision_with_context_and_consequences(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Adopt Rust",
            context="Slow Python performance",
            decision="Rewrite hot-path in Rust",
            consequences="Team needs Rust training",
            status="accepted",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["@type"] == "Decision"
        assert doc["context"] == "Slow Python performance"
        assert doc["decision"] == "Rewrite hot-path in Rust"
        assert doc["consequences"] == "Team needs Rust training"
        assert doc["status"] == "accepted"

    async def test_decision_with_options_embeds_considered_options(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Choose DB",
            decision="PostgreSQL",
            options=[
                ConsideredOptionProposal(
                    name="SQLite",
                    pros=["Simple", "No server"],
                    cons=["Not scalable"],
                    rejection_reason="Won't scale for production",
                ),
                ConsideredOptionProposal(
                    name="MySQL",
                    pros=["Fast reads"],
                    cons=["Less features"],
                ),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "options" in doc
        options = doc["options"]
        assert len(options) == 2

        assert options[0]["@type"] == "ConsideredOption"
        assert options[0]["name"] == "SQLite"
        assert options[0]["pros"] == ["Simple", "No server"]
        assert options[0]["cons"] == ["Not scalable"]
        assert options[0]["rejection_reason"] == "Won't scale for production"

        assert options[1]["@type"] == "ConsideredOption"
        assert options[1]["name"] == "MySQL"
        # None should be excluded by to_tdb (exclude_none=True)
        assert "rejection_reason" not in options[1]

    async def test_decision_no_options_has_empty_options_list(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(title="Simple choice", decision="Do it")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["options"] == []

    async def test_decision_empty_optional_fields_not_in_output(self):
        """context and consequences should be absent when None (exclude_none)."""
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(title="T", decision="D")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "context" not in doc
        assert "consequences" not in doc

    async def test_non_decision_proposal_returns_empty(self):
        """build_documents should silently return [] for unknown proposal types."""
        ctx = _FakeBuildContext()
        from pydantic import BaseModel

        class FakeProposal(BaseModel):
            kind: str = "fake"

        docs = await self.plugin.build_documents(FakeProposal(), ctx)
        assert docs == []
