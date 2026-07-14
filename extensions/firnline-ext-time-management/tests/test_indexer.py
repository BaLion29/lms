"""Tests for the TimeManagementIndexerPlugin."""

from __future__ import annotations

from firnline_ext_time_management.indexer import TimeManagementIndexerPlugin, plugin


class TestIndexerPluginMetadata:
    def setup_method(self):
        self.plugin = TimeManagementIndexerPlugin()

    def test_name(self):
        assert self.plugin.name == "time_management_indexer"

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {"time_management": ">=0.1.0 <0.2.0"}

    def test_indexed_classes(self):
        classes = self.plugin.indexed_classes()
        assert classes == ["Task", "Event", "Routine", "Activity"]


class TestEntityText:
    def setup_method(self):
        self.plugin = TimeManagementIndexerPlugin()

    def test_task_with_description(self):
        doc = {"name": "Buy milk", "description": "Weekly shopping"}
        assert self.plugin.entity_text(doc) == "Buy milk — Weekly shopping"

    def test_task_without_description(self):
        doc = {"name": "Buy milk"}
        assert self.plugin.entity_text(doc) == "Buy milk"

    def test_event_with_description(self):
        doc = {"name": "Meeting", "description": "Team sync"}
        assert self.plugin.entity_text(doc) == "Meeting — Team sync"

    def test_routine_no_description_field(self):
        """Routine documents have no 'description' field — text is name only."""
        doc = {"name": "Morning routine"}
        assert self.plugin.entity_text(doc) == "Morning routine"

    def test_activity_with_description(self):
        doc = {"name": "Morning yoga", "description": "Did my usual practice"}
        assert self.plugin.entity_text(doc) == "Morning yoga — Did my usual practice"

    def test_activity_without_description(self):
        doc = {"name": "Morning yoga"}
        assert self.plugin.entity_text(doc) == "Morning yoga"

    def test_extra_fields_not_in_text(self):
        """Priority, estimated_duration, routine, status are NOT in entity_text."""
        doc = {
            "name": "Run",
            "description": "5k",
            "priority": 1,
            "estimated_duration": 30,
            "routine": "Routine/morning_routine",
            "status": "open",
        }
        assert self.plugin.entity_text(doc) == "Run — 5k"


class TestEntityName:
    def setup_method(self):
        self.plugin = TimeManagementIndexerPlugin()

    def test_task_name(self):
        assert self.plugin.entity_name({"name": "Buy milk"}) == "Buy milk"

    def test_missing_name(self):
        assert self.plugin.entity_name({}) == ""

    def test_routine_name(self):
        assert self.plugin.entity_name({"name": "Morning routine"}) == "Morning routine"


class TestEntityAliases:
    def setup_method(self):
        self.plugin = TimeManagementIndexerPlugin()

    def test_aliases_contains_name(self):
        assert self.plugin.entity_aliases({"name": "Meeting"}) == ["Meeting"]

    def test_aliases_empty_when_no_name(self):
        assert self.plugin.entity_aliases({}) == []

    def test_aliases_single_entry(self):
        """Aliases list contains exactly the name, one entry."""
        aliases = self.plugin.entity_aliases({"name": "Morning yoga"})
        assert len(aliases) == 1
        assert aliases[0] == "Morning yoga"


class TestModuleLevelPlugin:
    def test_plugin_is_TimeManagementIndexerPlugin(self):
        assert isinstance(plugin, TimeManagementIndexerPlugin)

    def test_plugin_name(self):
        assert plugin.name == "time_management_indexer"
