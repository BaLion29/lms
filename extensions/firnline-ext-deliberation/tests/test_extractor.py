"""Plugin-specific tests for firnline-ext-deliberation — proposal parsing, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from firnline_core.plugins import EntityIndex
from firnline_ext_deliberation.extract import (
    DecisionProposal,
    DeliberationExtractor,
    ProblemProposal,
    QuestionProposal,
    plugin,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# DecisionProposal
# ---------------------------------------------------------------------------


class TestDecisionProposal:
    def test_minimal_decision(self):
        p = DecisionProposal(title="Use FastAPI", decision="We will use FastAPI")
        assert p.kind == "decision"
        assert p.title == "Use FastAPI"
        assert p.decision == "We will use FastAPI"
        assert p.context == []
        assert p.options == []
        assert p.addresses == []
        assert p.consequences is None

    def test_full_decision(self):
        p = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
            context=["Context/project-scope", "Context/requirements"],
            consequences="Team needs training",
            status="accepted",
            options=[
                {"name": "FastAPI", "pros": ["Fast", "Modern"], "cons": ["New to team"]},
                {"name": "Flask", "pros": ["Familiar"], "cons": ["Slower"], "rejection_reason": "Lacks async support"},
            ],
            addresses=["Problem/perf-issues"],
        )
        assert p.kind == "decision"
        assert p.status == "accepted"
        assert p.consequences == "Team needs training"
        assert len(p.context) == 2
        assert "Context/project-scope" in p.context
        assert len(p.options) == 2
        assert p.options[0].name == "FastAPI"
        assert p.options[1].rejection_reason == "Lacks async support"
        assert p.addresses == ["Problem/perf-issues"]

    def test_default_status_is_draft(self):
        p = DecisionProposal(title="Use FastAPI", decision="We will use FastAPI")
        assert p.status == "draft"

    def test_status_must_be_valid_literal(self):
        with pytest.raises(ValidationError):
            DecisionProposal(title="T", decision="D", status="invalid")

    def test_accepted_status_allowed(self):
        p = DecisionProposal(title="T", decision="D", status="accepted")
        assert p.status == "accepted"

    def test_rejected_status_disallowed(self):
        with pytest.raises(ValidationError):
            DecisionProposal(title="T", decision="D", status="rejected")


# ---------------------------------------------------------------------------
# ProblemProposal
# ---------------------------------------------------------------------------


class TestProblemProposal:
    def test_minimal_problem(self):
        p = ProblemProposal(title="Slow API responses")
        assert p.kind == "problem"
        assert p.title == "Slow API responses"
        assert p.description is None
        assert p.impact is None
        assert p.status == "open"

    def test_full_problem(self):
        p = ProblemProposal(
            title="Slow API responses",
            description="Endpoints take >5s under load",
            impact="Users experience timeouts in production",
            status="investigating",
        )
        assert p.kind == "problem"
        assert p.description == "Endpoints take >5s under load"
        assert p.impact == "Users experience timeouts in production"
        assert p.status == "investigating"

    def test_default_status_is_open(self):
        p = ProblemProposal(title="Memory leak")
        assert p.status == "open"

    def test_resolved_status_disallowed(self):
        with pytest.raises(ValidationError):
            ProblemProposal(title="T", status="resolved")


# ---------------------------------------------------------------------------
# QuestionProposal
# ---------------------------------------------------------------------------


class TestQuestionProposal:
    def test_minimal_question(self):
        p = QuestionProposal(question="What database should we use?")
        assert p.kind == "question"
        assert p.question == "What database should we use?"
        assert p.answer is None
        assert p.status == "open"

    def test_full_question(self):
        p = QuestionProposal(
            question="What database should we use?",
            answer="PostgreSQL for relational data, Redis for caching",
            status="answered",
        )
        assert p.kind == "question"
        assert p.answer == "PostgreSQL for relational data, Redis for caching"
        assert p.status == "answered"

    def test_default_status_is_open(self):
        p = QuestionProposal(question="Is this a test?")
        assert p.status == "open"

    def test_closed_status_disallowed(self):
        with pytest.raises(ValidationError):
            QuestionProposal(question="Q?", status="closed")


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def setup_method(self):
        self.plugin = DeliberationExtractor()

    def test_name(self):
        assert self.plugin.name == "deliberation_extractor"

    def test_produces(self):
        assert self.plugin.produces == ["Decision", "Problem", "Question"]

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {"deliberation": ">=0.1.0 <0.2.0"}

    def test_proposal_models_count(self):
        models = self.plugin.proposal_models()
        assert len(models) == 3

    def test_proposal_model_names(self):
        models = self.plugin.proposal_models()
        names = {m.__name__ for m in models}
        assert names == {"DecisionProposal", "ProblemProposal", "QuestionProposal"}

    def test_prompt_snippet_has_no_json_fences(self):
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet

    def test_prompt_snippet_mentions_all_kinds(self):
        snippet = self.plugin.prompt_snippet()
        assert "Decision" in snippet
        assert "Problem" in snippet
        assert "Question" in snippet

    def test_linking_context_with_entries(self):
        import asyncio

        index = EntityIndex()
        index.register("Decision", "Use FastAPI", "Decision/fastapi")
        index.register("Problem", "Slow API", "Problem/slow-api")
        index.register("Question", "DB choice", "Question/db-choice")

        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert "Decision" in result
        assert "Decision/fastapi" in result
        assert "Problem" in result
        assert "Problem/slow-api" in result
        assert "Question" in result
        assert "Question/db-choice" in result

    def test_linking_context_empty_index(self):
        import asyncio

        index = EntityIndex()
        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert result == ""

    def test_module_level_plugin_is_deliberation_extractor(self):
        assert isinstance(plugin, DeliberationExtractor)


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
        return datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


class TestBuildDocuments:
    def setup_method(self):
        self.plugin = DeliberationExtractor()

    # ── Decision ──────────────────────────────────────────────────

    async def test_minimal_decision_builds_with_provenance(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Decision"
        assert doc["title"] == "Use FastAPI"
        assert doc["decision"] == "We will use FastAPI"
        assert doc["status"] == "draft"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"] == {
            "@type": "Provenance",
            "agent": "ingestd",
            "at": "2026-07-17T12:00:00Z",
            "method": "llm_extraction",
        }

    async def test_full_decision_with_context_as_iris(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
            context=["Context/project-scope"],
            consequences="Training needed",
            status="accepted",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["@type"] == "Decision"
        assert doc["status"] == "accepted"
        assert doc["context"] == ["Context/project-scope"]
        assert doc["consequences"] == "Training needed"

    async def test_decision_with_options_embeds_considered_options(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
            options=[
                {"name": "FastAPI", "pros": ["Fast"], "cons": ["New"]},
                {"name": "Flask", "pros": ["Familiar"], "rejection_reason": "No async"},
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert len(doc["options"]) == 2
        opt0 = doc["options"][0]
        assert opt0["@type"] == "ConsideredOption"
        assert opt0["name"] == "FastAPI"
        assert opt0["pros"] == ["Fast"]
        assert opt0["cons"] == ["New"]
        assert "rejection_reason" not in opt0 or opt0.get("rejection_reason") is None
        opt1 = doc["options"][1]
        assert opt1["rejection_reason"] == "No async"

    async def test_decision_no_options_has_empty_options_list(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["options"] == []

    async def test_decision_empty_optional_fields_not_in_output(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        # consequences is None → should be absent or None in output
        assert doc.get("consequences") is None or "consequences" not in doc
        # supersedes is None → should be absent
        assert doc.get("supersedes") is None or "supersedes" not in doc

    async def test_decision_context_is_list_of_iris(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
            context=["Context/a", "Context/b"],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert isinstance(doc["context"], list)
        assert doc["context"] == ["Context/a", "Context/b"]

    async def test_decision_with_addresses(self):
        ctx = _FakeBuildContext()
        proposal = DecisionProposal(
            title="Use FastAPI",
            decision="We will use FastAPI",
            addresses=["Problem/slow-api"],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["addresses"] == ["Problem/slow-api"]

    # ── Problem ────────────────────────────────────────────────────

    async def test_minimal_problem_builds(self):
        ctx = _FakeBuildContext()
        proposal = ProblemProposal(title="Slow API responses")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Problem"
        assert doc["title"] == "Slow API responses"
        assert doc["status"] == "open"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"]["agent"] == "ingestd"
        assert doc["provenance"]["method"] == "llm_extraction"

    async def test_full_problem_builds(self):
        ctx = _FakeBuildContext()
        proposal = ProblemProposal(
            title="Slow API responses",
            description="Endpoints take >5s",
            impact="Timeouts in production",
            status="investigating",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["@type"] == "Problem"
        assert doc["title"] == "Slow API responses"
        assert doc["description"] == "Endpoints take >5s"
        assert doc["impact"] == "Timeouts in production"
        assert doc["status"] == "investigating"

    # ── Question ─────────────────────────────────────────────────

    async def test_minimal_question_builds(self):
        ctx = _FakeBuildContext()
        proposal = QuestionProposal(question="What DB to use?")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Question"
        assert doc["question"] == "What DB to use?"
        assert doc["status"] == "open"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"]["agent"] == "ingestd"

    async def test_full_question_builds(self):
        ctx = _FakeBuildContext()
        proposal = QuestionProposal(
            question="What DB to use?",
            answer="PostgreSQL",
            status="answered",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["@type"] == "Question"
        assert doc["question"] == "What DB to use?"
        assert doc["answer"] == "PostgreSQL"
        assert doc["status"] == "answered"

    # ── Unknown proposal ─────────────────────────────────────────

    async def test_non_deliberation_proposal_returns_empty(self):
        class _UnknownProposal:
            pass

        ctx = _FakeBuildContext()
        docs = await self.plugin.build_documents(_UnknownProposal(), ctx)
        assert docs == []
