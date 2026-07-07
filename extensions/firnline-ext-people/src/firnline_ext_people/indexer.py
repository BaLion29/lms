"""IndexerPlugin for Person documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class PeopleIndexerPlugin(IndexerPlugin):
    name: str = "people_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="people", range=">=0.1.0 <0.2.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Person"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        name = doc.get("name", "")
        contact = doc.get("contact")
        parts = [name]
        if isinstance(contact, dict):
            phone = contact.get("phone")
            email = contact.get("email")
            if phone:
                parts.append(phone)
            if email:
                parts.append(email)
        return " — ".join(parts)

    def entity_name(self, doc: dict[str, Any]) -> str:
        return str(doc.get("name", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        name = doc.get("name", "")
        if name:
            return [name]
        return []


plugin = PeopleIndexerPlugin()
