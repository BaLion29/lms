"""IndexerPlugin for Routine and Activity documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class RoutinesIndexerPlugin(IndexerPlugin):
    name: str = "routines_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="routines", range=">=1.0.0 <2.0.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Routine", "Activity"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        name = doc.get("name", "")
        description = doc.get("description", "")
        parts = [name]
        if description:
            parts.append(description)
        return " — ".join(parts)

    def entity_name(self, doc: dict[str, Any]) -> str:
        return str(doc.get("name", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        name = doc.get("name", "")
        if name:
            return [name]
        return []


plugin = RoutinesIndexerPlugin()
