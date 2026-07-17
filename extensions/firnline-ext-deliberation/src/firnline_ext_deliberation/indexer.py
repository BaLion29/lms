"""IndexerPlugin for deliberation documents — Decisions, Problems, Questions."""
from __future__ import annotations
from typing import Any
from firnline_core.plugins import IndexerPlugin, ModuleRequirement

class DeliberationsIndexerPlugin(IndexerPlugin):
    name: str = "deliberation_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="deliberation", range=">=0.1.0 <0.2.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Decision", "Problem", "Question"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        doc_type = doc.get("@type", "")
        if doc_type == "Decision":
            title = doc.get("title", "")
            decision = doc.get("decision", "")
            consequences = doc.get("consequences")
            parts = [title]
            if decision:
                parts.append(decision)
            if consequences:
                parts.append(consequences)
            return " — ".join(parts)
        elif doc_type == "Problem":
            title = doc.get("title", "")
            description = doc.get("description")
            impact = doc.get("impact")
            parts = [title]
            if description:
                parts.append(description)
            if impact:
                parts.append(impact)
            return " — ".join(parts)
        elif doc_type == "Question":
            question = doc.get("question", "")
            answer = doc.get("answer")
            parts = [question]
            if answer:
                parts.append(answer)
            return " — ".join(parts)
        else:
            return str(doc.get("title", "") or doc.get("question", ""))

    def entity_name(self, doc: dict[str, Any]) -> str:
        doc_type = doc.get("@type", "")
        if doc_type == "Question":
            return str(doc.get("question", ""))
        else:
            return str(doc.get("title", ""))

    def entity_aliases(self, doc: dict[str, Any]) -> list[str]:
        doc_type = doc.get("@type", "")
        if doc_type == "Question":
            question = doc.get("question", "")
            if question:
                return [question]
            return []
        else:
            title = doc.get("title", "")
            if title:
                return [title]
            return []

plugin = DeliberationsIndexerPlugin()
