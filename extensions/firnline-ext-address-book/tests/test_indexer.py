"""Tests for the AddressBookIndexerPlugin."""

from __future__ import annotations

from firnline_core.plugins import IndexerPlugin, validate_plugin
from firnline_ext_address_book.indexer import AddressBookIndexerPlugin, plugin


class TestIndexerPluginMetadata:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_name(self):
        assert self.plugin.name == "address_book_indexer"

    def test_requires(self):
        reqs = {r.name: r.range for r in self.plugin.requires}
        assert reqs == {"address_book": ">=0.2.0 <0.3.0"}

    def test_indexed_classes(self):
        classes = self.plugin.indexed_classes()
        assert classes == ["Person", "Location", "Organization"]


class TestEntityTextPerson:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_person_name_only(self):
        doc = {"@type": "Person", "name": "Alice"}
        assert self.plugin.entity_text(doc) == "Alice"

    def test_person_with_phone(self):
        doc = {"@type": "Person", "name": "Bob", "contact": {"phone": "+123"}}
        assert self.plugin.entity_text(doc) == "Bob — +123"

    def test_person_with_email(self):
        doc = {"@type": "Person", "name": "Bob", "contact": {"email": "bob@example.com"}}
        assert self.plugin.entity_text(doc) == "Bob — bob@example.com"

    def test_person_with_phone_and_email(self):
        doc = {
            "@type": "Person",
            "name": "Bob",
            "contact": {"phone": "+123", "email": "bob@example.com"},
        }
        assert self.plugin.entity_text(doc) == "Bob — +123 — bob@example.com"


class TestEntityTextLocation:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_location_name_only(self):
        doc = {"@type": "Location", "name": "Office"}
        assert self.plugin.entity_text(doc) == "Office"

    def test_location_with_address(self):
        doc = {"@type": "Location", "name": "Office", "address": "123 Main St"}
        assert self.plugin.entity_text(doc) == "Office — 123 Main St"


class TestEntityTextOrganization:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_org_name_only(self):
        doc = {"@type": "Organization", "name": "Acme Corp"}
        assert self.plugin.entity_text(doc) == "Acme Corp"

    def test_org_with_location_name(self):
        doc = {
            "@type": "Organization",
            "name": "Acme Corp",
            "location": {"name": "HQ Building"},
        }
        assert self.plugin.entity_text(doc) == "Acme Corp — HQ Building"

    def test_org_with_location_no_name(self):
        doc = {
            "@type": "Organization",
            "name": "Acme Corp",
            "location": {"address": "456 St"},
        }
        assert self.plugin.entity_text(doc) == "Acme Corp"


class TestEntityName:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_name(self):
        assert self.plugin.entity_name({"name": "Alice"}) == "Alice"

    def test_missing_name(self):
        assert self.plugin.entity_name({}) == ""


class TestEntityAliases:
    def setup_method(self):
        self.plugin = AddressBookIndexerPlugin()

    def test_aliases_contains_name(self):
        assert self.plugin.entity_aliases({"name": "Alice"}) == ["Alice"]

    def test_aliases_empty_when_no_name_and_no_aliases(self):
        assert self.plugin.entity_aliases({}) == []

    def test_aliases_includes_aliases_list(self):
        aliases = self.plugin.entity_aliases({"name": "Alice", "aliases": ["Al", "Ally"]})
        assert aliases == ["Alice", "Al", "Ally"]

    def test_aliases_strips_empty(self):
        aliases = self.plugin.entity_aliases({"name": "Bob", "aliases": ["", " ", "Bobby"]})
        assert aliases == ["Bob", "Bobby"]


class TestProtocolConformance:
    def test_indexer_protocol_conformance(self):
        violations = validate_plugin(plugin, IndexerPlugin)
        assert violations == [], f"protocol violations: {violations}"


class TestModuleLevelPlugin:
    def test_plugin_is_AddressBookIndexerPlugin(self):
        assert isinstance(plugin, AddressBookIndexerPlugin)

    def test_plugin_name(self):
        assert plugin.name == "address_book_indexer"
