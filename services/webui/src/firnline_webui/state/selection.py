"""Shared selection mixin for state classes with a detail drawer.

Provides ``selected_doc`` / ``selected_json`` vars and ``select`` /
``clear_selection`` event handlers via a Reflex mixin.  States with
different handler names or extra side‑effects can override or keep their
own handlers while still inheriting the vars.
"""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import WebuiClientError, make_tdb_browser


class SelectionMixin(rx.State, mixin=True):
    """Mixin with document‑selection vars and core event handlers."""

    selected_doc: dict | None = None
    selected_json: str = ""

    @rx.event
    async def select(self, doc_id: str):
        """Fetch a single document by IRI and open the detail drawer."""
        if not doc_id:
            return
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(doc_id)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def clear_selection(self):
        """Close the detail drawer."""
        self.selected_doc = None
        self.selected_json = ""
        yield
