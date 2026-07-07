"""Extraction plugin for Person/Location linking context.

Part of the firnline-ext-people reference extension.
Implements the ``ExtractorPlugin`` protocol with zero proposal models —
only provides linking-context lines via the extractor-plugin hook.
Registered via the ``firnline.ingestd.extractors`` entry point.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from firnline_core.plugins import EntityIndex, ExtractorPlugin, ModuleRequirement


class PeopleLinkingPlugin(ExtractorPlugin):
    """Provides Person/Location context lines for the extraction prompt.

    Has no proposal models — only contributes linking context.
    """

    name: str = "people_linking"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="people", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="places", range=">=0.1.0 <0.2.0"),
    ]
    produces: list[str] = []

    def proposal_models(self) -> list[type[BaseModel]]:
        return []

    def prompt_snippet(self) -> str:
        return ""

    async def linking_context(self, tdb: Any, *, index: Any, branch: str) -> str:
        """Render the Person/Location context block.

        This replaces the kernel-side ``build_context_block`` — the output
        is byte-identical to the previous pipeline-built block.
        """
        return _build_context_block(index)

    async def build_documents(
        self, proposal: BaseModel, ctx: Any
    ) -> list[dict[str, Any]]:
        return []


def _build_context_block(index: EntityIndex) -> str:
    """Render a compact prompt context block listing known people and locations."""

    def _section(label: str, entries: list[tuple[str, str]]) -> str:
        if not entries:
            return f"Known {label}: (none)"
        items = ", ".join(f"{name} <{iri}>" for name, iri in entries)
        return f"Known {label}: {items}"

    return (
        _section("people", index.names("Person"))
        + "\n"
        + _section("locations", index.names("Location"))
    )


# ---------------------------------------------------------------------------
# Module-level instance for entry-point discovery
# ---------------------------------------------------------------------------

plugin = PeopleLinkingPlugin()
