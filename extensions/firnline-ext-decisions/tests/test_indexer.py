"""Tests for the DecisionsIndexerPlugin."""

from __future__ import annotations

from firnline_ext_decisions.indexer import DecisionsIndexerPlugin, plugin


class TestIndexerPluginMetadata:
    def setup_method(self):
        self.plugin = DecisionsIndexerPlugin()

    def test_name(self):
        assert self.plugin.name == "decisions_indexer"

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {"decisions": ">=0.1.0 <0.2.0"}

    def test_indexed_classes(self):
        classes = self.plugin.indexed_classes()
        assert classes == ["Decision"]


class TestEntityText:
    def setup_method(self):
        self.plugin = DecisionsIndexerPlugin()

    def test_full_decision(self):
        doc = {
            "title": "Use PostgreSQL",
            "context": "We need a relational database",
            "decision": "We will use PostgreSQL 16",
            "consequences": "Team needs to learn PostgreSQL administration",
        }
        expected = (
            "Use PostgreSQL — We need a relational database — "
            "We will use PostgreSQL 16 — Team needs to learn PostgreSQL administration"
        )
        assert self.plugin.entity_text(doc) == expected

    def test_decision_minimal(self):
        doc = {"title": "Use PostgreSQL", "decision": "We will use PostgreSQL"}
        assert self.plugin.entity_text(doc) == "Use PostgreSQL — We will use PostgreSQL"

    def test_title_only(self):
        doc = {"title": "Use PostgreSQL"}
        assert self.plugin.entity_text(doc) == "Use PostgreSQL"

    def test_with_context_only(self):
        doc = {"title": "Use PostgreSQL", "context": "We need a database"}
        assert self.plugin.entity_text(doc) == "Use PostgreSQL — We need a database"

    def test_with_consequences_only(self):
        doc = {"title": "Use PostgreSQL", "consequences": "Higher ops cost"}
        assert self.plugin.entity_text(doc) == "Use PostgreSQL — Higher ops cost"

    def test_options_not_in_text(self):
        """Subdocument option names are NOT included in entity_text."""
        doc = {
            "title": "Use PostgreSQL",
            "decision": "PostgreSQL",
            "options": [
                {"name": "MySQL", "rejection_reason": "No JSONB"},
                {"name": "SQLite", "rejection_reason": "Not multi-user"},
            ],
        }
        assert self.plugin.entity_text(doc) == "Use PostgreSQL — PostgreSQL"

    def test_empty_fields_not_appended(self):
        doc = {
            "title": "Use PostgreSQL",
            "context": "",
            "decision": "PostgreSQL",
            "consequences": None,
        }
        assert self.plugin.entity_text(doc) == "Use PostgreSQL — PostgreSQL"


class TestEntityName:
    def setup_method(self):
        self.plugin = DecisionsIndexerPlugin()

    def test_decision_name(self):
        assert self.plugin.entity_name({"title": "Use PostgreSQL"}) == "Use PostgreSQL"

    def test_missing_title(self):
        assert self.plugin.entity_name({}) == ""


class TestEntityAliases:
    def setup_method(self):
        self.plugin = DecisionsIndexerPlugin()

    def test_aliases_contains_title(self):
        assert self.plugin.entity_aliases({"title": "Use PostgreSQL"}) == ["Use PostgreSQL"]

    def test_aliases_empty_when_no_title(self):
        assert self.plugin.entity_aliases({}) == []


class TestModuleLevelPlugin:
    def test_plugin_is_DecisionsIndexerPlugin(self):
        assert isinstance(plugin, DecisionsIndexerPlugin)

    def test_plugin_name(self):
        assert plugin.name == "decisions_indexer"
