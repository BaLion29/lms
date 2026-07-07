"""IndexerPlugin for Location documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class PlacesIndexerPlugin(IndexerPlugin):
    name: str = "places_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="places", range=">=0.1.0 <0.2.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Location"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        name = doc.get("name", "")
        address = doc.get("address")
        parts = [name]
        if address:
            parts.append(address)
        return " — ".join(parts)

    def entity_name(self, doc: dict[str, Any]) -> str:
        return str(doc.get("name", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        aliases: list[str] = []
        name = doc.get("name", "")
        if name:
            aliases.append(name)
        for alias in doc.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip():
                aliases.append(alias.strip())
        return aliases


plugin = PlacesIndexerPlugin()
