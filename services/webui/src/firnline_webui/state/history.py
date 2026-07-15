"""History state — commit log browsing."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import reflex as rx

from firnline_webui.clients import WebuiClientError, make_tdb_browser
from firnline_webui.state.base import BaseState
from firnline_webui.state.selection import SelectionMixin

_LOG_COUNT = 200


def _format_ts(ts: float | None) -> str:
    """Format a POSIX timestamp into a human-readable string."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""


class HistoryState(BaseState, SelectionMixin):
    """State for the /history page."""

    rows: list[dict] = []
    loading: bool = False
    error: str = ""

    # Pagination
    page_index: int = 0
    page_size: int = 25

    # Selected commit
    selected_commit_id: str = ""
    selected_commit: dict | None = None

    # Changes for selected commit
    inserted: list[str] = []
    updated: list[str] = []
    deleted: list[str] = []
    changes_loading: bool = False
    changes_error: str = ""
    _changes_cache: dict[str, dict] = {}  # commit_id → {inserted, updated, deleted}

    @rx.var
    def total_pages(self) -> int:
        if self.page_size <= 0 or len(self.rows) <= 0:
            return 0
        return (len(self.rows) + self.page_size - 1) // self.page_size

    @rx.var
    def paged_rows(self) -> list[dict]:
        start = self.page_index * self.page_size
        return self.rows[start : start + self.page_size]

    @rx.var
    def total_count(self) -> int:
        return len(self.rows)

    @rx.event
    async def load(self):
        """Fetch commit log and pre-format timestamps."""
        self.loading = True
        self.error = ""
        self.rows = []
        self.page_index = 0
        self.selected_commit_id = ""
        self.selected_commit = None
        self.inserted = []
        self.updated = []
        self.deleted = []
        self.changes_loading = False
        self.changes_error = ""
        self.selected_doc = None
        self.selected_json = ""
        yield

        tdb = make_tdb_browser()
        try:
            commits = await tdb.get_commit_log(_LOG_COUNT)
        except WebuiClientError as exc:
            self.error = f"Failed to load commit log: {exc.detail}"
        except Exception as exc:
            self.error = f"Failed to load commit log: {exc!s}"
        else:
            formatted: list[dict] = []
            for c in commits:
                formatted.append(
                    {
                        "id": c.get("id", ""),
                        "short_id": c.get("short_id", ""),
                        "author": c.get("author", ""),
                        "message": c.get("message", ""),
                        "timestamp": c.get("timestamp"),
                        "timestamp_fmt": _format_ts(c.get("timestamp")),
                    }
                )
            self.rows = formatted
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def next_page(self):
        """Go to next page."""
        if self.page_index + 1 < self.total_pages:
            self.page_index += 1
        yield

    @rx.event
    async def prev_page(self):
        """Go to previous page."""
        if self.page_index > 0:
            self.page_index -= 1
        yield

    @rx.event
    async def select_commit(self, commit_id: str):
        """Open commit detail and lazily fetch changes."""
        if not commit_id:
            return
        self.selected_commit_id = commit_id
        # Find metadata from rows
        self.selected_commit = next(
            (r for r in self.rows if r["id"] == commit_id),
            None,
        )
        yield

        # Check cache first
        if commit_id in self._changes_cache:
            cached = self._changes_cache[commit_id]
            self.inserted = cached.get("inserted", [])
            self.updated = cached.get("updated", [])
            self.deleted = cached.get("deleted", [])
            self.changes_loading = False
            self.changes_error = ""
            yield
            return

        self.changes_loading = True
        self.changes_error = ""
        self.inserted = []
        self.updated = []
        self.deleted = []
        yield

        tdb = make_tdb_browser()
        try:
            changes = await tdb.get_commit_changes(commit_id)
        except WebuiClientError as exc:
            self.changes_error = f"Failed to load changes: {exc.detail}"
            changes = {}
        except Exception as exc:
            self.changes_error = f"Failed to load changes: {exc!s}"
            changes = {}
        finally:
            await tdb.aclose()

        inserted = changes.get("inserted", []) or []
        updated = changes.get("updated", []) or []
        deleted = changes.get("deleted", []) or []

        self._changes_cache[commit_id] = {
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted,
        }
        self.inserted = inserted
        self.updated = updated
        self.deleted = deleted
        self.changes_loading = False
        yield

    @rx.event
    async def open_document(self, iri: str):
        """Fetch a single document by IRI and show in detail drawer."""
        if not iri:
            return
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(iri)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {
                "@id": iri,
                "error": f"Document not available (may have been deleted): {exc.detail}",
            }
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        except Exception as exc:
            self.selected_doc = {
                "@id": iri,
                "error": f"Failed to load document: {exc!s}",
            }
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def clear_document(self):
        """Close the document detail drawer."""
        self.selected_doc = None
        self.selected_json = ""
        yield

    @rx.event
    async def close_commit_detail(self):
        """Close the commit detail drawer."""
        self.selected_commit_id = ""
        self.selected_commit = None
        self.inserted = []
        self.updated = []
        self.deleted = []
        self.changes_loading = False
        self.changes_error = ""
        yield

    @rx.event
    def refresh(self):
        """Alias for load."""
        return self.load()
