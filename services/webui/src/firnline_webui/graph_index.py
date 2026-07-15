"""In-memory edge index for graph-view and relationship-browser features.

Framework-free — no Reflex imports.  Pure Python, unit-testable.

The async builder :func:`build_edge_index` fetches schema and documents
through a :class:`firnline_webui.clients.TdbBrowser`, then reuses
:func:`firnline_webui.introspect.extract_edges` and
:func:`firnline_webui.introspect.doc_label` to construct the index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from firnline_webui.clients import WebuiClientError

if TYPE_CHECKING:
    from firnline_webui.clients import TdbBrowser


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class NodeInfo:
    """Lightweight node descriptor."""

    id: str
    """IRI of the document."""

    label: str
    """Human-readable label derived via :func:`~firnline_webui.introspect.doc_label`."""

    type: str
    """Short class name (the ``@type`` field value)."""


@dataclass
class Edge:
    """Directed link from *source* to *target* via *prop*."""

    source: str
    """IRI of the source node."""

    target: str
    """IRI of the target node."""

    prop: str
    """Predicate / field name on the source document."""


@dataclass
class TripleRow:
    """Flat row representation for the relationships-browser table."""

    source_id: str
    source_label: str
    source_type: str
    prop: str
    target_id: str
    target_label: str
    target_type: str


# ── EdgeIndex ───────────────────────────────────────────────────────────────


@dataclass
class EdgeIndex:
    """In-memory graph index built from TerminusDB documents.

    Construct :class:`EdgeIndex` via the async builder
    :func:`build_edge_index`.  Query methods are pure and synchronous.
    """

    nodes: dict[str, NodeInfo]
    """All known nodes, keyed by IRI."""

    edges: list[Edge]
    """All deduplicated edges."""

    errors: dict[str, str] = field(default_factory=dict)
    """Per-class fetch errors (class name → error message)."""

    # Derived, precomputed on build ──────────────────────────────────────
    out_edges: dict[str, list[Edge]] = field(default_factory=dict)
    """For each node IRI, edges where *source* matches."""

    in_edges: dict[str, list[Edge]] = field(default_factory=dict)
    """For each node IRI, edges where *target* matches."""

    predicates: dict[str, int] = field(default_factory=dict)
    """Predicate (field name) → total edge count."""

    type_counts: dict[str, int] = field(default_factory=dict)
    """Class name → total node count."""

    degree: dict[str, int] = field(default_factory=dict)
    """Node IRI → in-degree + out-degree."""

    # ── Query methods ───────────────────────────────────────────────────

    def neighborhood(
        self, node_id: str, hops: int = 1
    ) -> tuple[list[NodeInfo], list[Edge]]:
        """Return the node plus nodes/edges within *hops* (both directions).

        Returns ``([], [])`` when *node_id* is unknown.
        """
        if node_id not in self.nodes:
            return ([], [])

        visited_nodes: set[str] = {node_id}
        visited_edges: set[tuple[str, str, str]] = set()
        frontier: set[str] = {node_id}

        for _ in range(hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                for edge in self.out_edges.get(nid, ()):
                    visited_edges.add((edge.source, edge.target, edge.prop))
                    if edge.target not in visited_nodes:
                        visited_nodes.add(edge.target)
                        next_frontier.add(edge.target)
                for edge in self.in_edges.get(nid, ()):
                    visited_edges.add((edge.source, edge.target, edge.prop))
                    if edge.source not in visited_nodes:
                        visited_nodes.add(edge.source)
                        next_frontier.add(edge.source)
            frontier = next_frontier

        nodes_list: list[NodeInfo] = [
            self.nodes[nid] for nid in visited_nodes
        ]
        edges_list: list[Edge] = [
            e
            for e in self.edges
            if (e.source, e.target, e.prop) in visited_edges
        ]
        return (nodes_list, edges_list)

    def filter(
        self,
        types: set[str] | None = None,
        predicates: set[str] | None = None,
        text: str | None = None,
    ) -> tuple[list[NodeInfo], list[Edge]]:
        """Return nodes/edges matching the given constraints.

        - *types*: keep only nodes whose ``.type`` is in the set.
        - *predicates*: keep only edges whose ``.prop`` is in the set.
        - *text*: case-insensitive substring match on node ``.label`` or ``.id``.

        Edges are only included when **both** endpoints survive the node
        filter.  ``None`` means no constraint.
        """
        matching_ids: set[str] = set(self.nodes.keys())

        if types is not None:
            matching_ids = {
                nid
                for nid in matching_ids
                if self.nodes[nid].type in types
            }

        if text is not None:
            text_lower = text.lower()
            matching_ids = {
                nid
                for nid in matching_ids
                if text_lower in self.nodes[nid].label.lower()
                or text_lower in self.nodes[nid].id.lower()
            }

        matching_edges: list[Edge] = []
        for edge in self.edges:
            if predicates is not None and edge.prop not in predicates:
                continue
            if edge.source in matching_ids and edge.target in matching_ids:
                matching_edges.append(edge)

        matching_nodes: list[NodeInfo] = [
            self.nodes[nid] for nid in matching_ids
        ]
        return (matching_nodes, matching_edges)

    def triples(
        self,
        predicates: set[str] | None = None,
        source_types: set[str] | None = None,
        target_types: set[str] | None = None,
        text: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TripleRow], int]:
        """Return flat rows for a relationships-browser table.

        Optional filters:
        - *predicates*: restrict to edges with these props.
        - *source_types* / *target_types*: restrict by node class.
        - *text*: case-insensitive substring in source/target label or id.

        Returns ``(page: list[TripleRow], total_matching: int)``.
        """
        filtered: list[TripleRow] = []
        for edge in self.edges:
            if predicates is not None and edge.prop not in predicates:
                continue

            src = self.nodes.get(edge.source)
            tgt = self.nodes.get(edge.target)
            if src is None or tgt is None:
                continue

            if source_types is not None and src.type not in source_types:
                continue
            if target_types is not None and tgt.type not in target_types:
                continue

            if text is not None:
                text_lower = text.lower()
                if not (
                    text_lower in src.label.lower()
                    or text_lower in src.id.lower()
                    or text_lower in tgt.label.lower()
                    or text_lower in tgt.id.lower()
                ):
                    continue

            filtered.append(
                TripleRow(
                    source_id=src.id,
                    source_label=src.label,
                    source_type=src.type,
                    prop=edge.prop,
                    target_id=tgt.id,
                    target_label=tgt.label,
                    target_type=tgt.type,
                )
            )

        total = len(filtered)
        page = filtered[offset : offset + limit]
        return (page, total)


# ── Async builder ───────────────────────────────────────────────────────────


async def build_edge_index(
    browser: TdbBrowser,
    class_names: list[str] | None = None,
    max_docs_per_class: int | None = None,
) -> EdgeIndex:
    """Build an :class:`EdgeIndex` from the TerminusDB database via *browser*.

    Parameters
    ----------
    browser:
        Connected :class:`~firnline_webui.clients.TdbBrowser`.
    class_names:
        Document classes to fetch.  Defaults to all
        :func:`~firnline_webui.introspect.browsable_classes`.
    max_docs_per_class:
        If set, only the first *N* documents per class are included.

    Returns
    -------
    EdgeIndex
        A fully built index with precomputed derived structures.
    """
    errors: dict[str, str] = {}

    # ── Fetch schema ────────────────────────────────────────────────────
    schema = await browser.get_schema()
    schema_meta: dict[str, dict[str, Any]] = {}
    for entry in schema:
        if entry.get("@type") == "Class":
            cid = entry.get("@id")
            if isinstance(cid, str) and cid:
                schema_meta[cid] = entry

    if class_names is None:
        from firnline_webui.introspect import browsable_classes

        class_names = browsable_classes(schema)

    # ── Fetch documents per class ───────────────────────────────────────
    all_docs: list[dict[str, Any]] = []
    for class_name in class_names:
        try:
            docs = await browser.get_documents(class_name)
        except WebuiClientError as exc:
            errors[class_name] = str(exc)
            continue

        if max_docs_per_class is not None:
            docs = docs[:max_docs_per_class]
        all_docs.extend(docs)

    # ── Build nodes ─────────────────────────────────────────────────────
    nodes: dict[str, NodeInfo] = {}
    from firnline_webui.introspect import doc_label

    for doc in all_docs:
        doc_id = doc.get("@id")
        if not isinstance(doc_id, str) or not doc_id:
            continue
        doc_type = doc.get("@type", "?")
        class_def = schema_meta.get(doc_type)
        label = doc_label(doc, class_def=class_def)
        nodes[doc_id] = NodeInfo(id=doc_id, label=label, type=doc_type)

    # ── Build edges ─────────────────────────────────────────────────────
    known_ids = set(nodes.keys())
    from firnline_webui.introspect import extract_edges

    raw_edges = extract_edges(all_docs, known_ids)
    edges: list[Edge] = [
        Edge(source=e["source"], target=e["target"], prop=e["prop"])
        for e in raw_edges
    ]

    # ── Precompute derived structures ───────────────────────────────────
    out_edges: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    in_edges: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    predicates: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    degree: dict[str, int] = {}

    for edge in edges:
        out_edges[edge.source].append(edge)
        in_edges[edge.target].append(edge)
        predicates[edge.prop] = predicates.get(edge.prop, 0) + 1

    for node_id, node_info in nodes.items():
        degree[node_id] = len(out_edges[node_id]) + len(in_edges[node_id])
        type_counts[node_info.type] = (
            type_counts.get(node_info.type, 0) + 1
        )

    return EdgeIndex(
        nodes=nodes,
        edges=edges,
        errors=errors,
        out_edges=out_edges,
        in_edges=in_edges,
        predicates=predicates,
        type_counts=type_counts,
        degree=degree,
    )
