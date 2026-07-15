"""IndexerPlugin for Task, Event, Routine, Activity, Project, Area, and Goal documents."""

from __future__ import annotations

from typing import Any

from firnline_core.plugins import IndexerPlugin, ModuleRequirement


class TimeManagementIndexerPlugin(IndexerPlugin):
    name: str = "time_management_indexer"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.2.0 <0.3.0"),
    ]

    def indexed_classes(self) -> list[str]:
        return ["Task", "Event", "Routine", "Activity", "Project", "Area", "Goal"]

    def entity_text(self, doc: dict[str, Any]) -> str:
        name = doc.get("name", "")
        description = doc.get("description", "")
        success_criteria = doc.get("success_criteria")
        parts = [name]
        if description:
            parts.append(description)
        if success_criteria:
            parts.append(success_criteria)
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


plugin = TimeManagementIndexerPlugin()
