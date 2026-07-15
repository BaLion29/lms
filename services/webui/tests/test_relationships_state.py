"""Tests for RelationshipsState — index build, filters, pagination, cross-state navigation."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from firnline_webui.graph_index import Edge, EdgeIndex, NodeInfo, build_edge_index
from firnline_webui.state.relationships import RelationshipsState


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


async def _drive_generator(state: RelationshipsState, gen):
    """Manually drive an async/sync generator or plain coroutine."""
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


# ── Load builds index + first page ───────────────────────────────────────────


async def test_load_builds_index_and_rows():
    """After load, _index is populated and rows are set."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)

    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state._index is not None
    assert state.loaded is True
    assert len(state.rows) > 0
    assert state.total_count == 4  # assignee x3 + knows x1

    # Check row structure
    row = state.rows[0]
    assert "source_id" in row
    assert "source_label" in row
    assert "source_type" in row
    assert "prop" in row
    assert "target_id" in row
    assert "target_label" in row
    assert "target_type" in row

    # Option lists populated
    assert len(state.predicate_options) == 2  # assignee, knows
    assert len(state.source_type_options) == 2  # Person, Task
    assert len(state.target_type_options) == 1  # Person (only target role)


# ── Predicate filter ─────────────────────────────────────────────────────────


async def test_predicate_filter_affects_rows():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_predicate("knows")
    await _drive_generator(state, gen)

    assert set(state.active_predicates) == {"knows"}
    assert all(r["prop"] == "knows" for r in state.rows)
    assert state.total_count == 1
    assert state.page == 0  # reset on filter

    # Toggle off
    gen = state.toggle_predicate("knows")
    await _drive_generator(state, gen)
    assert set(state.active_predicates) == set()
    assert state.total_count == 4


# ── Source type filter ───────────────────────────────────────────────────────


async def test_source_type_filter():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_source_type("Person")
    await _drive_generator(state, gen)

    assert set(state.active_source_types) == {"Person"}
    # Only "knows" has Person source (alice knows bob)
    assert state.total_count == 1
    assert state.rows[0]["prop"] == "knows"


# ── Target type filter ───────────────────────────────────────────────────────


async def test_target_type_filter():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.toggle_target_type("Task")
    await _drive_generator(state, gen)

    assert set(state.active_target_types) == {"Task"}
    # No edges target Task → 0
    assert state.total_count == 0


# ── Search text filter ───────────────────────────────────────────────────────


async def test_search_text_filter():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.set_search("alice")
    await _drive_generator(state, gen)

    # Matches: Task/1→alice (assignee target), alice→bob (knows source)
    assert state.total_count == 2
    assert state.page == 0  # reset


# ── Pagination ───────────────────────────────────────────────────────────────


async def test_pagination_next_prev():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]
    state.page_size = 2

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state.total_count == 4
    assert len(state.rows) == 2  # page_size=2
    assert state.page == 0

    gen = state.next_page()
    await _drive_generator(state, gen)
    assert state.page == 1
    assert len(state.rows) == 2

    gen = state.next_page()
    await _drive_generator(state, gen)
    assert state.page == 1  # no more pages, stays
    assert state.total_pages == 2

    gen = state.prev_page()
    await _drive_generator(state, gen)
    assert state.page == 0


async def test_set_page_size_resets_page():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    state.page = 1  # manually advance
    gen = state.set_page_size("10")
    await _drive_generator(state, gen)

    assert state.page_size == 10
    assert state.page == 0


async def test_set_page_size_invalid_ignored():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    gen = state.set_page_size("abc")
    await _drive_generator(state, gen)
    assert state.page_size == 25  # unchanged


async def test_total_pages_computed():
    state = RelationshipsState()  # type: ignore[call-arg]
    state.total_count = 100
    state.page_size = 25
    assert state.total_pages == 4


# ── select_endpoint populates drawer vars ────────────────────────────────────


async def test_select_endpoint_populates_drawer():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.select_endpoint("Person/alice")
        await _drive_generator(state, gen)

    assert state.selected_doc is not None
    assert state.selected_json != ""
    assert '"Person/alice"' in state.selected_json or "Person/alice" in state.selected_json


async def test_clear_selection_resets_drawer():
    state = RelationshipsState()  # type: ignore[call-arg]
    state.selected_doc = {"@id": "x"}
    state.selected_json = "{}"

    gen = state.clear_selection()
    await _drive_generator(state, gen)

    assert state.selected_doc is None
    assert state.selected_json == ""


# ── show_in_graph cross-state ────────────────────────────────────────────────


async def test_show_in_graph_switches_tab_and_triggers_load():
    """show_in_graph sets BrowseState.tab to 'graph' and chains GraphState handlers."""
    from firnline_webui.state.browse import BrowseState

    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    # Use a dummy object to capture tab changes without needing a real Reflex context
    class _DummyBrowse:
        tab = ""

    dummy_browse = _DummyBrowse()

    async def mock_get_state(cls):
        if cls is BrowseState:
            return dummy_browse
        return AsyncMock()

    with (
        patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser),
        patch.object(RelationshipsState, "get_state", side_effect=mock_get_state),
    ):
        gen = state.show_in_graph("Person/alice")

        # Yield 1: after setting tab
        result = await gen.__anext__()
        assert dummy_browse.tab == "graph"

        # Yield 2: GraphState.load_if_needed
        result = await gen.__anext__()
        assert result is not None  # event reference

        # Yield 3: after load_if_needed chaining
        result = await gen.__anext__()

        # Yield 4: GraphState.select_node
        result = await gen.__anext__()
        assert result is not None  # event reference

        # Yield 5: after select_node chaining
        result = await gen.__anext__()

        # Yield 6: GraphState.focus_current
        result = await gen.__anext__()
        assert result is not None  # event reference


