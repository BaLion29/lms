"""Graph state — interactive document graph visualization.

Builds an :class:`~firnline_webui.graph_index.EdgeIndex` once from the
database, then performs all filtering client-side via the index.
"""

from __future__ import annotations

import json
from typing import Any

import reflex as rx

from firnline_webui.clients import WebuiClientError, make_tdb_browser
from firnline_webui.graph_index import EdgeIndex, build_edge_index
from firnline_webui.state.base import BaseState

# Deterministic palette — 12 colours reused cyclically.
_COLORS: list[str] = [
    "#3B82F6",  # blue
    "#EF4444",  # red
    "#22C55E",  # green
    "#F59E0B",  # amber
    "#8B5CF6",  # violet
    "#EC4899",  # pink
    "#06B6D4",  # cyan
    "#F97316",  # orange
    "#14B8A6",  # teal
    "#A855F7",  # purple
    "#E11D48",  # rose
    "#84CC16",  # lime
]


def _assign_colors(types_sorted: list[str]) -> dict[str, str]:
    """Return a deterministic type→colour mapping."""
    return {t: _COLORS[i % len(_COLORS)] for i, t in enumerate(types_sorted)}


def _build_legend(type_colors: dict[str, str], index: EdgeIndex | None) -> list[dict]:
    """Build legend items for types that actually appear in *index*."""
    if index is None:
        return []
    items: list[dict] = []
    for t, color in type_colors.items():
        if index.type_counts.get(t, 0) > 0:
            items.append({"label": t, "color": color})
    return items


