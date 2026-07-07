"""Graph state — interactive document graph visualization."""

from __future__ import annotations

import json
from typing import Any

import reflex as rx

from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.introspect import browsable_classes, extract_edges
from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

_settings = get_settings()


def _make_tdb() -> TdbBrowser:
    return TdbBrowser(
        _settings.tdb_url,
        _settings.tdb_org,
        _settings.tdb_db,
        _settings.tdb_user,
        _settings.tdb_password,
        branch=_settings.tdb_branch,
        timeout=_settings.request_timeout_seconds,
    )


def _node_label(doc: dict) -> str:
    """Return a human-readable label for a document node."""
    for key in ("name", "title"):
        val = doc.get(key)
        if isinstance(val, str) and val:
            return val
    # Fall back to the last path segment of @id
    doc_id = doc.get("@id", "")
    if isinstance(doc_id, str):
        parts = doc_id.rstrip("/").rsplit("/", 1)
        return parts[-1]
    return str(doc_id)


class GraphState(BaseState):
    """State for the graph view on the /browse page."""

    # View mode toggle
    view: str = "list"

    # Graph data
    nodes: list[dict] = []
    links: list[dict] = []
    loading: bool = False
    loaded: bool = False
    error: str = ""
    filter_class: str = ""  # "" means all classes
    class_options: list[str] = []
    max_nodes: int = 500

    # Detail drawer
    selected_doc: dict | None = None
    selected_json: str = ""

    @rx.var
    def graph_data(self) -> dict:
        return {"nodes": self.nodes, "links": self.links}

    @rx.var
    def all_class_options(self) -> list[str]:
        """Class options with 'all' prepended for the filter select."""
        return ["all", *self.class_options]

    @rx.event
    async def load(self):
        """Fetch schema + documents, build nodes and edges."""
        if self.loading:
            return
        self.loading = True
        self.error = ""
        yield

        tdb = _make_tdb()
        try:
            schema = await tdb.get_schema()
            all_class_ids = browsable_classes(schema)
            self.class_options = all_class_ids

            # Determine which classes to fetch
            fetch_ids = (
                all_class_ids
                if not self.filter_class
                else [self.filter_class]
            )

            all_docs: list[dict] = []
            for cls_id in fetch_ids:
                if len(all_docs) >= self.max_nodes:
                    break
                try:
                    docs = await tdb.get_documents(cls_id)
                except WebuiClientError:
                    continue
                remaining = self.max_nodes - len(all_docs)
                if len(docs) > remaining:
                    all_docs.extend(docs[:remaining])
                    break
                all_docs.extend(docs)

            # Build nodes
            nodes: list[dict] = []
            for doc in all_docs:
                doc_id = doc.get("@id")
                if not isinstance(doc_id, str) or not doc_id:
                    continue
                nodes.append({
                    "id": doc_id,
                    "label": _node_label(doc),
                    "group": doc.get("@type", ""),
                })

            known_ids: set[str] = {n["id"] for n in nodes}
            raw_edges = extract_edges(all_docs, known_ids)
            links: list[dict] = [
                {"source": e["source"], "target": e["target"], "prop": e["prop"]}
                for e in raw_edges
            ]

            self.nodes = nodes
            self.links = links
            self.loaded = True
        except WebuiClientError as exc:
            self.error = f"Failed to load graph data: {exc.detail}"
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def set_filter_class(self, value: Any):
        """Set the class filter and reload."""
        # select.on_change type is str | list[str] at compile time;
        # at runtime it is always a single string for a single-select.
        if isinstance(value, str):
            if value == "all":
                self.filter_class = ""
            else:
                self.filter_class = value
        self.loaded = False
        self.nodes = []
        self.links = []
        return GraphState.load

    @rx.event
    async def select_node(self, node_id: str):
        """Fetch a document when a node is clicked."""
        if not node_id:
            return
        tdb = _make_tdb()
        try:
            doc = await tdb.get_document(node_id)
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
    async def set_view(self, value: Any):
        """Switch between list and graph views."""
        # segmented_control.on_change type is str | list[str] at compile
        # time; at runtime it is always a single string.
        if isinstance(value, str):
            self.view = value
        if self.view == "graph" and not self.loaded:
            return GraphState.load

    @rx.event
    async def load_if_needed(self):
        """Load graph data if not already loaded (for lazy initialization)."""
        if not self.loaded:
            return GraphState.load
