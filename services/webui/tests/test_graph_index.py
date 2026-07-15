"""Tests for graph_index.py — EdgeIndex and its async builder."""

from __future__ import annotations

import pytest

from firnline_core.tdb import TdbError
from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.graph_index import (
    Edge,
    EdgeIndex,
    NodeInfo,
    TripleRow,
    build_edge_index,
)


# ── Fake TdbClient + Browser factory ────────────────────────────────────────


class _FakeTdb:
    """Drop-in for firnline_core TdbClient with configurable canned data."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        docs_by_class: dict[str, list[dict]] | None = None,
        doc_by_iri: dict[str, dict] | None = None,
        raise_schema: Exception | None = None,
        classes_raising: dict[str, Exception] | None = None,
    ) -> None:
        self._schema = schema or []
        self._docs_by_class = docs_by_class or {}
        self._doc_by_iri = doc_by_iri or {}
        self._raise_schema = raise_schema
        self._classes_raising = classes_raising or {}
        self.aclose_called = False

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_schema is not None:
            raise self._raise_schema
        return self._schema

    async def get_documents(
        self, type_: str, branch: str = "main",
        skip: int | None = None, count: int | None = None,
    ) -> list[dict]:
        if type_ in self._classes_raising:
            raise self._classes_raising[type_]
        return self._docs_by_class.get(type_, [])

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        if iri in self._doc_by_iri:
            return self._doc_by_iri[iri]
        return {"@id": iri}

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_browser(fake: _FakeTdb) -> TdbBrowser:
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)


# ── Helpers: mini schema/docs fixtures ──────────────────────────────────────


def _task_person_schema() -> list[dict]:
    return [
        {"@type": "Class", "@id": "Task", "name": "xsd:string", "assignee": "Person"},
        {"@type": "Class", "@id": "Person", "name": "xsd:string"},
        {"@type": "Class", "@id": "Tag", "name": "xsd:string"},
        {"@type": "Context"},
        {"@type": "Enum", "@id": "Status"},
    ]


def _task_person_docs() -> dict[str, list[dict]]:
    return {
        "Task": [
            {"@id": "Task/1", "@type": "Task", "name": "Write tests", "assignee": "Person/alice"},
            {"@id": "Task/2", "@type": "Task", "name": "Review", "assignee": "Person/bob"},
        ],
        "Person": [
            {"@id": "Person/alice", "@type": "Person", "name": "Alice"},
            {"@id": "Person/bob", "@type": "Person", "name": "Bob"},
        ],
    }


# ── build_edge_index ────────────────────────────────────────────────────────


async def test_build_basic():
    """Happy path: nodes and edges are built correctly."""
    fake = _FakeTdb(schema=_task_person_schema(), docs_by_class=_task_person_docs())
    browser = _make_browser(fake)
    index = await build_edge_index(browser)

    # Nodes
    assert len(index.nodes) == 4
    assert index.nodes["Task/1"].label == "Write tests"
    assert index.nodes["Task/1"].type == "Task"
    assert index.nodes["Person/alice"].label == "Alice"
    assert index.nodes["Person/alice"].type == "Person"

    # Edges
    assert len(index.edges) == 2
    props = {e.prop for e in index.edges}
    assert props == {"assignee"}

    # Derived
    assert index.type_counts == {"Task": 2, "Person": 2}
    assert index.predicates == {"assignee": 2}
    assert index.degree["Task/1"] == 1
    assert index.degree["Person/alice"] == 1
    assert index.degree["Person/bob"] == 1


async def test_build_class_names_filter():
    """Only requested classes are fetched."""
    fake = _FakeTdb(schema=_task_person_schema(), docs_by_class=_task_person_docs())
    browser = _make_browser(fake)
    index = await build_edge_index(browser, class_names=["Task"])

    assert len(index.nodes) == 2
    assert all(n.type == "Task" for n in index.nodes.values())
    # No Person nodes → no edges survive because targets unknown
    assert len(index.edges) == 0


async def test_build_max_docs_per_class():
    """max_docs_per_class truncates."""
    fake = _FakeTdb(schema=_task_person_schema(), docs_by_class=_task_person_docs())
    browser = _make_browser(fake)
    index = await build_edge_index(browser, max_docs_per_class=1)

    # Should have at most 1 Task + the 2 Person docs (Person wasn't truncated
    # because max applies per class, and we still get all Person)
    # Actually max_docs_per_class applies to each class: Task gets 1, Person gets 1
    assert len(index.nodes) == 2  # 1 Task + 1 Person


async def test_build_per_class_error_tolerance():
    """Failing class is skipped and recorded in errors."""
    fake = _FakeTdb(
        schema=_task_person_schema(),
        docs_by_class=_task_person_docs(),
        classes_raising={"Task": TdbError(500, "task fetch boom")},
    )
    browser = _make_browser(fake)
    index = await build_edge_index(browser)

    assert "Task" in index.errors
    assert "task fetch boom" in index.errors["Task"]
    # Person docs still loaded
    assert len(index.nodes) == 2  # Person/alice, Person/bob
    assert all(n.type == "Person" for n in index.nodes.values())


async def test_build_per_class_webui_client_error_tolerance():
    """WebuiClientError is tolerated per-class, recorded in errors."""
    fake = _FakeTdb(
        schema=_task_person_schema(),
        docs_by_class=_task_person_docs(),
        classes_raising={"Person": WebuiClientError(500, "boom")},
    )
    browser = _make_browser(fake)
    index = await build_edge_index(browser)

    assert "Person" in index.errors
    assert "boom" in index.errors["Person"]
    assert len(index.nodes) == 2  # only Tasks


async def test_build_default_class_names_from_schema():
    """When class_names is None, browsable_classes() drives the fetch."""
    fake = _FakeTdb(schema=_task_person_schema(), docs_by_class=_task_person_docs())
    browser = _make_browser(fake)
    index = await build_edge_index(browser)

    assert len(index.nodes) == 4  # Task, Person, Tag (0 Tag docs though)
    assert index.type_counts == {"Task": 2, "Person": 2}


async def test_build_empty():
    """Empty schema → no nodes, no edges."""
    fake = _FakeTdb(schema=[], docs_by_class={})
    browser = _make_browser(fake)
    index = await build_edge_index(browser)
    assert len(index.nodes) == 0
    assert len(index.edges) == 0
    assert index.type_counts == {}


async def test_build_docs_without_at_id_skipped():
    """Documents missing @id are not added as nodes."""
    schema = [{"@type": "Class", "@id": "Ghost"}]
    docs = {"Ghost": [{"@type": "Ghost", "name": "no-id"}]}
    fake = _FakeTdb(schema=schema, docs_by_class=docs)
    browser = _make_browser(fake)
    index = await build_edge_index(browser)
    assert len(index.nodes) == 0


async def test_build_label_fallback():
    """doc_label falls back to @id last segment when no name/title."""
    schema = [
        {"@type": "Class", "@id": "Thing", "description": "xsd:string"}
    ]
    docs = {"Thing": [{"@id": "base/abc-123", "@type": "Thing"}]}
    fake = _FakeTdb(schema=schema, docs_by_class=docs)
    browser = _make_browser(fake)
    index = await build_edge_index(browser)
    assert index.nodes["base/abc-123"].label == "abc-123"


async def test_build_label_with_class_def():
    """Uses class_def.label_field for label extraction."""
    schema = [
        {
            "@type": "Class",
            "@id": "Thing",
            "title": "xsd:string",
            "@metadata": {"label_field": "title"},
        }
    ]
    docs = {"Thing": [{"@id": "Thing/1", "@type": "Thing", "title": "My Title"}]}
    fake = _FakeTdb(schema=schema, docs_by_class=docs)
    browser = _make_browser(fake)
    index = await build_edge_index(browser)
    assert index.nodes["Thing/1"].label == "My Title"


# ── neighborhood ────────────────────────────────────────────────────────────


def _line_graph_index() -> EdgeIndex:
    """A → B → C → D  (unidirectional)."""
    nodes = {
        "A": NodeInfo(id="A", label="Alice", type="Person"),
        "B": NodeInfo(id="B", label="Bob", type="Person"),
        "C": NodeInfo(id="C", label="Carol", type="Person"),
        "D": NodeInfo(id="D", label="Dan", type="Person"),
    }
    edges = [
        Edge(source="A", target="B", prop="knows"),
        Edge(source="B", target="C", prop="knows"),
        Edge(source="C", target="D", prop="knows"),
    ]
    return _make_index(nodes, edges)


def _star_graph_index() -> EdgeIndex:
    """A → B, A → C, A → D  (star)."""
    nodes = {
        "A": NodeInfo(id="A", label="A", type="X"),
        "B": NodeInfo(id="B", label="B", type="X"),
        "C": NodeInfo(id="C", label="C", type="X"),
        "D": NodeInfo(id="D", label="D", type="X"),
    }
    edges = [
        Edge(source="A", target="B", prop="ref"),
        Edge(source="A", target="C", prop="ref"),
        Edge(source="A", target="D", prop="ref"),
    ]
    return _make_index(nodes, edges)


def _bidirectional_index() -> EdgeIndex:
    """A ↔ B (2 directed edges)."""
    nodes = {
        "A": NodeInfo(id="A", label="A", type="X"),
        "B": NodeInfo(id="B", label="B", type="X"),
    }
    edges = [
        Edge(source="A", target="B", prop="friend"),
        Edge(source="B", target="A", prop="friend"),
    ]
    return _make_index(nodes, edges)


def _make_index(
    nodes: dict[str, NodeInfo], edges: list[Edge]
) -> EdgeIndex:
    """Construct a fully derived EdgeIndex from raw nodes/edges."""
    out_edges: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    in_edges: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    predicates: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    degree: dict[str, int] = {}

    for e in edges:
        out_edges[e.source].append(e)
        in_edges[e.target].append(e)
        predicates[e.prop] = predicates.get(e.prop, 0) + 1

    for nid, info in nodes.items():
        degree[nid] = len(out_edges[nid]) + len(in_edges[nid])
        type_counts[info.type] = type_counts.get(info.type, 0) + 1

    return EdgeIndex(
        nodes=nodes,
        edges=edges,
        out_edges=out_edges,
        in_edges=in_edges,
        predicates=predicates,
        type_counts=type_counts,
        degree=degree,
    )


def test_neighborhood_unknown_node():
    index = _line_graph_index()
    nodes, edges = index.neighborhood("Z")
    assert nodes == []
    assert edges == []


def test_neighborhood_hops_1_line():
    """From B at 1 hop: B, A, C + edges (knows) A→B, B→C."""
    index = _line_graph_index()
    nodes, edges = index.neighborhood("B", hops=1)

    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B", "C"}

    edge_triples = {(e.source, e.target, e.prop) for e in edges}
    assert edge_triples == {("A", "B", "knows"), ("B", "C", "knows")}


def test_neighborhood_hops_2_line():
    """From B at 2 hops: A, B, C, D + 3 edges."""
    index = _line_graph_index()
    nodes, edges = index.neighborhood("B", hops=2)

    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B", "C", "D"}
    assert len(edges) == 3


def test_neighborhood_hops_1_star():
    """From A: B, C, D."""
    index = _star_graph_index()
    nodes, edges = index.neighborhood("A", hops=1)

    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B", "C", "D"}
    assert len(edges) == 3


def test_neighborhood_hops_1_star_leaf():
    """From B: only A + the edge A→B (reverse direction)."""
    index = _star_graph_index()
    nodes, edges = index.neighborhood("B", hops=1)

    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B"}
    assert len(edges) == 1
    assert edges[0].source == "A"


def test_neighborhood_bidirectional_hops_1():
    """A ↔ B: 1 hop from A covers A and B, both edges."""
    index = _bidirectional_index()
    nodes, edges = index.neighborhood("A", hops=1)
    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B"}
    assert len(edges) == 2


# ── filter ──────────────────────────────────────────────────────────────────


def _multi_type_index() -> EdgeIndex:
    nodes = {
        "A": NodeInfo(id="A", label="Alice", type="Person"),
        "B": NodeInfo(id="B", label="Bob", type="Person"),
        "C": NodeInfo(id="C", label="Task One", type="Task"),
        "D": NodeInfo(id="D", label="Task Two", type="Task"),
    }
    edges = [
        Edge(source="A", target="C", prop="assigned"),
        Edge(source="B", target="D", prop="assigned"),
        Edge(source="A", target="B", prop="friend"),
    ]
    return _make_index(nodes, edges)


def test_filter_types_only():
    index = _multi_type_index()
    nodes, edges = index.filter(types={"Person"})
    node_ids = {n.id for n in nodes}
    assert node_ids == {"A", "B"}
    # Only A→B (friend) survives because both endpoints are Person
    assert len(edges) == 1
    assert edges[0].prop == "friend"


def test_filter_predicates_only():
    index = _multi_type_index()
    nodes, edges = index.filter(predicates={"assigned"})
    # No node filter → all nodes
    assert len(nodes) == 4
    # Only assigned edges
    assert len(edges) == 2
    assert all(e.prop == "assigned" for e in edges)


def test_filter_text_only():
    index = _multi_type_index()
    nodes, edges = index.filter(text="task")
    node_ids = {n.id for n in nodes}
    assert node_ids == {"C", "D"}
    # Edges only among surviving nodes → none (A,B not in set)
    assert len(edges) == 0


def test_filter_text_case_insensitive():
    index = _multi_type_index()
    nodes, _ = index.filter(text="ALICE")
    node_ids = {n.id for n in nodes}
    assert node_ids == {"A"}


def test_filter_combined():
    """Person nodes matching "bob" with friend edges."""
    index = _multi_type_index()
    nodes, edges = index.filter(
        types={"Person"}, predicates={"friend"}, text="bob"
    )
    node_ids = {n.id for n in nodes}
    assert node_ids == {"B"}
    # friend edge: A→B, but A is filtered out → no edges
    assert len(edges) == 0


def test_filter_combined_different():
    """Person nodes matching "ali" (Alice) → friend edge should be excluded
    because Bob is not in the matching node set."""
    index = _multi_type_index()
    nodes, edges = index.filter(
        types={"Person"}, predicates={"friend"}, text="ali"
    )
    node_ids = {n.id for n in nodes}
    assert node_ids == {"A"}
    # A→B has B not in set → excluded
    assert len(edges) == 0


def test_filter_no_constraints():
    index = _multi_type_index()
    nodes, edges = index.filter()
    assert len(nodes) == 4
    assert len(edges) == 3


# ── triples ─────────────────────────────────────────────────────────────────


def test_triples_all():
    index = _multi_type_index()
    page, total = index.triples()
    assert total == 3
    assert len(page) == 3  # all fit in default limit=50


def test_triples_pagination():
    index = _multi_type_index()
    page, total = index.triples(offset=1, limit=1)
    assert total == 3
    assert len(page) == 1


def test_triples_predicates_filter():
    index = _multi_type_index()
    page, total = index.triples(predicates={"friend"})
    assert total == 1
    assert page[0].prop == "friend"
    assert page[0].source_id == "A"
    assert page[0].target_id == "B"


def test_triples_source_types():
    index = _multi_type_index()
    page, total = index.triples(source_types={"Person"})
    # assigned: A→C, B→D; friend: A→B — all have Person source
    assert total == 3


def test_triples_target_types():
    index = _multi_type_index()
    page, total = index.triples(target_types={"Task"})
    # assigned: A→C, B→D — both target Task
    assert total == 2
    assert all(r.target_type == "Task" for r in page)


def test_triples_both_types():
    index = _multi_type_index()
    page, total = index.triples(source_types={"Person"}, target_types={"Person"})
    # Only friend: A→B
    assert total == 1
    assert page[0].prop == "friend"


def test_triples_text_filter():
    index = _multi_type_index()
    page, total = index.triples(text="alice")
    # Matches: assigned A→C, friend A→B
    assert total == 2


def test_triples_text_filter_target():
    index = _multi_type_index()
    page, total = index.triples(text="task")
    # Matches: assigned A→C (target C label "Task One"), assigned B→D
    assert total == 2


def test_triples_combined_filters():
    index = _multi_type_index()
    page, total = index.triples(
        predicates={"assigned"}, source_types={"Person"}, text="bob"
    )
    # Matches: assigned B→D (bob in source label)
    assert total == 1
    assert page[0].source_label == "Bob"
    assert page[0].target_id == "D"


def test_triples_empty_index():
    index = _make_index({}, [])
    page, total = index.triples()
    assert total == 0
    assert page == []


def test_triples_limit():
    index = _multi_type_index()
    page, total = index.triples(limit=2)
    assert total == 3
    assert len(page) == 2


# ── edge-case: derived structures on empty index ────────────────────────────


def test_derived_on_empty():
    index = _make_index({}, [])
    assert index.nodes == {}
    assert index.edges == []
    assert index.out_edges == {}
    assert index.in_edges == {}
    assert index.predicates == {}
    assert index.type_counts == {}
    assert index.degree == {}


# ── self-loop exclusion (via extract_edges) ─────────────────────────────────


async def test_build_self_loops_excluded():
    schema = [{"@type": "Class", "@id": "X", "name": "xsd:string"}]
    docs = {"X": [{"@id": "x/1", "@type": "X", "ref": "x/1"}]}
    fake = _FakeTdb(schema=schema, docs_by_class=docs)
    browser = _make_browser(fake)
    index = await build_edge_index(browser)
    assert len(index.edges) == 0
