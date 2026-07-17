"""Plugin-specific tests for routine_spawn — proposal parsing, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ValidationError

from firnline_core.plugins import EntityIndex
from firnline_ext_time_management.routine_spawn import (
    SpawnedStepSpec,
    TriggeredRoutineExtractor,
    TriggeredRoutineProposal,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Proposal model validation — TriggeredRoutineProposal
# ---------------------------------------------------------------------------


class TestTriggeredRoutineProposal:
    def test_kind_default(self):
        p = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[SpawnedStepSpec(name="Stretch", step_type="activity")],
        )
        assert p.kind == "triggered_routine"

    def test_minimal_proposal(self):
        p = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[SpawnedStepSpec(name="Stretch")],
        )
        assert p.routine_name == "Morning routine"
        assert len(p.steps) == 1
        assert p.steps[0].name == "Stretch"
        assert p.steps[0].step_type == "activity"

    def test_mixed_steps_with_all_fields(self):
        p = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[
                SpawnedStepSpec(
                    name="Stretch",
                    step_type="activity",
                    description="Morning stretches",
                    priority=1,
                    estimated_duration=10,
                    start_datetime=datetime(2026, 7, 8, 7, 0, 0, tzinfo=UTC),
                    end_datetime=datetime(2026, 7, 8, 7, 15, 0, tzinfo=UTC),
                ),
                SpawnedStepSpec(
                    name="Review PRs",
                    step_type="task",
                    description="Check open PRs",
                    priority=2,
                    estimated_duration=30,
                    due_date=datetime(2026, 7, 10, 17, 0, 0, tzinfo=UTC),
                ),
            ],
        )
        assert len(p.steps) == 2
        # Activity step
        a = p.steps[0]
        assert a.step_type == "activity"
        assert a.description == "Morning stretches"
        assert a.priority == 1
        assert a.estimated_duration == 10
        assert a.start_datetime.year == 2026
        assert a.end_datetime.hour == 7
        # Task step
        t = p.steps[1]
        assert t.step_type == "task"
        assert t.description == "Check open PRs"
        assert t.priority == 2
        assert t.estimated_duration == 30
        assert t.due_date.month == 7

    def test_step_type_rejects_invalid_value(self):
        with pytest.raises(ValidationError):
            SpawnedStepSpec(name="Bad step", step_type="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def setup_method(self):
        self.plugin = TriggeredRoutineExtractor()

    def test_name(self):
        assert self.plugin.name == "time_management_triggered_routine"

    def test_produces(self):
        assert self.plugin.produces == ["Task", "Activity", "Routine"]

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {
            "time_management": ">=0.1.0 <0.2.0",
        }

    def test_proposal_models_count(self):
        models = self.plugin.proposal_models()
        assert len(models) == 1
        names = {m.__name__ for m in models}
        assert names == {"TriggeredRoutineProposal"}

    def test_snippet_has_no_json_fences(self):
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet

    def test_snippet_mentions_triggered_routine_activity_task(self):
        snippet = self.plugin.prompt_snippet()
        assert "triggered" in snippet
        assert "Routine" in snippet
        assert "activity" in snippet
        assert "task" in snippet

    def test_linking_context_with_registered_routine(self):
        import asyncio

        index = EntityIndex()
        index.register("Routine", "Morning routine", "Routine/morning_routine")

        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert "Routine|Routine/morning_routine|Morning routine" in result

    def test_linking_context_empty_index(self):
        import asyncio

        index = EntityIndex()
        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert result == ""


# ---------------------------------------------------------------------------
# Build-document integration tests
# ---------------------------------------------------------------------------


_SENTINEL_NOT_FOUND = object()  # distinct from None (None = "use default")


class _FakeBuildContext:
    """Minimal BuildContext double for testing build_documents."""

    def __init__(
        self,
        captured_iri: str = "InboxNote/test123",
        ensure_entity_returns: str | object | None = None,
    ):
        self.captured_iri = captured_iri
        self.tdb = None
        self.branch = "main"
        self._ensure_entity_returns = ensure_entity_returns
        self.ensure_entity_calls: list[tuple] = []

    def now(self) -> datetime:
        return datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)

    async def ensure_entity(self, type_name: str, name: str, factory):
        self.ensure_entity_calls.append((type_name, name, factory))
        if self._ensure_entity_returns is not None:
            if self._ensure_entity_returns is _SENTINEL_NOT_FOUND:
                return None  # simulate no match
            return self._ensure_entity_returns
        # Default: simulate existing entity found
        return f"{type_name}/{name.lower().replace(' ', '_')}"


class TestBuildDocuments:
    def setup_method(self):
        self.plugin = TriggeredRoutineExtractor()

    async def test_mixed_steps_spawn_tasks_and_activities(self):
        ctx = _FakeBuildContext()
        proposal = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[
                SpawnedStepSpec(
                    name="Warmup",
                    step_type="activity",
                    description="Light cardio",
                ),
                SpawnedStepSpec(
                    name="Review PRs",
                    step_type="task",
                    description="Check open PRs",
                ),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 2

        # First doc is an Activity
        act = docs[0]
        assert act["@type"] == "Activity"
        assert act["name"] == "Warmup"
        assert act["derived_from"] == ["InboxNote/test123"]
        assert act["provenance"] == {
            "@type": "Provenance",
            "agent": "ingestd",
            "at": "2026-07-07T12:00:00Z",
            "method": "llm_extraction",
        }

        # Second doc is a Task
        task = docs[1]
        assert task["@type"] == "Task"
        assert task["name"] == "Review PRs"
        assert task["status"] == "open"

    async def test_activity_step_links_to_routine(self):
        ctx = _FakeBuildContext()
        proposal = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[SpawnedStepSpec(name="Stretch", step_type="activity")],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["routine"] == "Routine/morning_routine"
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Routine"
        assert ctx.ensure_entity_calls[0][1] == "Morning routine"
        # Factory returns None → lookup-only, no auto-creation
        factory = ctx.ensure_entity_calls[0][2]
        assert factory() is None

    async def test_routine_not_found_still_spawns_without_link(self):
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = TriggeredRoutineProposal(
            routine_name="Bogus routine",
            steps=[
                SpawnedStepSpec(name="Stretch", step_type="activity"),
                SpawnedStepSpec(name="Review PRs", step_type="task"),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 2
        # Activity doc has NO "routine" key
        assert "routine" not in docs[0]
        # Task is still spawned
        assert docs[1]["@type"] == "Task"

    async def test_task_step_carries_due_date(self):
        ctx = _FakeBuildContext()
        proposal = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[
                SpawnedStepSpec(
                    name="Review PRs",
                    step_type="task",
                    due_date=datetime(2026, 7, 10, 17, 0, 0, tzinfo=UTC),
                ),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["due_date"] == "2026-07-10T17:00:00Z"

    async def test_empty_steps_returns_empty(self):
        ctx = _FakeBuildContext()
        proposal = TriggeredRoutineProposal(
            routine_name="Morning routine",
            steps=[],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []

    async def test_unknown_proposal_returns_empty(self):
        class FakeProposal(BaseModel):
            kind: str = "fake"

        ctx = _FakeBuildContext()
        docs = await self.plugin.build_documents(FakeProposal(), ctx)
        assert docs == []
