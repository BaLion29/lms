"""Tests for GraphState — index build, filtering, focus mode, colours."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from firnline_webui.graph_index import Edge, EdgeIndex, NodeInfo, build_edge_index
from firnline_webui.state.graph import GraphState, _assign_colors, _build_legend

# ── Minimal fake TdbClient + Browser factory ─────────────────────────────────


class _FakeTdb:
    """Drop-in for firnline_core TdbClient with canned data."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        docs_by_class: dict[str, list[dict]] | None = None,
    ) -> None:
        self._schema = schema or []
        self._docs_by_class = docs_by_class or {}
        self.aclose_called = False

    async def get_schema(self, branch: str = "main") -> list[dict]:
        return self._schema

    async def get_documents(
        self, type_: str, branch: str = "main",
        skip: int | None = None, count: int | None = None,
    ) -> list[dict]:
        return self._docs_by_class.get(type_, [])

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        return {"@id": iri, "title": iri.rsplit("/", 1)[-1]}

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_browser(fake: _FakeTdb):
    from firnline_webui.clients import TdbBrowser
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)


def _schema() -> list[dict]:
    return [
        {"@type": "Class", "@id": "Person", "name": "xsd:string", "knows": "Person"},
        {"@type": "Class", "@id": "Task", "title": "xsd:string", "assignee": "Person"},
    ]


def _docs() -> dict[str, list[dict]]:
    return {
        "Person": [
            {"@id": "Person/alice", "@type": "Person", "name": "Alice", "knows": "Person/bob"},
            {"@id": "Person/bob", "@type": "Person", "name": "Bob"},
            {"@id": "Person/carol", "@type": "Person", "name": "Carol"},
        ],
        "Task": [
            {"@id": "Task/1", "@type": "Task", "title": "Write tests", "assignee": "Person/alice"},
            {"@id": "Task/2", "@type": "Task", "title": "Review", "assignee": "Person/bob"},
            {"@id": "Task/3", "@type": "Task", "title": "Ship it", "assignee": "Person/carol"},
        ],
    }


async def _drive_generator(state: GraphState, gen):
    """Manually drive an async/sync generator or plain coroutine."""
    import inspect

    if inspect.iscoroutine(gen):
        await gen
        return []

    results = []
    try:
        while True:
            if inspect.isasyncgen(gen):
                results.append(await gen.__anext__())
            else:
                results.append(gen.__next__())
    except StopIteration:
        pass
    except StopAsyncIteration:
        pass
    return results


# ── Colour helpers ───────────────────────────────────────────────────────────


def test_assign_colors_deterministic():
    types = ["Task", "Person", "Tag"]
    mapping = _assign_colors(types)
    assert mapping["Task"] != mapping["Person"]
    assert mapping["Person"] != mapping["Tag"]
    # second call gives same mapping
    mapping2 = _assign_colors(types)
    assert mapping == mapping2


def test_assign_colors_uses_palette():
    types = ["A"]
    mapping = _assign_colors(types)
    assert mapping["A"].startswith("#")


def test_build_legend_filters_by_index():
    colors = {"Person": "#aaa", "Task": "#bbb", "Ghost": "#ccc"}
    idx = _make_index(
        nodes={
            "A": NodeInfo(id="A", label="A", type="Person"),
            "B": NodeInfo(id="B", label="B", type="Task"),
        },
        edges=[],
    )
    legend = _build_legend(colors, idx)
    assert len(legend) == 2
    labels = {l["label"] for l in legend}
    assert labels == {"Person", "Task"}


def test_build_legend_empty_index():
    legend = _build_legend({"X": "#000"}, None)
    assert legend == []


# ── Helper: build a minimal EdgeIndex ────────────────────────────────────────


def _make_index(
    nodes: dict[str, NodeInfo], edges: list[Edge]
) -> EdgeIndex:
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


