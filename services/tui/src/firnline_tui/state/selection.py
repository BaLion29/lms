"""SelectionController — selected-document detail loading (framework-free)."""
from __future__ import annotations

import json


from firnline_tui.state.context import AppContext


class SelectionController:
    """Selected-document detail loading. Owned by screens that show a detail panel."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._selected_iri: str | None = None

    async def select(self, iri: str) -> str:
        """Fetch document by IRI, return pretty-printed JSON. Raises UiClientError."""
        if not iri:
            return ""
        self._selected_iri = iri
        tdb = self._ctx.make_tdb()
        try:
            doc = await tdb.get_document(iri)
            return json.dumps(doc, indent=2, default=str)
        finally:
            await tdb.aclose()

    def clear(self) -> None:
        self._selected_iri = None

    @property
    def selected_iri(self) -> str | None:
        return self._selected_iri
