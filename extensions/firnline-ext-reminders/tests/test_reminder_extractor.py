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

    def test_produces(self):
        assert ReminderExtractPlugin().produces == ["Reminder", "OneShotTrigger"]

    def test_requires_includes_reminders_and_triggers(self):
        req_names = {r.name for r in ReminderExtractPlugin().requires}
        assert req_names == {"reminders", "triggers"}

    def test_reminders_requirement_range(self):
        req = next(r for r in ReminderExtractPlugin().requires if r.name == "reminders")
        assert req.range == ">=0.1.0 <0.2.0"

    def test_triggers_requirement_range(self):
        req = next(r for r in ReminderExtractPlugin().requires if r.name == "triggers")
        assert req.range == ">=0.1.0 <0.2.0"

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
    captured_iri="InboxNote/test1",
    *,
    now_dt=None,
    branch="main",
) -> BuildContext:
    tdb = tdb_mock or AsyncMock()
    dt = now_dt or datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
    ensure_entity = AsyncMock()
    return BuildContext(
        tdb=tdb,
        captured_iri=captured_iri,
        now=lambda: dt,
        ensure_entity=ensure_entity,
        branch=branch,
    )


class TestBuildDocumentsNoFireAt:
    """Without fire_at: no trigger doc, trigger=None, provenance present."""

    async def test_no_trigger_doc_returned(self):
        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()
        proposal = ReminderProposal(name="Call doctor")
        docs = await plugin.build_documents(proposal, ctx)
        assert len(docs) == 1
        # trigger=None → excluded by to_tdb()'s exclude_none
        assert docs[0].get("trigger") is None
        assert docs[0]["@type"] == "Reminder"
        assert docs[0]["name"] == "Call doctor"
        # provenance instead of derived_from
        prov = docs[0]["provenance"]
        assert prov["agent"] == "ingestd"
        assert prov["method"] == "llm_extraction"
        assert prov["source"] == "InboxNote/test1"
        assert "at" in prov
        assert "derived_from" not in docs[0]
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
    """With fire_at set: OneShotTrigger returned in batch with client @id, referenced by Reminder."""

    async def test_trigger_in_batch_and_linked(self):
        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()

        fire_dt = datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC)
        proposal = ReminderProposal(name="Call doctor", fire_at=fire_dt)
        docs = await plugin.build_documents(proposal, ctx)

        # Two docs returned: [trigger_doc, reminder_doc] — no side-insert
        assert len(docs) == 2
        trigger_doc, reminder_doc = docs

        # trigger doc
        assert trigger_doc["@type"] == "OneShotTrigger"
        assert trigger_doc["name"] == "Reminder: Call doctor"
        assert trigger_doc["enabled"] is True
        # fire_at serialized as canonical UTC Z-suffix
        assert trigger_doc["fire_at"] == "2026-07-07T09:00:00Z"
        # trigger has a client-supplied @id
        assert trigger_doc["@id"].startswith("OneShotTrigger/")
        # trigger has provenance
        assert trigger_doc["provenance"]["agent"] == "ingestd"
        assert trigger_doc["provenance"]["method"] == "llm_extraction"

        # reminder doc references the trigger by its client @id
        assert reminder_doc["@type"] == "Reminder"
        assert reminder_doc["trigger"] == trigger_doc["@id"]
        assert reminder_doc["name"] == "Call doctor"
        # provenance instead of derived_from
        assert reminder_doc["provenance"]["agent"] == "ingestd"
        assert reminder_doc["provenance"]["source"] == "InboxNote/test1"
        assert "derived_from" not in reminder_doc

        # No side-insert at all
        ctx.tdb.insert_documents.assert_not_called()

    async def test_fire_at_with_offset_converts_to_utc(self):
        """fire_at=2026-07-07T09:00:00+02:00 → serializes as 2026-07-07T07:00:00Z."""
        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()

        fire_dt = datetime(2026, 7, 7, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        proposal = ReminderProposal(name="Call dentist", fire_at=fire_dt)
        docs = await plugin.build_documents(proposal, ctx)

        trigger_doc = docs[0]
        # +02:00 → 07:00 UTC
        assert trigger_doc["fire_at"] == "2026-07-07T07:00:00Z"

    async def test_naive_fire_at_treated_as_utc(self):
        """Naive datetime is serialized as-is with Z suffix (treated as UTC)."""
        ctx = _make_ctx()
        plugin = ReminderExtractPlugin()

        naive_dt = datetime(2026, 7, 7, 9, 0, 0)  # no tzinfo
        proposal = ReminderProposal(name="Naive test", fire_at=naive_dt)
        docs = await plugin.build_documents(proposal, ctx)

        trigger_doc = docs[0]
        assert trigger_doc["fire_at"] == "2026-07-07T09:00:00Z"

    async def test_branch_not_used_for_side_insert(self):
        """No side-insert happens; branch is irrelevant now."""
        ctx = _make_ctx(branch="feature/test")
        plugin = ReminderExtractPlugin()

        proposal = ReminderProposal(name="Branch test", fire_at=datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC))
        docs = await plugin.build_documents(proposal, ctx)

        assert len(docs) == 2
        ctx.tdb.insert_documents.assert_not_called()