def _sample_index() -> EdgeIndex:
    nodes = {
        "Person/alice": NodeInfo(id="Person/alice", label="Alice", type="Person"),
        "Person/bob": NodeInfo(id="Person/bob", label="Bob", type="Person"),
        "Person/carol": NodeInfo(id="Person/carol", label="Carol", type="Person"),
        "Task/1": NodeInfo(id="Task/1", label="Write tests", type="Task"),
        "Task/2": NodeInfo(id="Task/2", label="Review", type="Task"),
        "Task/3": NodeInfo(id="Task/3", label="Ship it", type="Task"),
    }
    edges = [
        Edge(source="Task/1", target="Person/alice", prop="assignee"),
        Edge(source="Task/2", target="Person/bob", prop="assignee"),
        Edge(source="Task/3", target="Person/carol", prop="assignee"),
        Edge(source="Person/alice", target="Person/bob", prop="knows"),
    ]
    return _make_index(nodes, edges)


# ── Load + graph_data ────────────────────────────────────────────────────────


async def test_load_builds_index_and_graph_data():
    """After load, _index is populated and nodes/links are set."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)

    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state._index is not None
    assert state.loaded is True
    assert len(state.nodes) > 0
    assert len(state.links) > 0
    # Nodes have colour assigned
    assert "color" in state.nodes[0]
    assert state.nodes[0]["color"].startswith("#")
    # Type colors are set
    assert len(state._type_colors) >= 2


# ── Multi-class filter ───────────────────────────────────────────────────────


async def test_type_filter_toggle():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # Toggle: only Person
    gen = state.toggle_type("Person")
    await _drive_generator(state, gen)

    assert set(state.active_types) == {"Person"}
    node_types = {n["group"] for n in state.nodes}
    assert node_types == {"Person"}
    # Only "knows" edge between Persons
    assert len(state.links) == 1
    assert state.links[0]["prop"] == "knows"

    # Toggle again: deselect
    gen = state.toggle_type("Person")
    await _drive_generator(state, gen)
    assert set(state.active_types) == set()
    assert len(state.nodes) == 6  # all nodes back


async def test_type_filter_multiple():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_type("Person")
    await _drive_generator(state, gen)
    gen = state.toggle_type("Task")
    await _drive_generator(state, gen)

    assert set(state.active_types) == {"Person", "Task"}
    assert len(state.nodes) == 6


# ── Predicate filter ─────────────────────────────────────────────────────────


async def test_predicate_filter():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_predicate("knows")
    await _drive_generator(state, gen)

    assert set(state.active_predicates) == {"knows"}
    assert all(e["prop"] == "knows" for e in state.links)
    assert len(state.links) == 1


# ── Search text filter ───────────────────────────────────────────────────────


async def test_search_filter():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.set_search("alice")
    await _drive_generator(state, gen)

    node_ids = {n["id"] for n in state.nodes}
    assert node_ids == {"Person/alice"}
    # No edges with filtered node set (only alice, no edges among single node)
    assert len(state.links) == 0


# ── Combined filters ─────────────────────────────────────────────────────────


async def test_combined_filters():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_type("Task")
    await _drive_generator(state, gen)
    gen = state.toggle_predicate("assignee")
    await _drive_generator(state, gen)
    gen = state.set_search("write")
    await _drive_generator(state, gen)

    node_ids = {n["id"] for n in state.nodes}
    assert node_ids == {"Task/1"}
    # assignee Task/1→Person/alice, but alice not in node set → 0 edges
    assert len(state.links) == 0


# ── Node cap truncation ──────────────────────────────────────────────────────


async def test_node_cap_truncation_warning():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # All 6 nodes loaded, no truncation yet
    assert len(state.nodes) == 6
    assert state.truncated is False

    # Cap at 2 — should truncate
    gen = state.set_max_nodes("2")
    await _drive_generator(state, gen)
    assert state.max_nodes == 2
    assert state.truncated is True
    assert state.total_filtered == 6
    assert len(state.nodes) == 2

    # Raise cap
    gen = state.set_max_nodes("1000")
    await _drive_generator(state, gen)
    assert state.max_nodes == 1000
    assert state.truncated is False
    assert len(state.nodes) == 6


async def test_node_cap_truncation_false_when_under_limit():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]
    state.max_nodes = 500

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state.truncated is False
    assert state.total_filtered == 6
    assert len(state.nodes) == 6


# ── Focus mode ───────────────────────────────────────────────────────────────


async def test_focus_mode_enter_exit():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

        # Select a node first (sets focus_node_id etc.)
        gen = state.select_node("Person/alice")
        await _drive_generator(state, gen)

    assert state.focus_node_id == "Person/alice"
    assert state.focus_node_label == "Alice"
    assert state.focus_node_type == "Person"
    assert state.focus_node_degree > 0  # alice is referenced by Task/1 + knows Bob

    # Enter focus mode
    gen = state.focus_current()
    await _drive_generator(state, gen)
    assert state.is_focused is True
    assert state.focus_hops == 1
    # Should show alice + 1-hop neighbours
    node_ids = {n["id"] for n in state.nodes}
    assert "Person/alice" in node_ids
    # 1-hop includes Bob, Task/1, knows edge + assignee edge
    assert len(node_ids) >= 2

    # Change hops
    gen = state.set_focus_hops("2")
    await _drive_generator(state, gen)
    assert state.focus_hops == 2

    # Exit focus
    gen = state.exit_focus()
    await _drive_generator(state, gen)
    assert state.is_focused is False
    # All nodes back
    assert len(state.nodes) == 6


async def test_focus_mode_keep_filters_disabled():
    """When focus mode is entered, existing filters don't affect the view."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

        # Apply a type filter first
        gen = state.toggle_type("Task")
        await _drive_generator(state, gen)
        assert all(n["group"] == "Task" for n in state.nodes)

        # Select "Person/alice" and focus — its neighborhood should show Person
        # nodes too even though Task filter is active
        gen = state.select_node("Person/alice")
        await _drive_generator(state, gen)
        gen = state.focus_current()
        await _drive_generator(state, gen)

    node_ids = {n["id"] for n in state.nodes}
    # Should include Person/alice and its neighbours, not just Tasks
    assert "Person/alice" in node_ids

    # Exit focus — filters should reapply
    gen = state.exit_focus()
    await _drive_generator(state, gen)
    # Back to Task-only view
    assert all(n["group"] == "Task" for n in state.nodes)


