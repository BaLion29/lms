"""IndexerPlugin for Decision documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class DecisionsIndexerPlugin(IndexerPlugin):
    name: str = "decisions_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="decisions", range=">=0.1.0 <0.2.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Decision"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        title = doc.get("title", "")
        context = doc.get("context")
        decision = doc.get("decision", "")
        consequences = doc.get("consequences")
        parts = [title]
        if context:
            parts.append(context)
        if decision:
            parts.append(decision)
        if consequences:
            parts.append(consequences)
        return " — ".join(parts)

    def entity_name(self, doc: dict[str, Any]) -> str:
        return str(doc.get("title", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        title = doc.get("title", "")
        if title:
            return [title]
        return []


plugin = DecisionsIndexerPlugin()