class GraphState(BaseState):
    """State for the graph view on the /browse page."""

    # ── View mode toggle ──────────────────────────────────────────────
    view: str = "list"

    # ── Graph data (serialisable — sent to frontend) ──────────────────
    nodes: list[dict] = []
    links: list[dict] = []
    loading: bool = False
    loaded: bool = False
    error: str = ""

    # ── EdgeIndex (kept server-side, NOT a Var) ──────────────────────
    _index: EdgeIndex | None = None
    _type_colors: dict[str, str] = {}  # type → colour string

    # ── Filters ───────────────────────────────────────────────────────
    active_types: list[str] = []  # selected class filter (empty = all)
    active_predicates: list[str] = []  # selected edge predicate filter (empty = all)
    search_text: str = ""

    # ── Node cap ──────────────────────────────────────────────────────
    max_nodes: int = 500
    truncated: bool = False
    total_filtered: int = 0  # count before truncation

    # ── Index fetch errors ────────────────────────────────────────────
    index_errors: list[str] = []

    # ── Focus mode ────────────────────────────────────────────────────
    focus_node_id: str = ""
    focus_node_label: str = ""
    focus_node_type: str = ""
    focus_node_degree: int = 0
    focus_node_out: int = 0
    focus_node_in: int = 0
    focus_hops: int = 1
    is_focused: bool = False

    # ── Detail drawer ─────────────────────────────────────────────────
    selected_doc: dict | None = None
    selected_json: str = ""

    # ── Derived display data (plain vars — recomputed on load) ──────
    type_counts_list: list[dict] = []
    predicate_list: list[dict] = []
    legend_items: list[dict] = []

    # ── Computed vars ─────────────────────────────────────────────────

    @rx.var
    def graph_data(self) -> dict:
        return {"nodes": self.nodes, "links": self.links}

    # ── Internal helpers ──────────────────────────────────────────────

    def _refresh_derived(self) -> None:
        """Recompute UI-facing data derived from ``_index`` / ``_type_colors``."""
        idx = self._index
        if idx is None:
            self.type_counts_list = []
            self.predicate_list = []
            self.legend_items = []
            return
        self.type_counts_list = [
            {"type": t, "count": c}
            for t, c in sorted(idx.type_counts.items())
        ]
        self.predicate_list = [
            {"prop": p, "count": c}
            for p, c in sorted(idx.predicates.items())
        ]
        self.legend_items = _build_legend(self._type_colors, idx)

    def _recompute_display(self) -> None:
        """Recompute self.nodes / self.links from _index + filters + cap."""
        idx = self._index
        if idx is None:
            self.nodes = []
            self.links = []
            self.truncated = False
            self.total_filtered = 0
            return

        if self.is_focused and self.focus_node_id:
            node_infos, edges = idx.neighborhood(
                self.focus_node_id, hops=self.focus_hops
            )
        else:
            types_set: set[str] | None = (
                set(self.active_types) if self.active_types else None
            )
            preds_set: set[str] | None = (
                set(self.active_predicates) if self.active_predicates else None
            )
            txt: str | None = self.search_text.strip() if self.search_text.strip() else None
            node_infos, edges = idx.filter(
                types=types_set, predicates=preds_set, text=txt
            )

        total = len(node_infos)
        self.total_filtered = total

        # Apply node cap
        capped = node_infos[: self.max_nodes]
        self.truncated = total > self.max_nodes

        capped_ids = {n.id for n in capped}
        capped_edges = [
            e for e in edges if e.source in capped_ids and e.target in capped_ids
        ]

        self.nodes = [
            {
                "id": ni.id,
                "label": ni.label,
                "group": ni.type,
                "color": self._type_colors.get(ni.type, "#94A3B8"),
            }
            for ni in capped
        ]
        self.links = [
            {"source": e.source, "target": e.target, "prop": e.prop}
            for e in capped_edges
        ]

    # ── Event handlers ────────────────────────────────────────────────

    @rx.event
    async def load(self):
        """Fetch schema + documents via EdgeIndex, then recompute display."""
        if self.loading:
            return
        self.loading = True
        self.error = ""
        self.index_errors = []
        yield

        tdb = make_tdb_browser()
        try:
            index = await build_edge_index(tdb, max_docs_per_class=self.max_nodes)

            self._index = index
            # Record per-class fetch errors
            self.index_errors = [
                f"{cls_name}: {msg}" for cls_name, msg in index.errors.items()
            ]
            # Assign colours deterministically
            sorted_types = sorted(index.type_counts.keys())
            self._type_colors = _assign_colors(sorted_types)

            self.loaded = True
            self.truncated = False
            self.total_filtered = 0
            self._refresh_derived()
            self._recompute_display()
        except WebuiClientError as exc:
            self.error = f"Failed to load graph data: {exc.detail}"
            self.loaded = False
        except Exception as exc:
            self.error = f"Failed to load graph data: {exc}"
            self.loaded = False
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    def toggle_type(self, type_name: str):
        """Toggle a class type in the active filter set."""
        if type_name in self.active_types:
            self.active_types = [t for t in self.active_types if t != type_name]
        else:
            self.active_types = [*self.active_types, type_name]
        self._recompute_display()
        yield

    @rx.event
    def toggle_predicate(self, prop: str):
        """Toggle a predicate in the active filter set."""
        if prop in self.active_predicates:
            self.active_predicates = [p for p in self.active_predicates if p != prop]
        else:
            self.active_predicates = [*self.active_predicates, prop]
        self._recompute_display()
        yield

    @rx.event
    def set_search(self, text: str):
        """Set the node label/id search text."""
        self.search_text = text
        self._recompute_display()
        yield

    @rx.event
    def set_max_nodes(self, value: str):
        """Change the node cap from a select dropdown string value."""
        try:
            new_cap = int(value)
            if new_cap > 0:
                self.max_nodes = new_cap
        except (ValueError, TypeError):
            pass
        self._recompute_display()
        yield

    @rx.event
    async def select_node(self, node_id: str):
        """Fetch a document for the detail drawer and populate focus panel."""
        if not node_id:
            return

        # Fetch document for detail drawer
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(node_id)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()

        # Populate focus-panel info from the index
        idx = self._index
        if idx is not None:
            ni = idx.nodes.get(node_id)
            if ni is not None:
                self.focus_node_id = ni.id
                self.focus_node_label = ni.label
                self.focus_node_type = ni.type
                self.focus_node_degree = idx.degree.get(node_id, 0)
                self.focus_node_out = len(idx.out_edges.get(node_id, []))
                self.focus_node_in = len(idx.in_edges.get(node_id, []))
            else:
                self.focus_node_id = node_id
                self.focus_node_label = node_id
                self.focus_node_type = ""
                self.focus_node_degree = 0
                self.focus_node_out = 0
                self.focus_node_in = 0
        yield

    @rx.event
    def focus_current(self):
        """Enter focus mode for the currently selected node."""
        if self.focus_node_id and not self.is_focused:
            self.is_focused = True
            self.focus_hops = 1
            self._recompute_display()
        yield

    @rx.event
    def set_focus_hops(self, value: str):
        """Change neighbourhood hop count in focus mode."""
        try:
            hops = int(value)
            if hops >= 1:
                self.focus_hops = hops
        except (ValueError, TypeError):
            pass
        if self.is_focused:
            self._recompute_display()
        yield

    @rx.event
    def exit_focus(self):
        """Exit focus mode, restore filtered full view."""
        self.is_focused = False
        self._recompute_display()
        yield

    @rx.event
    async def clear_selection(self):
        """Close the detail drawer."""
        self.selected_doc = None
        self.selected_json = ""
        yield

    @rx.event
    async def set_view(self, value: Any):
        """Switch between list and graph views."""
        if isinstance(value, str):
            self.view = value
        if self.view == "graph" and not self.loaded:
            return GraphState.load  # type: ignore[return-value]

    @rx.event
    async def load_if_needed(self):
        """Load graph data if not already loaded (for lazy initialization)."""
        if not self.loaded:
            return GraphState.load  # type: ignore[return-value]

    @rx.event
    def dismiss_index_errors(self):
        """Dismiss per-class fetch error warnings."""
        self.index_errors = []
        yield