# ── Type counts + predicate list computed vars ───────────────────────────────


async def test_type_counts_computed_var():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    tcl = state.type_counts_list
    assert len(tcl) == 2
    types = {d["type"] for d in tcl}
    assert types == {"Person", "Task"}

    pl = state.predicate_list
    assert len(pl) == 2  # assignee, knows
    props = {p["prop"] for p in pl}
    assert props == {"assignee", "knows"}


async def test_legend_items_computed_var():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    legend = state.legend_items
    assert len(legend) == 2
    labels = {l["label"] for l in legend}
    assert labels == {"Person", "Task"}
    assert all("color" in l for l in legend)


# ── Index errors ─────────────────────────────────────────────────────────────


async def test_index_errors_stored():
    """Per-class errors from build_edge_index are stored."""
    fake = _FakeTdb(schema=_schema(), docs_by_class={"Task": []})
    browser = _make_browser(fake)

    state = GraphState()  # type: ignore[call-arg]
    with patch(
        "firnline_webui.state.graph.build_edge_index",
        return_value=_sample_index(),
    ):
        state._index = _sample_index()
        # Manually set errors
        state.index_errors = ["Person: fetch failed"]
        gen = state.dismiss_index_errors()
        await _drive_generator(state, gen)
        assert state.index_errors == []


# ── Load idempotent / caching ────────────────────────────────────────────────