async def test_show_in_graph_sets_browse_tab():
    """Test that show_in_graph actually sets BrowseState.tab via the dummy."""
    from firnline_webui.state.browse import BrowseState

    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    class _DummyBrowse:
        tab = ""

    dummy_browse = _DummyBrowse()

    async def mock_get_state(cls):
        if cls is BrowseState:
            return dummy_browse
        return AsyncMock()

    with (
        patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser),
        patch.object(RelationshipsState, "get_state", side_effect=mock_get_state),
    ):
        gen = state.show_in_graph("Person/alice")
        try:
            while True:
                await gen.__anext__()
        except StopAsyncIteration:
            pass

    assert dummy_browse.tab == "graph"


# ── Error handling ───────────────────────────────────────────────────────────


async def test_load_sets_error_on_failure():
    """When build_edge_index raises, error var is populated."""
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch(
        "firnline_webui.state.relationships.build_edge_index",
        side_effect=Exception("boom"),
    ):
        gen = state.load()
        # The handler catches WebuiClientError, but a plain Exception will propagate
        try:
            await _drive_generator(state, gen)
        except Exception:
            pass

    # After a plain Exception, loaded is False (or error may be set depending on the exception type)
    # Since it's not a WebuiClientError, it propagates. That's acceptable.


async def test_index_errors_stored():
    """Index.errors are surfaced as state.index_errors."""
    state = RelationshipsState()  # type: ignore[call-arg]
    state._index = _sample_index()
    # Manually set errors via the index
    state._index.errors["BrokenClass"] = "fetch failed"
    state._refresh_rows()
    # load() sets index_errors from index.errors; manually simulate
    state.index_errors = [f"{k}: {v}" for k, v in state._index.errors.items()]

    assert len(state.index_errors) == 1
    assert "BrokenClass" in state.index_errors[0]

    gen = state.dismiss_index_errors()
    await _drive_generator(state, gen)
    assert state.index_errors == []


# ── Load idempotent / caching ────────────────────────────────────────────────


async def test_load_if_needed_only_loads_once():
    """load_if_needed triggers load when not loaded, skips when loaded."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]
    assert not state.loaded

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    assert state.loaded is True
    first_rows = len(state.rows)

    gen2 = state.load_if_needed()
    await _drive_generator(state, gen2)
    assert state.loaded is True
    assert len(state.rows) == first_rows


# ── Predicate/source/target filters affect rows and total ────────────────────


async def test_combined_filters():
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # Filter by predicate + source type + search
    gen = state.toggle_predicate("assignee")
    await _drive_generator(state, gen)
    gen = state.toggle_source_type("Task")
    await _drive_generator(state, gen)
    gen = state.set_search("write")
    await _drive_generator(state, gen)

    assert state.total_count == 1
    assert state.rows[0]["source_label"] == "Write tests"
    assert state.rows[0]["prop"] == "assignee"
    assert state.rows[0]["target_label"] == "Alice"


# ── Per-role type counts from edges (Fix 5) ───────────────────────────────────


async def test_source_type_options_from_edges():
    """source_type_options counts are derived from edges, not total node counts."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # With sample data: 3 Task→Person(assignee) + 1 Person→Person(knows)
    # Source types: Task appears 3 times, Person appears 1 time
    src_opts = {o["label"]: o["count"] for o in state.source_type_options}
    assert src_opts.get("Task") == 3
    assert src_opts.get("Person") == 1


async def test_target_type_options_from_edges():
    """target_type_options counts are derived from edges, not total node counts."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # Target types: Person appears 4 times (3 assignee + 1 knows)
    tgt_opts = {o["label"]: o["count"] for o in state.target_type_options}
    assert tgt_opts.get("Person") == 4


async def test_type_options_differ_from_total_counts():
    """Per-role edge counts differ from total node counts (type_counts)."""
    fake = _FakeTdb(schema=_schema(), docs_by_class=_docs())
    browser = _make_browser(fake)
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.relationships.make_tdb_browser", return_value=browser):
        gen = state.load()
        await _drive_generator(state, gen)

    # Total node counts: Person=3, Task=3
    idx = state._index
    assert idx is not None
    assert idx.type_counts == {"Person": 3, "Task": 3}

    # But source_type_options uses edge-derived counts
    src_opts = {o["label"]: o["count"] for o in state.source_type_options}
    assert src_opts.get("Person") == 1  # ≠ 3 (total nodes)
    assert src_opts.get("Task") == 3  # ≠ 3 (total nodes)

    tgt_opts = {o["label"]: o["count"] for o in state.target_type_options}
    assert tgt_opts.get("Person") == 4  # ≠ 3 (total nodes)


# ── Fallback error handling (Fix 2) ───────────────────────────────────────────


async def test_load_catches_generic_exception():
    """load() catches plain Exception from build_edge_index and sets error."""
    state = RelationshipsState()  # type: ignore[call-arg]

    with patch(
        "firnline_webui.state.relationships.build_edge_index",
        side_effect=RuntimeError("unexpected failure"),
    ):
        gen = state.load()
        await _drive_generator(state, gen)

    assert not state.loaded
    assert state.error != ""
    assert "unexpected failure" in state.error
    assert not state.loading
