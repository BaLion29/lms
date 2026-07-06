"""Plugin-specific tests for firnline-ext-reminders — proposal parsing, prompt snippet, build_documents."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from firnline_core.plugins import BuildContext
from firnline_ext_reminders.extract import ReminderExtractPlugin, ReminderProposal

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Proposal model validation
# ---------------------------------------------------------------------------


class TestReminderProposal:
    def test_minimal_reminder(self):
        p = ReminderProposal(name="Call doctor")
        assert p.kind == "reminder"
        assert p.name == "Call doctor"
        assert p.description is None
        assert p.fire_at is None

    def test_reminder_with_description(self):
        p = ReminderProposal(name="Call doctor", description="Ask about results")
        assert p.description == "Ask about results"

    def test_reminder_with_fire_at(self):
        p = ReminderProposal(name="Call doctor", fire_at=datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC))
        assert p.fire_at == datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC)

    def test_fire_at_accepts_none_explicitly(self):
        p = ReminderProposal(name="Test", fire_at=None)
        assert p.fire_at is None

    def test_fire_at_field_has_description(self):
        field = ReminderProposal.model_fields["fire_at"]
        assert field.description is not None
        assert "fire" in field.description.lower()


# ---------------------------------------------------------------------------
# Prompt snippet
# ---------------------------------------------------------------------------


class TestPromptSnippet:
    def setup_method(self):
        self.plugin = ReminderExtractPlugin()

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
        assert ReminderExtractPlugin().name == "reminder_extract"

    def test_requires_includes_reminders_and_triggers(self):
        req_names = {r.name for r in ReminderExtractPlugin().requires}
        assert req_names == {"reminders", "triggers"}

    def test_triggers_requirement_range(self):
        trig_req = next(r for r in ReminderExtractPlugin().requires if r.name == "triggers")
        assert trig_req.range == ">=1.1.0 <2.0.0"

    def test_proposal_models_count(self):
        models = ReminderExtractPlugin().proposal_models()
        assert len(models) == 1
        assert models[0].__name__ == "ReminderProposal"

    async def test_linking_context_returns_empty(self):
        result = await ReminderExtractPlugin().linking_context(None, index=None, branch="")
        assert result == ""


# ---------------------------------------------------------------------------
# build_documents — integration-style tests using a mocked BuildContext
# ---------------------------------------------------------------------------


def _make_ctx(
    tdb_mock=None,
    inbox_iri="InboxNote/test1",
    *,
    now_dt=None,
    branch="main",
) -> BuildContext:
    tdb = tdb_mock or AsyncMock()
    dt = now_dt or datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
    return BuildContext(tdb=tdb, inbox_iri=inbox_iri, now=lambda: dt, branch=branch)


class TestBuildDocumentsNoFireAt:
    """Without fire_at: no trigger insert, trigger=None, behaviour unchanged."""

    async def test_no_trigger_inserted(self):
        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()
        proposal = ReminderProposal(name="Call doctor")
        docs = await plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        # trigger=None → excluded by to_tdb()'s exclude_none
        assert docs[0].get("trigger") is None
        assert docs[0]["derived_from"] == "InboxNote/test1"
        assert docs[0]["name"] == "Call doctor"
        ctx.tdb.insert_documents.assert_not_called()

    async def test_unknown_proposal_returns_empty(self):
        """Non-ReminderProposal yields empty list."""
        from pydantic import BaseModel

        class Unknown(BaseModel):
            kind: str = "unknown"

        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()
        docs = await plugin.build_documents(Unknown(), ctx)
        assert docs == []


class TestBuildDocumentsWithFireAt:
    """With fire_at set: insert OneShotTrigger, reference its IRI on the Reminder."""

    async def test_trigger_inserted_and_linked(self):
        tdb = AsyncMock()
        tdb.insert_documents.return_value = ["terminusdb:///data/OneShotTrigger/fire1"]
        ctx = _make_ctx(tdb)
        plugin = ReminderExtractPlugin()

        fire_dt = datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC)
        proposal = ReminderProposal(name="Call doctor", fire_at=fire_dt)
        docs = await plugin.build_documents(proposal, ctx)

        # tdb.insert_documents called exactly once
        tdb.insert_documents.assert_called_once()
        call_docs, call_kwargs = tdb.insert_documents.call_args

        # The inserted doc is a OneShotTrigger
        inserted = call_docs[0][0]
        assert inserted["@type"] == "OneShotTrigger"
        assert inserted["name"] == "Reminder: Call doctor"
        assert inserted["enabled"] is True
        # fire_at serialized as canonical UTC Z-suffix
        assert inserted["fire_at"] == "2026-07-07T09:00:00Z"

        # Uses the correct branch and a message
        assert call_kwargs["branch"] == "main"
        assert call_kwargs["message"].startswith("ingestd: ")
        assert "OneShotTrigger" in call_kwargs["message"]
        assert "Call doctor" in call_kwargs["message"]

        # Reminder references the trigger IRI
        assert len(docs) == 1
        assert docs[0]["trigger"] == "OneShotTrigger/fire1"
        assert docs[0]["derived_from"] == "InboxNote/test1"
        assert docs[0]["name"] == "Call doctor"

    async def test_fire_at_with_offset_converts_to_utc(self):
        """fire_at=2026-07-07T09:00:00+02:00 → serializes as 2026-07-07T07:00:00Z."""
        tdb = AsyncMock()
        tdb.insert_documents.return_value = ["terminusdb:///data/OneShotTrigger/off1"]
        ctx = _make_ctx(tdb)
        plugin = ReminderExtractPlugin()

        fire_dt = datetime(2026, 7, 7, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        proposal = ReminderProposal(name="Call dentist", fire_at=fire_dt)
        docs = await plugin.build_documents(proposal, ctx)

        inserted = tdb.insert_documents.call_args[0][0][0]
        # +02:00 → 07:00 UTC
        assert inserted["fire_at"] == "2026-07-07T07:00:00Z"
        assert docs[0]["trigger"] == "OneShotTrigger/off1"

    async def test_naive_fire_at_treated_as_utc(self):
        """Naive datetime is serialized as-is with Z suffix (treated as UTC)."""
        tdb = AsyncMock()
        tdb.insert_documents.return_value = ["terminusdb:///data/OneShotTrigger/naive1"]
        ctx = _make_ctx(tdb)
        plugin = ReminderExtractPlugin()

        naive_dt = datetime(2026, 7, 7, 9, 0, 0)  # no tzinfo
        proposal = ReminderProposal(name="Naive test", fire_at=naive_dt)
        await plugin.build_documents(proposal, ctx)

        inserted = tdb.insert_documents.call_args[0][0][0]
        assert inserted["fire_at"] == "2026-07-07T09:00:00Z"

    async def test_different_branch_passed_through(self):
        """ctx.branch is forwarded to the insert call."""
        tdb = AsyncMock()
        tdb.insert_documents.return_value = ["terminusdb:///data/OneShotTrigger/br1"]
        ctx = _make_ctx(tdb, branch="feature/test")
        plugin = ReminderExtractPlugin()

        proposal = ReminderProposal(name="Branch test", fire_at=datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC))
        await plugin.build_documents(proposal, ctx)

        assert tdb.insert_documents.call_args[1]["branch"] == "feature/test"