async def test_load_if_needed_only_loads_once():
    """load_if_needed triggers load when not loaded, skips when loaded."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]
    assert not state.loaded

    # Simulate Reflex event chaining: load_if_needed returns GraphState.load
    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state.loaded is True
    first_nodes = len(state.nodes)

    # Second call to load_if_needed: loaded is True → returns None (no chain)
    gen2 = state.load_if_needed()
    await _drive_generator(state, gen2)
    # load was NOT re-run
    assert state.loaded is True
    assert len(state.nodes) == first_nodes


# ── Deterministic colours on reload ──────────────────────────────────────────


async def test_colors_stable_across_loads():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    first_colors = {n["id"]: n["color"] for n in state.nodes}
    assert len(set(first_colors.values())) >= 2  # at least two different colours

    # Reload (reset and load again)
    state.loaded = False
    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    second_colors = {n["id"]: n["color"] for n in state.nodes}
    assert first_colors == second_colors  # stable across reloads


# ── select_node updates focus metadata ───────────────────────────────────────


async def test_select_node_populates_focus_metadata():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

        gen = state.select_node("Person/bob")
        await _drive_generator(state, gen)

    assert state.focus_node_id == "Person/bob"
    assert state.focus_node_label == "Bob"
    assert state.focus_node_type == "Person"
    assert state.focus_node_degree > 0
    assert state.selected_doc is not None
    assert state.selected_json != ""


async def test_select_node_unknown_still_sets_basic_info():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    # Load but the index doesn't have the node clicked
    state._index = _sample_index()

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        gen = state.select_node("Nonexistent/xyz")
        await _drive_generator(state, gen)

    assert state.focus_node_id == "Nonexistent/xyz"
    assert state.focus_node_type == ""
    assert state.focus_node_degree == 0


async def test_clear_selection_resets_doc():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]

    state.selected_doc = {"@id": "x"}
    state.selected_json = "{}"

    gen = state.clear_selection()
    await _drive_generator(state, gen)

    assert state.selected_doc is None
    assert state.selected_json == ""


async def test_focus_current_noop_without_selection():
    """focus_current does nothing if no node is selected."""
    state = GraphState()  # type: ignore[call-arg]
    state._index = _sample_index()
    state.is_focused = False
    state.focus_node_id = ""

    gen = state.focus_current()
    await _drive_generator(state, gen)

    assert state.is_focused is False


async def test_set_view_triggers_load_when_graph_and_not_loaded():
    """set_view('graph') chains to load when not yet loaded."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = GraphState()  # type: ignore[call-arg]
    state.loaded = False

    with patch("firnline_webui.state.graph.make_tdb_browser", return_value=browser):
        # Simulate Reflex chaining: set_view returns GraphState.load
        gen = state.load()
        await _drive_generator(state, gen)
        state.view = "graph"

    assert state.loaded is True
    assert state.view == "graph"


async def test_set_view_no_load_when_list():
    state = GraphState()  # type: ignore[call-arg]
    state.loaded = False

    gen = state.set_view("list")
    await _drive_generator(state, gen)

    assert state.view == "list"
    assert state.loaded is False


async def test_set_focus_hops_accepts_any_positive():
    """set_focus_hops accepts any int >= 1."""
    state = GraphState()  # type: ignore[call-arg]
    state._index = _sample_index()
    state.focus_node_id = "Person/alice"
    state.is_focused = True
    state.focus_hops = 1
    state._recompute_display()

    gen = state.set_focus_hops("5")
    await _drive_generator(state, gen)

    assert state.focus_hops == 5  # accepted (>= 1)


async def test_set_focus_hops_invalid_ignored():
    state = GraphState()  # type: ignore[call-arg]
    state._index = _sample_index()
    state.focus_node_id = "Person/alice"
    state.is_focused = True
    state.focus_hops = 1
    state._recompute_display()

    gen = state.set_focus_hops("0")
    await _drive_generator(state, gen)

    assert state.focus_hops == 1  # unchanged (0 is < 1)


async def test_set_max_nodes_invalid_ignored():
    state = GraphState()  # type: ignore[call-arg]
    state._index = _sample_index()
    state.max_nodes = 500
    state._recompute_display()

    gen = state.set_max_nodes("abc")
    await _drive_generator(state, gen)

    assert state.max_nodes == 500  # unchanged


# ── Fallback error handling (Fix 2) ───────────────────────────────────────────


async def test_load_catches_generic_exception():
    """load() catches plain Exception from build_edge_index and sets error."""
    state = GraphState()  # type: ignore[call-arg]

    with patch(
        "firnline_webui.state.graph.build_edge_index",
        side_effect=RuntimeError("unexpected graph failure"),
    ):
        gen = state.load()
        await _drive_generator(state, gen)

    assert not state.loaded
    assert state.error != ""
    assert "unexpected graph failure" in state.error
    assert not state.loading
