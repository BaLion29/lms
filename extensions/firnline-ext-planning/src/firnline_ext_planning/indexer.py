"""IndexerPlugin for Task and Event documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class PlanningIndexerPlugin(IndexerPlugin):
    name: str = "planning_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="planning", range=">=2.0.0 <3.0.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Task", "Event"]

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


plugin = PlanningIndexerPlugin()
