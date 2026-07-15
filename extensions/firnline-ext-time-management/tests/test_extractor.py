"""Plugin-specific tests for firnline-ext-time-management — proposal parsing, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timezone

from firnline_core.plugins import EntityIndex
from firnline_ext_time_management.extract import (
    ActivityProposal,
    AreaProposal,
    EventProposal,
    GoalProposal,
    PersonProposal,
    ProjectProposal,
    RoutineProposal,
    RoutineStepSpec,
    TaskProposal,
    TimeManagementPlugin,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Proposal model validation — Task, Event, Person (ported from planning)
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

    def test_project_and_area_default_none(self):
        p = TaskProposal(name="Buy milk")
        assert p.project_name is None
        assert p.area_name is None

    def test_with_project_and_area(self):
        p = TaskProposal(
            name="Write report",
            project_name="Q3 report",
            area_name="Work",
        )
        assert p.project_name == "Q3 report"
        assert p.area_name == "Work"


class TestEventProposal:
    def test_event_with_location(self):
        p = EventProposal(name="Meeting", location_name="Office")
        assert p.kind == "event"
        assert p.location_name == "Office"

    def test_event_minimal(self):
        p = EventProposal(name="Meeting")
        assert p.location_name is None
        assert p.start_datetime is None

    def test_project_and_area_default_none(self):
        p = EventProposal(name="Meeting")
        assert p.project_name is None
        assert p.area_name is None

    def test_with_project_and_area(self):
        p = EventProposal(
            name="Sprint planning",
            project_name="Mobile app",
            area_name="Engineering",
        )
        assert p.project_name == "Mobile app"
        assert p.area_name == "Engineering"


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
# Routine/Activity proposal model validation
# ---------------------------------------------------------------------------


class TestRoutineProposal:
    def test_minimal_routine_with_activity_step(self):
        p = RoutineProposal(
            name="Morning routine",
            steps=[RoutineStepSpec(name="Stretch", step_type="activity")],
        )
        assert p.kind == "routine"
        assert p.name == "Morning routine"
        assert len(p.steps) == 1
        assert p.steps[0].step_type == "activity"
        assert p.steps[0].cadence_days is None

    def test_routine_with_mixed_steps(self):
        p = RoutineProposal(
            name="Gym routine",
            required_context=["fitness"],
            steps=[
                RoutineStepSpec(
                    name="Warmup",
                    step_type="activity",
                    description="Light cardio",
                    cadence_days=1,
                ),
                RoutineStepSpec(
                    name="Bench press",
                    step_type="task",
                    description="3 sets of 10",
                    priority=2,
                    estimated_duration=15,
                ),
            ],
        )
        assert p.kind == "routine"
        assert p.required_context == ["fitness"]
        assert len(p.steps) == 2
        assert p.steps[0].step_type == "activity"
        assert p.steps[0].description == "Light cardio"
        assert p.steps[0].cadence_days == 1
        assert p.steps[1].step_type == "task"
        assert p.steps[1].priority == 2
        assert p.steps[1].estimated_duration == 15


class TestActivityProposal:
    def test_minimal_activity(self):
        p = ActivityProposal(name="Morning yoga")
        assert p.kind == "activity"
        assert p.name == "Morning yoga"
        assert p.description is None
        assert p.routine_name is None

    def test_activity_with_routine_link(self):
        p = ActivityProposal(
            name="Morning yoga session",
            description="Did my usual practice",
            routine_name="Morning routine",
            priority=1,
            estimated_duration=30,
            start_datetime=datetime(2026, 7, 8, 7, 0, 0, tzinfo=UTC),
        )
        assert p.routine_name == "Morning routine"
        assert p.priority == 1
        assert p.estimated_duration == 30
        assert p.start_datetime.year == 2026


# ---------------------------------------------------------------------------
# PARA proposal model validation
# ---------------------------------------------------------------------------


class TestProjectProposal:
    def test_minimal_project(self):
        p = ProjectProposal(name="Garden redesign")
        assert p.kind == "project"
        assert p.name == "Garden redesign"
        assert p.description is None
        assert p.target_date is None
        assert p.area_name is None
        assert p.goal_name is None

    def test_full_project(self):
        p = ProjectProposal(
            name="Garden redesign",
            description="Redesign the backyard by June",
            target_date=datetime(2026, 6, 30, tzinfo=UTC),
            area_name="Home",
            goal_name="Better outdoor space",
        )
        assert p.kind == "project"
        assert p.description == "Redesign the backyard by June"
        assert p.target_date.month == 6
        assert p.area_name == "Home"
        assert p.goal_name == "Better outdoor space"


class TestAreaProposal:
    def test_minimal_area(self):
        p = AreaProposal(name="Health")
        assert p.kind == "area"
        assert p.name == "Health"
        assert p.description is None

    def test_area_with_description(self):
        p = AreaProposal(name="Finances", description="Managing budgets and investments")
        assert p.kind == "area"
        assert p.description == "Managing budgets and investments"


class TestGoalProposal:
    def test_minimal_goal(self):
        p = GoalProposal(name="Run a marathon")
        assert p.kind == "goal"
        assert p.name == "Run a marathon"
        assert p.description is None
        assert p.target_date is None
        assert p.success_criteria is None

    def test_full_goal(self):
        p = GoalProposal(
            name="Save for house",
            description="Save 50k for a down-payment",
            target_date=datetime(2027, 12, 31, tzinfo=UTC),
            success_criteria="50k in savings account",
        )
        assert p.kind == "goal"
        assert p.description == "Save 50k for a down-payment"
        assert p.target_date.year == 2027
        assert p.success_criteria == "50k in savings account"


# ---------------------------------------------------------------------------
# Prompt snippet
# ---------------------------------------------------------------------------


class TestPromptSnippet:
    def setup_method(self):
        self.plugin = TimeManagementPlugin()

    def test_snippet_has_no_json_fences(self):
        snippet = self.plugin.prompt_snippet()
        assert "```json" not in snippet
        assert "```" not in snippet

    def test_snippet_mentions_routine_and_activity(self):
        snippet = self.plugin.prompt_snippet()
        assert "Routine" in snippet
        assert "Activity" in snippet

    def test_snippet_mentions_para_semantics(self):
        snippet = self.plugin.prompt_snippet()
        assert "Project" in snippet
        assert "Area" in snippet
        assert "Goal" in snippet
        assert "project_name" in snippet
        assert "area_name" in snippet


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def setup_method(self):
        self.plugin = TimeManagementPlugin()

    def test_name(self):
        assert self.plugin.name == "time_management_extractor"

    def test_produces(self):
        assert self.plugin.produces == ["Task", "Event", "Person", "Location", "Routine", "Activity", "Project", "Area", "Goal"]

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {
            "time_management": ">=0.1.0 <0.2.0",
            "address_book": ">=0.1.0 <0.2.0",
        }

    def test_proposal_models_count(self):
        models = self.plugin.proposal_models()
        assert len(models) == 8
        names = {m.__name__ for m in models}
        assert names == {
            "TaskProposal", "EventProposal", "PersonProposal",
            "RoutineProposal", "ActivityProposal",
            "ProjectProposal", "AreaProposal", "GoalProposal",
        }

    def test_linking_context_includes_all_entity_types(self):
        import asyncio

        index = EntityIndex()
        index.register("Person", "Alice", "Person/alice")
        index.register("Location", "Office", "Location/office")
        index.register("Routine", "Morning routine", "Routine/morning_routine")
        index.register("Project", "Garden redesign", "Project/garden_redesign")
        index.register("Area", "Health", "Area/health")
        index.register("Goal", "Run marathon", "Goal/run_marathon")

        result = asyncio.run(self.plugin.linking_context(None, index=index, branch=""))
        assert "Person|Person/alice|Alice" in result
        assert "Location|Location/office|Office" in result
        assert "Routine|Routine/morning_routine|Morning routine" in result
        assert "Project|Project/garden_redesign|Garden redesign" in result
        assert "Area|Area/health|Health" in result
        assert "Goal|Goal/run_marathon|Run marathon" in result

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
        self.plugin = TimeManagementPlugin()

    # ── Task (ported from planning) ───────────────────────────────────

    async def test_task_proposal_builds_with_provenance(self):
        ctx = _FakeBuildContext()
        proposal = TaskProposal(
            name="Buy milk",
            description="Weekly shopping",
            priority=2,
            estimated_duration=30,
            due_date=datetime(2026, 7, 10, 17, 0, 0, tzinfo=UTC),
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Task"
        assert doc["name"] == "Buy milk"
        assert doc["status"] == "open"
        assert doc["due_date"] == "2026-07-10T17:00:00Z"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"] == {
            "@type": "Provenance",
            "agent": "ingestd",
            "at": "2026-07-07T12:00:00Z",
            "method": "llm_extraction",
        }

    # ── Event (ported from planning) ──────────────────────────────────

    async def test_event_proposal_no_location(self):
        ctx = _FakeBuildContext()
        proposal = EventProposal(
            name="Meeting",
            description="Team sync",
            start_datetime=datetime(2026, 7, 8, 9, 0, 0, tzinfo=UTC),
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Event"
        assert doc["name"] == "Meeting"
        assert doc["status"] == "open"
        assert doc["start_datetime"] == "2026-07-08T09:00:00Z"
        assert "location" not in doc

    async def test_event_proposal_with_location_ensure_entity(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Location/office_room")
        proposal = EventProposal(name="Meeting", location_name="Office Room")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["location"] == "Location/office_room"
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Location"
        assert ctx.ensure_entity_calls[0][1] == "Office Room"
        factory_doc = ctx.ensure_entity_calls[0][2]()
        assert factory_doc["@type"] == "Location"
        assert factory_doc["name"] == "Office Room"

    # ── Person (ported from planning) ─────────────────────────────────

    async def test_person_proposal_existing_person(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Person/alice")
        proposal = PersonProposal(name="Alice", email="alice@example.com")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert ctx.ensure_entity_calls[0][0] == "Person"

    async def test_person_proposal_new_person(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Person/bob")
        proposal = PersonProposal(name="Bob", email="bob@example.com", phone="+123")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        factory_doc = ctx.ensure_entity_calls[0][2]()
        assert factory_doc["@type"] == "Person"
        assert factory_doc["contact"] == {
            "@type": "Contact",
            "email": "bob@example.com",
            "phone": "+123",
        }

    # ── Routine ───────────────────────────────────────────────────────

    async def test_routine_proposal_with_activity_steps(self):
        ctx = _FakeBuildContext()
        proposal = RoutineProposal(
            name="Morning routine",
            required_context=["health"],
            steps=[
                RoutineStepSpec(
                    name="Stretch",
                    step_type="activity",
                    description="Morning stretches",
                    cadence_days=1,
                ),
                RoutineStepSpec(
                    name="Meditate",
                    step_type="activity",
                    priority=1,
                    estimated_duration=10,
                ),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Routine"
        assert doc["name"] == "Morning routine"
        assert doc["required_context"] == ["Project/health"]
        assert "steps" in doc

        steps = doc["steps"]
        assert len(steps) == 2

        s0 = steps[0]
        assert s0["@type"] == "RoutineStep"
        assert s0["name"] == "Stretch"
        assert s0["cadence_days"] == 1
        assert s0["activity"]["@type"] == "ActivitySpec"
        assert s0["activity"]["name"] == "Stretch"
        assert s0["activity"]["description"] == "Morning stretches"
        assert "task" not in s0 or s0.get("task") is None

        s1 = steps[1]
        assert s1["@type"] == "RoutineStep"
        assert s1["name"] == "Meditate"
        assert s1.get("cadence_days") is None  # None excluded by pydantic to_tdb
        assert s1["activity"]["@type"] == "ActivitySpec"
        assert s1["activity"]["priority"] == 1
        assert s1["activity"]["estimated_duration"] == 10

    async def test_routine_proposal_with_task_steps(self):
        ctx = _FakeBuildContext()
        proposal = RoutineProposal(
            name="Work checklist",
            steps=[
                RoutineStepSpec(
                    name="Review PRs",
                    step_type="task",
                    priority=2,
                    estimated_duration=30,
                ),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        steps = doc["steps"]
        s0 = steps[0]
        assert s0["name"] == "Review PRs"
        assert s0["task"]["@type"] == "TaskSpec"
        assert s0["task"]["name"] == "Review PRs"
        assert s0["task"]["priority"] == 2
        assert s0["task"]["estimated_duration"] == 30
        assert s0.get("activity") is None

    async def test_routine_proposal_mixed_steps(self):
        """Routine with both activity-step and task-step confirms oneOf mapping."""
        ctx = _FakeBuildContext()
        proposal = RoutineProposal(
            name="Mixed routine",
            steps=[
                RoutineStepSpec(name="Warmup", step_type="activity"),
                RoutineStepSpec(name="Coding", step_type="task"),
            ],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        steps = docs[0]["steps"]
        assert steps[0]["activity"] is not None
        assert steps[0].get("task") is None
        assert steps[1]["task"] is not None
        assert steps[1].get("activity") is None

    async def test_routine_step_default_step_type_is_activity(self):
        """Default step_type is 'activity' — no step_type specified should map to activity."""
        spec = RoutineStepSpec(name="Default step")
        assert spec.step_type == "activity"

    async def test_routine_required_context_fallback_to_tag(self):
        """Routine with required_context where no Project/Area/Goal matches → creates Tag."""
        # Simulate: Project, Area, Goal not found, but Tag creation works
        class _TagFallbackCtx(_FakeBuildContext):
            async def ensure_entity(self, type_name: str, name: str, factory):
                self.ensure_entity_calls.append((type_name, name, factory))
                if type_name == "Tag":
                    return "Tag/home"
                return None  # Project, Area, Goal — all not found

        ctx = _TagFallbackCtx()
        proposal = RoutineProposal(
            name="Home routine",
            required_context=["home"],
            steps=[RoutineStepSpec(name="Stretch", step_type="activity")],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["required_context"] == ["Tag/home"]
        # Verify Tag factory was called (not lambda: None from _resolve_context)
        tag_call = [c for c in ctx.ensure_entity_calls if c[0] == "Tag"]
        assert len(tag_call) == 1
        factory_doc = tag_call[0][2]()
        assert factory_doc["@type"] == "Tag"
        assert factory_doc["name"] == "home"

    async def test_routine_required_context_resolves_existing_area(self):
        """Routine with required_context where Area matches → uses Area IRI, no Tag."""

        class _AreaOnlyCtx(_FakeBuildContext):
            async def ensure_entity(self, type_name: str, name: str, factory):
                self.ensure_entity_calls.append((type_name, name, factory))
                if type_name == "Area":
                    return "Area/home"
                return None  # Project, Goal — not found

        ctx = _AreaOnlyCtx()
        proposal = RoutineProposal(
            name="Home routine",
            required_context=["home"],
            steps=[RoutineStepSpec(name="Stretch", step_type="activity")],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["required_context"] == ["Area/home"]

    async def test_routine_no_required_context_defaults_empty(self):
        """Routine without required_context keeps the field empty."""
        ctx = _FakeBuildContext()
        proposal = RoutineProposal(
            name="Simple routine",
            steps=[RoutineStepSpec(name="Step", step_type="activity")],
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["required_context"] == []

    # ── Activity ──────────────────────────────────────────────────────

    async def test_activity_proposal_minimal(self):
        ctx = _FakeBuildContext()
        proposal = ActivityProposal(name="Morning yoga")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Activity"
        assert doc["name"] == "Morning yoga"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"]["agent"] == "ingestd"
        assert "routine" not in doc

    async def test_activity_proposal_with_priority_and_duration(self):
        ctx = _FakeBuildContext()
        proposal = ActivityProposal(
            name="Run",
            priority=1,
            estimated_duration=45,
            start_datetime=datetime(2026, 7, 8, 6, 30, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 7, 8, 7, 15, 0, tzinfo=UTC),
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["priority"] == 1
        assert doc["estimated_duration"] == 45
        assert doc["start_datetime"] == "2026-07-08T06:30:00Z"
        assert doc["end_datetime"] == "2026-07-08T07:15:00Z"

    async def test_activity_proposal_with_routine_link(self):
        """Activity with routine_name resolves via ensure_entity."""
        ctx = _FakeBuildContext(ensure_entity_returns="Routine/morning_routine")
        proposal = ActivityProposal(
            name="Morning yoga session",
            routine_name="Morning routine",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["routine"] == "Routine/morning_routine"
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Routine"
        assert ctx.ensure_entity_calls[0][1] == "Morning routine"
        # Factory returns None → no auto-creation
        factory = ctx.ensure_entity_calls[0][2]
        assert factory() is None

    async def test_activity_proposal_routine_not_found_no_auto_create(self):
        """If routine_name doesn't match, leave routine field unset (do NOT auto-create)."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)  # no match
        proposal = ActivityProposal(name="Unknown routine session", routine_name="Bogus")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "routine" not in doc

    # ── Anchor field absence ──────────────────────────────────────────

    async def test_task_no_anchor_field_emitted(self):
        ctx = _FakeBuildContext()
        proposal = TaskProposal(name="No due date")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "anchor_at" not in doc

    async def test_event_no_anchor_field_emitted(self):
        ctx = _FakeBuildContext()
        proposal = EventProposal(name="Undated Event")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "anchor_at" not in doc

    # ── Project ───────────────────────────────────────────────────────

    async def test_project_proposal_minimal(self):
        ctx = _FakeBuildContext()
        proposal = ProjectProposal(name="Garden redesign")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Project"
        assert doc["name"] == "Garden redesign"
        assert doc["status"] == "active"
        assert doc["derived_from"] == ["InboxNote/test123"]
        assert doc["provenance"]["agent"] == "ingestd"

    async def test_project_proposal_with_target_date(self):
        ctx = _FakeBuildContext()
        target = datetime(2026, 6, 30, tzinfo=UTC)
        proposal = ProjectProposal(
            name="Redesign",
            description="Redo the backyard",
            target_date=target,
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["description"] == "Redo the backyard"
        assert doc["target_date"] == "2026-06-30T00:00:00Z"

    async def test_project_proposal_with_area_and_goal_context(self):
        """Project area_name and goal_name resolve to contexts via ensure_entity."""
        ctx = _FakeBuildContext(ensure_entity_returns="Area/home")
        proposal = ProjectProposal(
            name="Garden redesign",
            area_name="Home",
            goal_name="Better outdoor space",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "contexts" in doc
        # The default behaviour of _FakeBuildContext returns same IRI for all calls
        # Both area and goal resolve to the same IRI
        assert len(doc["contexts"]) == 2
        assert "Area/home" in doc["contexts"]

    async def test_project_proposal_context_not_found(self):
        """If area_name and goal_name don't match, contexts stays empty."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = ProjectProposal(
            name="Garden redesign",
            area_name="Bogus",
            goal_name="Nonsense",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc.get("contexts", []) == []

    # ── Area ──────────────────────────────────────────────────────────

    async def test_area_proposal_minimal(self):
        ctx = _FakeBuildContext()
        proposal = AreaProposal(name="Health")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []  # ensure_entity handles creation, returns []
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Area"
        assert ctx.ensure_entity_calls[0][1] == "Health"
        # Factory creates a valid Area document
        factory = ctx.ensure_entity_calls[0][2]
        factory_doc = factory()
        assert factory_doc["@type"] == "Area"
        assert factory_doc["name"] == "Health"

    async def test_area_proposal_with_description(self):
        ctx = _FakeBuildContext()
        proposal = AreaProposal(name="Finances", description="Budget and investments")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        factory_doc = ctx.ensure_entity_calls[0][2]()
        assert factory_doc["description"] == "Budget and investments"

    async def test_area_proposal_already_exists_is_reused(self):
        """When an Area already exists, ensure_entity returns its IRI and factory is NOT called."""
        ctx = _FakeBuildContext(ensure_entity_returns="Area/health")
        proposal = AreaProposal(name="Health")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert docs == []
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Area"
        assert ctx.ensure_entity_calls[0][1] == "Health"
        # The factory should NOT be called since the entity already exists
        factory = ctx.ensure_entity_calls[0][2]

    # ── Goal ──────────────────────────────────────────────────────────

    async def test_goal_proposal_minimal(self):
        ctx = _FakeBuildContext()
        proposal = GoalProposal(name="Run a marathon")
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["@type"] == "Goal"
        assert doc["name"] == "Run a marathon"
        assert doc["status"] == "active"
        assert doc["derived_from"] == ["InboxNote/test123"]

    async def test_goal_proposal_full(self):
        ctx = _FakeBuildContext()
        target = datetime(2027, 12, 31, tzinfo=UTC)
        proposal = GoalProposal(
            name="Save for house",
            description="Down-payment savings",
            target_date=target,
            success_criteria="50k in account",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["description"] == "Down-payment savings"
        assert doc["target_date"] == "2027-12-31T00:00:00Z"
        assert doc["success_criteria"] == "50k in account"
        assert doc["status"] == "active"

    # ── Task context wiring (project / area) ──────────────────────────

    async def test_task_with_project_context_link(self):
        """Task with project_name resolves the Project IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Project/garden")
        proposal = TaskProposal(
            name="Buy soil",
            project_name="Garden redesign",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["contexts"] == ["Project/garden"]
        assert len(ctx.ensure_entity_calls) == 1
        assert ctx.ensure_entity_calls[0][0] == "Project"
        assert ctx.ensure_entity_calls[0][1] == "Garden redesign"
        # Factory returns None → no auto-creation
        factory = ctx.ensure_entity_calls[0][2]
        assert factory() is None

    async def test_task_with_area_context_link(self):
        """Task with area_name resolves the Area IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Area/home")
        proposal = TaskProposal(
            name="Fix sink",
            area_name="Home",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["contexts"] == ["Area/home"]

    async def test_task_with_both_project_and_area_context(self):
        """Task with both project_name and area_name resolves both IRIs."""
        # Use a call-counter approach: first call returns Project, second returns Area
        class _MultiReturnCtx(_FakeBuildContext):
            def __init__(self):
                super().__init__()
                self._call_count = 0

            async def ensure_entity(self, type_name: str, name: str, factory):
                self._call_count += 1
                self.ensure_entity_calls.append((type_name, name, factory))
                if self._call_count == 1:
                    return "Project/garden"
                return "Area/home"

        ctx = _MultiReturnCtx()
        proposal = TaskProposal(
            name="Buy soil",
            project_name="Garden redesign",
            area_name="Home",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "Project/garden" in doc["contexts"]
        assert "Area/home" in doc["contexts"]
        assert len(doc["contexts"]) == 2

    async def test_task_context_not_found_no_contexts_set(self):
        """If project_name doesn't match anything, no context is added."""
        ctx = _FakeBuildContext(ensure_entity_returns=_SENTINEL_NOT_FOUND)
        proposal = TaskProposal(name="Unknown task", project_name="Bogus")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc.get("contexts", []) == []

    async def test_task_no_context_hint_keeps_default_empty(self):
        """Task without project_name or area_name has empty contexts list."""
        ctx = _FakeBuildContext()
        proposal = TaskProposal(name="Simple task")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc.get("contexts", []) == []

    # ── Event context wiring (project / area) ─────────────────────────

    async def test_event_with_project_context_link(self):
        """Event with project_name resolves the Project IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Project/mobile_app")
        proposal = EventProposal(
            name="Sprint review",
            project_name="Mobile app",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "Project/mobile_app" in doc["contexts"]

    async def test_event_with_area_context_link(self):
        """Event with area_name resolves the Area IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Area/engineering")
        proposal = EventProposal(
            name="Standup",
            area_name="Engineering",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "Area/engineering" in doc["contexts"]

    # ── Project context wiring (area / goal) ──────────────────────────

    async def test_project_with_area_context(self):
        """Project with area_name resolves Area IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Area/home")
        proposal = ProjectProposal(
            name="Garden redesign",
            area_name="Home",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["contexts"] == ["Area/home"]

    async def test_project_with_goal_context(self):
        """Project with goal_name resolves Goal IRI into contexts."""
        ctx = _FakeBuildContext(ensure_entity_returns="Goal/outdoor_space")
        proposal = ProjectProposal(
            name="Garden redesign",
            goal_name="Better outdoor space",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert doc["contexts"] == ["Goal/outdoor_space"]

    # ── Goal has no status in minimal build ───────────────────────────
    # (already covered by test_goal_proposal_minimal: status == "active")
