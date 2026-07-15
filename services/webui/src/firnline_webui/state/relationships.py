"""Relationships state — triples browser backed by EdgeIndex."""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import WebuiClientError, make_tdb_browser
from firnline_webui.graph_index import EdgeIndex, build_edge_index
from firnline_webui.state.base import BaseState
from firnline_webui.state.selection import SelectionMixin


class RelationshipsState(BaseState, SelectionMixin):
    """State for the relationships (triples) browser on the /browse page."""

    # ── Backend var (NOT a Reflex Var) ────────────────────────────────
    _index: EdgeIndex | None = None

    # ── Status ────────────────────────────────────────────────────────
    loading: bool = False
    loaded: bool = False
    error: str = ""

    # ── Filter vars ───────────────────────────────────────────────────
    active_predicates: list[str] = []
    active_source_types: list[str] = []
    active_target_types: list[str] = []
    search_text: str = ""

    # ── Pagination ────────────────────────────────────────────────────
    page: int = 0
    page_size: int = 25
    total_count: int = 0

    # ── Index fetch errors ────────────────────────────────────────────
    index_errors: list[str] = []

    # ── Rows + option lists (plain vars refreshed by _refresh_rows) ──
    rows: list[dict] = []
    predicate_options: list[dict] = []
    source_type_options: list[dict] = []
    target_type_options: list[dict] = []

    # ── Computed vars ─────────────────────────────────────────────────

    @rx.var
    def total_pages(self) -> int:
        if self.page_size <= 0 or self.total_count <= 0:
            return 0
        return (self.total_count + self.page_size - 1) // self.page_size

    # ── Internal helpers ──────────────────────────────────────────────

    def _refresh_rows(self) -> None:
        """Recompute rows + option lists from _index and current filters."""
        idx = self._index
        if idx is None:
            self.rows = []
            self.predicate_options = []
            self.source_type_options = []
            self.target_type_options = []
            self.total_count = 0
            return

        offset = self.page * self.page_size

        triples, total = idx.triples(
            predicates=set(self.active_predicates) if self.active_predicates else None,
            source_types=set(self.active_source_types) if self.active_source_types else None,
            target_types=set(self.active_target_types) if self.active_target_types else None,
            text=self.search_text.strip() if self.search_text.strip() else None,
            offset=offset,
            limit=self.page_size,
        )

        self.total_count = total
        self.rows = [
            {
                "source_id": r.source_id,
                "source_label": r.source_label,
                "source_type": r.source_type,
                "prop": r.prop,
                "target_id": r.target_id,
                "target_label": r.target_label,
                "target_type": r.target_type,
            }
            for r in triples
        ]

        # Option lists derived from the full index (not filtered)
        self.predicate_options = [
            {"label": p, "count": c}
            for p, c in sorted(idx.predicates.items())
        ]
        # Per-role type counts computed from edges (not total node counts)
        src_counts: dict[str, int] = {}
        tgt_counts: dict[str, int] = {}
        for edge in idx.edges:
            src_node = idx.nodes.get(edge.source)
            tgt_node = idx.nodes.get(edge.target)
            if src_node is not None:
                src_counts[src_node.type] = src_counts.get(src_node.type, 0) + 1
            if tgt_node is not None:
                tgt_counts[tgt_node.type] = tgt_counts.get(tgt_node.type, 0) + 1
        self.source_type_options = [
            {"label": t, "count": c}
            for t, c in sorted(src_counts.items())
        ]
        self.target_type_options = [
            {"label": t, "count": c}
            for t, c in sorted(tgt_counts.items())
        ]

    def _reset_page_and_refresh(self) -> None:
        """Reset to page 0 and recompute rows."""
        self.page = 0
        self._refresh_rows()

    # ── Event handlers ────────────────────────────────────────────────

    @rx.event
    async def load(self):
        """Build the EdgeIndex from the database."""
        if self.loading:
            return
        self.loading = True
        self.error = ""
        self.index_errors = []
        yield

        tdb = make_tdb_browser()
        try:
            index = await build_edge_index(tdb)
            self._index = index
            self.index_errors = [
                f"{cls_name}: {msg}" for cls_name, msg in index.errors.items()
            ]
            self.loaded = True
            self._refresh_rows()
        except WebuiClientError as exc:
            self.error = f"Failed to load relationships: {exc.detail}"
            self.loaded = False
        except Exception as exc:
            self.error = f"Failed to load relationships: {exc}"
            self.loaded = False
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def refresh(self):
        """Full rebuild of the index."""
        self._index = None
        self.loaded = False
        self.page = 0
        return RelationshipsState.load  # type: ignore[return-value]

    @rx.event
    async def load_if_needed(self):
        """Lazily load if not already loaded."""
        if not self.loaded:
            return RelationshipsState.load  # type: ignore[return-value]

    @rx.event
    def toggle_predicate(self, prop: str):
        """Toggle a predicate filter."""
        if prop in self.active_predicates:
            self.active_predicates = [p for p in self.active_predicates if p != prop]
        else:
            self.active_predicates = [*self.active_predicates, prop]
        self._reset_page_and_refresh()
        yield

    @rx.event
    def toggle_source_type(self, type_name: str):
        """Toggle a source-type filter."""
        if type_name in self.active_source_types:
            self.active_source_types = [t for t in self.active_source_types if t != type_name]
        else:
            self.active_source_types = [*self.active_source_types, type_name]
        self._reset_page_and_refresh()
        yield

    @rx.event
    def toggle_target_type(self, type_name: str):
        """Toggle a target-type filter."""
        if type_name in self.active_target_types:
            self.active_target_types = [t for t in self.active_target_types if t != type_name]
        else:
            self.active_target_types = [*self.active_target_types, type_name]
        self._reset_page_and_refresh()
        yield

    @rx.event
    def set_search(self, text: str):
        """Set search text and reset page."""
        self.search_text = text
        self._reset_page_and_refresh()
        yield

    @rx.event
    def next_page(self):
        """Go to next page."""
        if self.page + 1 < self.total_pages:
            self.page += 1
            self._refresh_rows()
        yield

    @rx.event
    def prev_page(self):
        """Go to previous page."""
        if self.page > 0:
            self.page -= 1
            self._refresh_rows()
        yield

    @rx.event
    def set_page_size(self, value: str):
        """Update page size and reset to page 0."""
        try:
            new_size = int(value)
        except (ValueError, TypeError):
            return
        if new_size <= 0:
            return
        self.page_size = new_size
        self._reset_page_and_refresh()
        yield

    @rx.event
    async def select_endpoint(self, iri: str):
        """Fetch a single document by IRI and open the detail drawer."""
        if not iri:
            return
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(iri)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def show_in_graph(self, source_iri: str):
        """Switch to the Graph tab and focus on node neighbourhood."""
        from firnline_webui.state.browse import BrowseState  # noqa: PLC0415
        from firnline_webui.state.graph import GraphState  # noqa: PLC0415

        browse_state = await self.get_state(BrowseState)
        browse_state.tab = "graph"
        yield
        yield GraphState.load_if_needed
        yield
        yield GraphState.select_node(source_iri)
        yield
        yield GraphState.focus_current

    @rx.event
    def dismiss_index_errors(self):
        """Dismiss per-class fetch error warnings."""
        self.index_errors = []
        yield
