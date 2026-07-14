"""Inbox state — introspection-driven inbox view."""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.introspect import doc_preview, inbox_classes
from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

_settings = get_settings()


async def _load_inbox_rows(tdb: TdbBrowser) -> tuple[list[dict], set[str]]:
    """Fetch schema, find Captured class, fetch all Captured documents.

    Returns ``(rows, statuses)``.  Raises ``WebuiClientError`` on schema
    failure; per-class fetch failures are silently skipped.
    """
    schema = await tdb.get_schema()
    class_ids = inbox_classes(schema)
    if not class_ids:
        return [], set()

    all_rows: list[dict] = []
    statuses: set[str] = set()

    for cid in class_ids:
        try:
            docs = await tdb.get_documents(cid)
        except WebuiClientError:
            continue

        for doc in docs:
            iri = doc.get("@id", "")
            status = str(doc.get("status", ""))
            captured_at = str(doc.get("captured_at", ""))
            content_type = str(doc.get("content_type", ""))
            # Preview: prefer content, fallback to transcription
            preview = doc_preview(doc)
            all_rows.append(
                {
                    "class": cid,
                    "id": iri,
                    "status": status,
                    "captured_at": captured_at,
                    "content_type": content_type,
                    "preview": preview,
                }
            )
            if status:
                statuses.add(status)

    all_rows.sort(key=lambda r: r.get("captured_at") or "", reverse=True)
    return all_rows, statuses


class InboxState(BaseState):
    """State for the /inbox page."""

    rows: list[dict] = []
    loading: bool = False
    error: str = ""
    status_filter: str = "all"
    available_statuses: list[str] = []

    # Detail drawer
    selected_doc: dict | None = None
    selected_json: str = ""

    def _make_tdb(self) -> TdbBrowser:
        return TdbBrowser(
            _settings.tdb_url,
            _settings.tdb_org,
            _settings.tdb_db,
            _settings.tdb_user,
            _settings.tdb_password,
            branch=_settings.tdb_branch,
            timeout=_settings.request_timeout_seconds,
        )

    @rx.event
    async def load(self):
        """Load schema, find inbox classes, fetch all documents."""
        self.loading = True
        self.error = ""
        self.selected_doc = None
        self.selected_json = ""
        yield

        tdb = self._make_tdb()
        try:
            all_rows, statuses = await _load_inbox_rows(tdb)
        except WebuiClientError as exc:
            self.error = f"Failed to load schema: {exc.detail}"
        else:
            self.rows = all_rows
            self.available_statuses = sorted(statuses)
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def set_status_filter(self, value: str):
        """Set the active status filter chip."""
        self.status_filter = value
        yield

    @rx.event
    async def select(self, doc_id: str):
        """Fetch a single document by IRI and open the detail drawer."""
        tdb = self._make_tdb()
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

    @rx.event
    def refresh(self):
        """Alias for load."""
        return self.load()

    @rx.var
    def filtered_rows(self) -> list[dict]:
        """Rows filtered by the active status filter."""
        if self.status_filter == "all":
            return self.rows
        return [r for r in self.rows if r.get("status") == self.status_filter]
