"""Plugin-specific tests for firnline-ext-reminders — proposal parsing, prompt snippet."""

from __future__ import annotations

import asyncio

from firnline_ext_reminders.extract import ReminderExtractPlugin, ReminderProposal


# ---------------------------------------------------------------------------
# Proposal model validation
# ---------------------------------------------------------------------------


class TestReminderProposal:
    def test_minimal_reminder(self):
        p = ReminderProposal(name="Call doctor")
        assert p.kind == "reminder"
        assert p.name == "Call doctor"
        assert p.description is None

    def test_reminder_with_description(self):
        p = ReminderProposal(name="Call doctor", description="Ask about results")
        assert p.description == "Ask about results"


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

    def test_requires_has_reminders(self):
        req_names = {r.name for r in ReminderExtractPlugin().requires}
        assert req_names == {"reminders"}

    def test_proposal_models_count(self):
        models = ReminderExtractPlugin().proposal_models()
        assert len(models) == 1
        assert models[0].__name__ == "ReminderProposal"

    def test_linking_context_returns_empty(self):
        result = asyncio.run(
            ReminderExtractPlugin().linking_context(None, index=None, branch="")
        )
        assert result == ""
