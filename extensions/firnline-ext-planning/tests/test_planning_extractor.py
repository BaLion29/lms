"""Plugin-specific tests for firnline-ext-planning — proposal parsing per kind, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timezone

from firnline_core.plugins import EntityIndex
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

    def test_produces(self):
        assert PlanningPlugin().produces == ["Task", "Event", "Person", "Location"]

    def test_requires_has_planning_people_places(self):
        reqs = {r.name: r.range for r in PlanningPlugin().requires}
        assert reqs == {
            "planning": ">=0.1.0 <0.2.0",
            "people": ">=0.1.0 <0.2.0",
            "places": ">=0.1.0 <0.2.0",
        }

    def test_proposal_models_count(self):
        models = PlanningPlugin().proposal_models()
        assert len(models) == 3
        names = {m.__name__ for m in models}
        assert names == {"TaskProposal", "EventProposal", "PersonProposal"}

    def test_linking_context_returns_names(self):
        import asyncio

        index = EntityIndex()
        index.register("Person", "Alice", "Person/alice")
        index.register("Location", "Office", "Location/office")

        result = asyncio.run(PlanningPlugin().linking_context(None, index=index, branch=""))
        assert "Person|Person/alice|Alice" in result
        assert "Location|Location/office|Office" in result

    def test_linking_context_empty_index(self):
        import asyncio

        index = EntityIndex()
        result = asyncio.run(PlanningPlugin().linking_context(None, index=index, branch=""))
        assert result == ""


# ---------------------------------------------------------------------------
# Build-document integration tests
# ---------------------------------------------------------------------------


class _FakeBuildContext:
    """Minimal BuildContext double for testing build_documents."""

    def __init__(self, captured_iri: str = "InboxNote/test123", ensure_entity_returns: str | None = None):
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
            return self._ensure_entity_returns
        # Default: simulate existing entity found
        return f"{type_name}/{name.lower().replace(' ', '_')}"


class TestBuildDocuments:
    def setup_method(self):
        self.plugin = PlanningPlugin()

    async def test_task_proposal_builds_with_provenance_and_anchor(self):
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
        assert doc["created_at"] == "2026-07-07T12:00:00Z"
        assert doc["updated_at"] == "2026-07-07T12:00:00Z"
        assert doc["anchor_at"] == "2026-07-10T17:00:00Z"
        assert "derived_from" not in doc
        assert doc["provenance"] == {
            "@type": "Provenance",
            "source": "InboxNote/test123",
            "agent": "ingestd",
            "at": "2026-07-07T12:00:00Z",
            "method": "llm_extraction",
        }

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
        assert doc["anchor_at"] == "2026-07-08T09:00:00Z"
        assert "location" not in doc  # exclude_none
        assert "derived_from" not in doc
        assert doc["provenance"]["agent"] == "ingestd"
        assert doc["provenance"]["method"] == "llm_extraction"

    async def test_event_proposal_with_location_ensure_entity(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Location/office_room")
        proposal = EventProposal(
            name="Meeting",
            location_name="Office Room",
        )
        docs = await self.plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["location"] == "Location/office_room"

        assert len(ctx.ensure_entity_calls) == 1
        type_name, name, factory = ctx.ensure_entity_calls[0]
        assert type_name == "Location"
        assert name == "Office Room"
        # factory should return a full Location dict
        loc_doc = factory()
        assert loc_doc["@type"] == "Location"
        assert loc_doc["name"] == "Office Room"
        assert "created_at" in loc_doc
        assert "provenance" in loc_doc

    async def test_person_proposal_existing_person(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Person/alice")
        proposal = PersonProposal(name="Alice", email="alice@example.com")
        docs = await self.plugin.build_documents(proposal, ctx)
        # Existing person linked — no new doc returned
        assert docs == []
        assert ctx.ensure_entity_calls[0][0] == "Person"
        assert ctx.ensure_entity_calls[0][1] == "Alice"

    async def test_person_proposal_new_person(self):
        # Simulate ensure_entity creating the entity and returning an IRI.
        ctx = _FakeBuildContext(ensure_entity_returns="Person/bob")
        proposal = PersonProposal(name="Bob", email="bob@example.com", phone="+123")
        docs = await self.plugin.build_documents(proposal, ctx)
        # ensure_entity handles creation; no separate docs to return
        assert docs == []
        assert ctx.ensure_entity_calls[0][0] == "Person"
        assert ctx.ensure_entity_calls[0][1] == "Bob"

    async def test_person_proposal_ensure_entity_factory_creates_full_doc(self):
        ctx = _FakeBuildContext(ensure_entity_returns="Person/bob")
        proposal = PersonProposal(name="Bob", email="bob@example.com", phone="+123")
        await self.plugin.build_documents(proposal, ctx)
        _type_name, _name, factory = ctx.ensure_entity_calls[0]
        doc = factory()
        assert doc["@type"] == "Person"
        assert doc["name"] == "Bob"
        assert doc["contact"] == {
            "@type": "Contact",
            "email": "bob@example.com",
            "phone": "+123",
        }
        assert doc["provenance"]["agent"] == "ingestd"
        assert doc["provenance"]["method"] == "llm_extraction"
        assert "created_at" in doc
        assert "updated_at" in doc

    async def test_event_anchor_at_none_when_no_start(self):
        ctx = _FakeBuildContext()
        proposal = EventProposal(name="Undated Event")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "anchor_at" not in doc  # exclude_none when None

    async def test_task_anchor_at_none_when_no_due_date(self):
        ctx = _FakeBuildContext()
        proposal = TaskProposal(name="No due date")
        docs = await self.plugin.build_documents(proposal, ctx)
        doc = docs[0]
        assert "anchor_at" not in doc  # exclude_none when None
