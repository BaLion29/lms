"""Plugin-specific tests for firnline-ext-planning — proposal parsing per kind, prompt snippet."""

from __future__ import annotations

from datetime import datetime, timezone

from firnline_ext_planning.extract import (
    EventProposal,
    PersonProposal,
    PlanningPlugin,
    TaskProposal,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Proposal model validation
# ---------------------------------------------------------------------------


class TestTaskProposal:
    def test_minimal_task(self):
        p = TaskProposal(name="Buy milk")
        assert p.kind == "task"
        assert p.name == "Buy milk"
        assert p.description is None

    def test_full_task(self):
        p = TaskProposal(
            name="Review",
            description="Q3 review",
            priority=2,
            estimated_duration=30,
            due_date=datetime(2026, 7, 10, 17, 0, 0, tzinfo=UTC),
        )
        assert p.priority == 2
        assert p.estimated_duration == 30
        assert p.due_date.year == 2026


class TestEventProposal:
    def test_event_with_location(self):
        p = EventProposal(name="Meeting", location_name="Office")
        assert p.kind == "event"
        assert p.location_name == "Office"

    def test_event_minimal(self):
        p = EventProposal(name="Meeting")
        assert p.location_name is None
        assert p.start_datetime is None


class TestPersonProposal:
    def test_person_with_email(self):
        p = PersonProposal(name="Bob", email="bob@example.com")
        assert p.kind == "person"
        assert p.name == "Bob"
        assert p.email == "bob@example.com"

    def test_person_minimal(self):
        p = PersonProposal(name="Alice")
        assert p.email is None
        assert p.phone is None


# ---------------------------------------------------------------------------
# Prompt snippet
# ---------------------------------------------------------------------------


class TestPromptSnippet:
    def setup_method(self):
        self.plugin = PlanningPlugin()

    def test_snippet_has_no_json_fences(self):
        """The kernel owns the JSON contract; plugin snippets provide
        instruction text only — no JSON code fences."""
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def test_name(self):
        assert PlanningPlugin().name == "planning_people"

    def test_requires_has_planning_people_places(self):
        req_names = {r.name for r in PlanningPlugin().requires}
        assert req_names >= {"planning", "people", "places"}

    def test_proposal_models_count(self):
        models = PlanningPlugin().proposal_models()
        assert len(models) == 3
        names = {m.__name__ for m in models}
        assert names == {"TaskProposal", "EventProposal", "PersonProposal"}

    def test_linking_context_returns_empty(self):
        import asyncio
        result = asyncio.run(PlanningPlugin().linking_context(None, index=None, branch=""))
        assert result == ""
