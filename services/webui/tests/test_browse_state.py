"""Tests for BrowseState — search filtering, count loading, tab var."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from firnline_core.tdb import TdbError
from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.state.browse import BrowseState


# ---------------------------------------------------------------------------
# Fake TdbBrowser building blocks
# ---------------------------------------------------------------------------


class _FakeTdb:
    """Drop-in for firnline_core TdbClient with configurable behaviour."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        modules: list[dict] | None = None,
        counts: dict[str, int] | None = None,
        raise_tdb_error_on: str | None = None,
        tdb_error: tuple[int, str] = (500, "boof"),
    ) -> None:
        if schema is None:
            schema = [
                {
                    "@type": "Class",
                    "@id": "Person",
                    "name": "xsd:string",
                    "age": "xsd:integer",
                },
                {
                    "@type": "Class",
                    "@id": "Task",
                    "title": "xsd:string",
                    "done": "xsd:boolean",
                },
            ]
        if modules is None:
            modules = [
                {
                    "@id": "SchemaModule/base",
                    "name": "base",
                    "version": "1.0",
                    "exports": ["Person", "Task"],
                },
            ]
        if counts is None:
            counts = {"Person": 128, "Task": 42}
        self._schema = schema
        self._modules = modules
        self._counts = counts
        self._raise_tdb_error_on = raise_tdb_error_on
        self._tdb_error = tdb_error
        self.aclose_called = False
        self._count_calls: list[str] = []

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_tdb_error_on == "schema":
            raise TdbError(*self._tdb_error)
        return self._schema

    async def get_documents(self, type_: str, branch: str = "main",
                            skip: int | None = None, count: int | None = None) -> list[dict]:
        if type_ == "SchemaModule" and self._modules is not None:
            return self._modules
        return []

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        return {"@id": iri}

    async def count_documents(self, type_: str, branch: str = "main") -> int:
        self._count_calls.append(type_)
        if isinstance(self._counts, dict) and type_ in self._counts:
            return self._counts[type_]
        raise TdbError(500, f"count failed for {type_}")

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_fake_browser(fake_tdb: _FakeTdb) -> TdbBrowser:
    """Construct a TdbBrowser backed by *_fake_tdb*."""
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake_tdb)


async def _drive_handler(gen):
    """Drive an async generator handler to completion, returning the final state."""
    try:
        while True:
            val = await gen.__anext__()
            # If the generator yields another event handler, drive that too
            if callable(val) or (hasattr(val, '__call__')):
                continue
    except StopAsyncIteration:
        pass


# ---------------------------------------------------------------------------
# Tab default
# ---------------------------------------------------------------------------


def test_tab_default():
    """BrowseState.tab defaults to 'classes'."""
    state = BrowseState()  # type: ignore[call-arg]
    assert state.tab == "classes"


# ---------------------------------------------------------------------------
# Search filtering
# ---------------------------------------------------------------------------


def test_search_filtering_exact_match():
    """filtered_groups includes only matching classes."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"], "other": ["Event"]}
    state.search_query = "Person"

    fg = state.filtered_groups
    assert "base" in fg
    assert fg["base"] == ["Person"]
    assert "other" not in fg


def test_search_filtering_case_insensitive():
    """filtered_groups is case-insensitive."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}
    state.search_query = "person"

    fg = state.filtered_groups
    assert "base" in fg
    assert fg["base"] == ["Person"]


def test_search_filtering_no_match_hides_all():
    """filtered_groups is empty when nothing matches."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}
    state.search_query = "zzz_nonexistent"

    assert state.filtered_groups == {}


def test_search_filtering_empty_query_returns_all():
    """filtered_groups returns all groups when query is empty."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}
    state.search_query = ""

    assert state.filtered_groups == state.groups


# ---------------------------------------------------------------------------
# Module key ordering
# ---------------------------------------------------------------------------


def test_filtered_module_keys_other_last():
    """'other' module is always sorted last."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"zebra": ["A"], "apple": ["B"], "other": ["C"]}

    keys = state.filtered_module_keys
    assert keys == ["apple", "zebra", "other"]


def test_filtered_module_keys_no_other():
    """Without 'other', keys are just sorted alphabetically."""
    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"zebra": ["A"], "apple": ["B"]}

    assert state.filtered_module_keys == ["apple", "zebra"]


def test_search_active():
    """search_active is True only when search_query is non-empty."""
    state = BrowseState()  # type: ignore[call-arg]
    assert not state.search_active
    state.search_query = "x"
    assert state.search_active
    state.search_query = "   "
    assert not state.search_active


def test_has_any_class():
    """has_any_class reflects whether groups contain classes."""
    state = BrowseState()  # type: ignore[call-arg]
    assert not state.has_any_class
    state.groups = {"mod": ["A"]}
    assert state.has_any_class
    state.groups = {"mod": []}
    assert not state.has_any_class


# ---------------------------------------------------------------------------
# Count loading — success
# ---------------------------------------------------------------------------


async def test_load_counts_success():
    """load_counts() fetches counts for all classes in groups."""
    fake = _FakeTdb(counts={"Person": 128, "Task": 42})
    browser = _make_fake_browser(fake)

    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser):
        await _drive_handler(state.load_counts())

    assert state.class_counts == {"Person": "128", "Task": "42"}
    assert fake.aclose_called
    assert not state.counts_loading


# ---------------------------------------------------------------------------
# Count loading — per-class failure is graceful
# ---------------------------------------------------------------------------


async def test_load_counts_per_class_failure_graceful():
    """When count_documents fails for a class, its count stays ''."""
    fake = _FakeTdb(counts={"Person": 128})  # Task will fail via TdbError
    browser = _make_fake_browser(fake)

    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser):
        await _drive_handler(state.load_counts())

    assert state.class_counts["Person"] == "128"
    assert state.class_counts.get("Task", "") == ""
    assert fake.aclose_called


# ---------------------------------------------------------------------------
# Count loading — all fail
# ---------------------------------------------------------------------------


async def test_load_counts_all_failure():
    """When all count_documents calls fail, per-class entries are empty strings."""
    fake = _FakeTdb(counts={})  # all raise
    browser = _make_fake_browser(fake)

    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {"base": ["Person", "Task"]}

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser):
        await _drive_handler(state.load_counts())

    # Each class gets an entry but the count string is empty (graceful)
    assert state.class_counts == {"Person": "", "Task": ""}
    assert fake.aclose_called


# ---------------------------------------------------------------------------
# Count loading — no classes (early return)
# ---------------------------------------------------------------------------


async def test_load_counts_no_classes():
    """load_counts returns immediately when groups is empty."""
    fake = _FakeTdb()
    browser = _make_fake_browser(fake)

    state = BrowseState()  # type: ignore[call-arg]
    state.groups = {}

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser):
        await _drive_handler(state.load_counts())

    assert state.class_counts == {}


# ---------------------------------------------------------------------------
# load() triggers load_counts
# ---------------------------------------------------------------------------


async def test_load_triggers_load_counts():
    """After load() + load_counts() complete, class_counts is populated."""
    fake = _FakeTdb(counts={"Person": 128, "Task": 42})
    browser = _make_fake_browser(fake)

    state = BrowseState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser):
        # Run load to completion — it chains to load_counts
        await _drive_handler(state.load())

    # Groups populated from the schema + modules
    assert "Person" in state.groups.get("base", [])
    assert fake.aclose_called

    # Now drive load_counts through a fresh browser
    fake2 = _FakeTdb(counts={"Person": 128, "Task": 42})
    browser2 = _make_fake_browser(fake2)

    with patch("firnline_webui.state.browse.make_tdb_browser", return_value=browser2):
        await _drive_handler(state.load_counts())

    assert state.class_counts == {"Person": "128", "Task": "42"}
    assert not state.counts_loading


# ============================================================================
# BrowseClassState tests — server/hybrid pagination, sort, search, references
# ============================================================================

from types import SimpleNamespace  # noqa: E402

from firnline_webui.state.browse import BrowseClassState  # noqa: E402
from firnline_webui.state.browse_helpers import (  # noqa: E402
    _compute_references,
    _is_known_ref,
    _row_matches,
    _sort_key,
)


def _mock_router(state, class_name: str):
    """Set up a mock router on *state* so load() can read the class_name param."""
    mock = SimpleNamespace()
    mock_page = SimpleNamespace()
    mock_page.params = {"class_name": class_name}
    mock.page = mock_page
    object.__setattr__(state, "router", mock)


class _FakeClassTdb:
    """Drop-in for firnline_core TdbClient with per-type documents."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        counts: dict[str, int] | None = None,
        docs: dict[str, list[dict]] | None = None,
        single_doc: dict | None = None,
        raise_tdb_error_on: str | None = None,
        tdb_error: tuple[int, str] = (500, "boof"),
    ) -> None:
        if schema is None:
            schema = [
                {
                    "@type": "Class",
                    "@id": "Person",
                    "name": "xsd:string",
                    "age": "xsd:integer",
                },
            ]
        if counts is None:
            counts = {}
        if docs is None:
            docs = {}
        if single_doc is None:
            single_doc = {"@id": "doc/1", "name": "Test"}
        self._schema = schema
        self._counts = counts
        self._docs = docs
        self._single_doc = single_doc
        self._raise_tdb_error_on = raise_tdb_error_on
        self._tdb_error = tdb_error
        self.aclose_called = False
        self.get_docs_calls: list[dict] = []

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_tdb_error_on == "schema":
            raise TdbError(*self._tdb_error)
        return self._schema

    async def get_documents(
        self,
        type_: str,
        branch: str = "main",
        skip: int | None = None,
        count: int | None = None,
    ) -> list[dict]:
        if self._raise_tdb_error_on == "get_documents":
            raise TdbError(*self._tdb_error)
        self.get_docs_calls.append({"type_": type_, "skip": skip, "count": count})
        doc_list = self._docs.get(type_, [])
        if skip is not None and count is not None:
            return doc_list[skip : skip + count]
        if skip is not None:
            return doc_list[skip:]
        if count is not None:
            return doc_list[:count]
        return doc_list

    async def count_documents(self, type_: str, branch: str = "main") -> int:
        if self._raise_tdb_error_on == "count":
            raise TdbError(*self._tdb_error)
        if type_ in self._counts:
            return self._counts[type_]
        return 0

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        if self._raise_tdb_error_on == "get_document":
            raise TdbError(*self._tdb_error)
        return {**self._single_doc, "@id": iri}

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_browser(fake: _FakeClassTdb) -> TdbBrowser:
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)


async def _drive(gen):
    """Drive an async generator handler, executing chained handlers.

    When a handler yields another event handler (as an EventSpec), extract
    the handler function and drive it with the state instance as self.
    """
    try:
        while True:
            val = await gen.__anext__()
            # Reflex yields EventSpec for chained event handlers
            if hasattr(val, "handler") and hasattr(val.handler, "fn"):
                fn = val.handler.fn
                # fn is an unbound method; bind it to the state instance
                if hasattr(fn, "__self__") and fn.__self__ is not None:
                    await _drive(fn())
                else:
                    continue
            elif callable(val):
                await _drive(val())
            elif hasattr(val, "__call__"):
                continue
    except StopAsyncIteration:
        pass


def _make_docs(n: int) -> list[dict]:
    return [{"@id": f"Person/{i}", "@type": "Person", "name": f"Name {i}", "age": 20 + i} for i in range(n)]


# -- _sort_key / _row_matches -------------------------------------------------


def test_sort_key_normalizes_case():
    assert _sort_key("Alice") == "alice"
    assert _sort_key("BOB") == "bob"
    assert _sort_key("") == ""


def test_row_matches_exact():
    row = {"@id": "A", "name": "Alice", "title": "Engineer"}
    assert _row_matches(row, "Alice")
    assert _row_matches(row, "alice")
    assert not _row_matches(row, "Bob")


def test_row_matches_substring():
    row = {"@id": "A", "name": "Alice", "title": "Engineer"}
    assert _row_matches(row, "lic")
    assert _row_matches(row, "ngin")


def test_row_matches_empty_query():
    assert _row_matches({"name": "X"}, "")
    assert _row_matches({"name": "X"}, "   ")


def test_row_matches_multiple_fields():
    row = {"@id": "A", "name": "Alice", "title": "Engineer"}
    assert _row_matches(row, "engineer")


# -- Hybrid path: total ≤ 1000 → all docs loaded -----------------------------


async def test_hybrid_path_loads_all_docs():
    """When total ≤ threshold, all docs are loaded into all_rows."""
    docs = _make_docs(50)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 50},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.total_count == 50
    assert state.use_server_pagination is False
    assert len(state.all_rows) == 50
    assert state.rows == []
    assert state.display_fields == ["name", "age"]
    assert state._known_class_ids == ["Person"]
    assert fake.aclose_called


# -- Server path: total > 1000 → server-side pagination ----------------------


async def test_server_path_fetches_page_with_skip_count():
    """When total > threshold, first page is fetched with skip=0, count=page_size."""
    docs = _make_docs(2000)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 2000},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.total_count == 2000
    assert state.use_server_pagination is True
    assert len(state.rows) == 25
    assert state.all_rows == []
    assert state.page_index == 0
    assert len(fake.get_docs_calls) >= 1
    first = fake.get_docs_calls[0]
    assert first["type_"] == "Person"
    assert first["skip"] == 0
    assert first["count"] == 25


async def test_server_path_next_page_fetches():
    """Next page triggers fetch_page with correct skip."""
    docs = _make_docs(2000)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 2000},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())
        assert state.page_index == 0
        fake.get_docs_calls.clear()

        await _drive(state.next_page())
        assert state.page_index == 1
        assert len(fake.get_docs_calls) == 1
        assert fake.get_docs_calls[0]["skip"] == 25
        assert fake.get_docs_calls[0]["count"] == 25


async def test_server_path_prev_page_fetches():
    """Prev page triggers fetch_page with correct skip."""
    docs = _make_docs(2000)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 2000},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())
        state.page_index = 2
        fake.get_docs_calls.clear()

        await _drive(state.prev_page())
        assert state.page_index == 1
        assert len(fake.get_docs_calls) == 1
        assert fake.get_docs_calls[0]["skip"] == 25
        assert fake.get_docs_calls[0]["count"] == 25


# -- Client-side sort (hybrid path) -------------------------------------------


async def test_hybrid_sort_asc():
    """Sort field ascending in hybrid mode."""
    docs = [
        {"@id": "Person/1", "@type": "Person", "name": "Charlie"},
        {"@id": "Person/2", "@type": "Person", "name": "Alice"},
        {"@id": "Person/3", "@type": "Person", "name": "Bob"},
    ]
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string"}],
        counts={"Person": 3},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    await _drive(state.set_sort("name"))
    rows = state.paged_rows
    assert rows[0]["name"] == "Alice"
    assert rows[1]["name"] == "Bob"
    assert rows[2]["name"] == "Charlie"


async def test_hybrid_sort_desc():
    """Sort field descending in hybrid mode."""
    docs = [
        {"@id": "Person/1", "@type": "Person", "name": "Charlie"},
        {"@id": "Person/2", "@type": "Person", "name": "Alice"},
        {"@id": "Person/3", "@type": "Person", "name": "Bob"},
    ]
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string"}],
        counts={"Person": 3},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    await _drive(state.set_sort("name"))
    await _drive(state.set_sort("name"))  # toggle to desc
    rows = state.paged_rows
    assert rows[0]["name"] == "Charlie"
    assert rows[1]["name"] == "Bob"
    assert rows[2]["name"] == "Alice"


async def test_hybrid_sort_toggle():
    """Toggling sort dir works."""
    docs = [
        {"@id": "Person/1", "@type": "Person", "name": "A"},
        {"@id": "Person/2", "@type": "Person", "name": "B"},
    ]
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string"}],
        counts={"Person": 2},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.sort_field == ""
    assert state.sort_dir == "asc"

    await _drive(state.set_sort("name"))
    assert state.sort_field == "name"
    assert state.sort_dir == "asc"

    await _drive(state.set_sort("name"))
    assert state.sort_field == "name"
    assert state.sort_dir == "desc"

    await _drive(state.set_sort("name"))
    assert state.sort_field == "name"
    assert state.sort_dir == "asc"


# -- Text filter (hybrid path) ------------------------------------------------


async def test_hybrid_search_filters_rows():
    """Search filters all_rows case-insensitively."""
    docs = [
        {"@id": "Person/1", "@type": "Person", "name": "Alice", "title": "Dev"},
        {"@id": "Person/2", "@type": "Person", "name": "Bob", "title": "PM"},
        {"@id": "Person/3", "@type": "Person", "name": "Charlie", "title": "Dev"},
    ]
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "title": "xsd:string"}],
        counts={"Person": 3},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    await _drive(state.set_search("bob"))
    assert state.effective_count == 1
    rows = state.paged_rows
    assert len(rows) == 1
    assert rows[0]["name"] == "Bob"

    await _drive(state.set_search("dev"))
    assert state.effective_count == 2

    await _drive(state.set_search(""))
    assert state.effective_count == 3


async def test_hybrid_search_no_match_shows_empty():
    """When no rows match, paged_rows is empty."""
    docs = _make_docs(10)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 10},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    await _drive(state.set_search("zzz_nonexistent_xyzzy"))
    assert state.effective_count == 0
    assert state.paged_rows == []


# -- Page-size change resets to page 0 ----------------------------------------


async def test_hybrid_page_size_resets_page():
    """Changing page size resets page_index to 0."""
    docs = _make_docs(100)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 100},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    state.page_index = 2
    await _drive(state.set_page_size("10"))
    assert state.page_size == 10
    assert state.page_index == 0


async def test_server_page_size_resets_and_fetches():
    """Changing page size in server mode resets page and re-fetches."""
    docs = _make_docs(2000)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": 2000},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())
        fake.get_docs_calls.clear()

        await _drive(state.set_page_size("50"))
        assert state.page_size == 50
        assert state.page_index == 0
        assert len(fake.get_docs_calls) >= 1
        assert fake.get_docs_calls[-1]["skip"] == 0
        assert fake.get_docs_calls[-1]["count"] == 50


# -- select() extracts references ---------------------------------------------


async def test_select_extracts_references():
    """select() computes outgoing references from the doc."""
    fake = _FakeClassTdb(
        schema=[
            {"@type": "Class", "@id": "Person", "name": "xsd:string"},
            {"@type": "Class", "@id": "Task", "title": "xsd:string"},
        ],
        single_doc={
            "@id": "Person/0",
            "@type": "Person",
            "name": "Alice",
            "friend": "Person/1",
            "task": {"@id": "Task/0"},
        },
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    state._known_class_ids = ["Person", "Task"]

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.select("Person/0"))

    assert state.selected_doc is not None
    assert state.references
    ref_targets = {r["target"] for r in state.references}
    assert "Person/1" in ref_targets
    assert "Task/0" in ref_targets
    assert fake.aclose_called


async def test_select_handles_error():
    """select() handles WebuiClientError gracefully."""
    fake = _FakeClassTdb(raise_tdb_error_on="get_document")
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.select("Person/0"))

    assert state.selected_doc is not None
    assert "error" in state.selected_doc  # type: ignore[operator]
    assert state.references == []


# -- navigate_to_reference ----------------------------------------------------


async def test_navigate_to_reference_chains_to_select():
    """navigate_to_reference(target) yields BrowseClassState.select(target)."""
    state = BrowseClassState()  # type: ignore[call-arg]
    gen = state.navigate_to_reference("Person/5")
    val = await gen.__anext__()
    # Reflex yields EventSpec for chained handlers
    assert hasattr(val, "handler")
    assert val.handler.fn.__name__ == "select"


# -- clear_selection clears references ----------------------------------------


async def test_clear_selection_clears_references():
    """clear_selection resets selected_doc, selected_json, and references."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.selected_doc = {"@id": "x"}
    state.selected_json = '{"@id": "x"}'
    state.references = [{"prop": "friend", "target": "Person/1", "target_label": "Person/1"}]

    await _drive(state.clear_selection())
    assert state.selected_doc is None
    assert state.selected_json == ""
    assert state.references == []


# -- Hybrid threshold boundary ------------------------------------------------


async def test_total_exactly_threshold_uses_hybrid():
    """When total == HYBRID_THRESHOLD, hybrid path is used."""
    threshold = 1000  # BrowseClassState.HYBRID_THRESHOLD
    docs = _make_docs(threshold)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": threshold},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.use_server_pagination is False
    assert len(state.all_rows) == threshold


async def test_total_above_threshold_uses_server():
    """When total > HYBRID_THRESHOLD, server pagination is used."""
    threshold = 1000  # BrowseClassState.HYBRID_THRESHOLD
    docs = _make_docs(threshold + 1)
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Person", "name": "xsd:string", "age": "xsd:integer"}],
        counts={"Person": threshold + 1},
        docs={"Person": docs},
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.use_server_pagination is True
    assert len(state.rows) == 25


# -- Computed vars ------------------------------------------------------------


def test_effective_count_server_mode():
    """In server mode, effective_count equals total_count."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.total_count = 500
    state.use_server_pagination = True
    state.search_text = "should be ignored"
    assert state.effective_count == 500


def test_effective_count_hybrid_no_search():
    """In hybrid mode without search, effective_count equals total_count."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.total_count = 50
    state.use_server_pagination = False
    state.search_text = ""
    assert state.effective_count == 50


def test_total_pages_calculation():
    """total_pages uses effective_count."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.total_count = 100
    state.page_size = 25
    assert state.total_pages == 4

    state.total_count = 101
    assert state.total_pages == 5

    state.total_count = 0
    assert state.total_pages == 0


def test_paged_rows_server_mode_uses_rows():
    """In server mode, paged_rows returns sorted rows."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.use_server_pagination = True
    state.rows = [
        {"@id": "1", "name": "B"},
        {"@id": "2", "name": "A"},
    ]
    state.sort_field = "name"
    state.sort_dir = "asc"
    state.page_size = 25
    rows = state.paged_rows
    assert rows[0]["name"] == "A"
    assert rows[1]["name"] == "B"


def test_paged_rows_hybrid_paginates():
    """In hybrid mode, paged_rows returns paginated all_rows."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.use_server_pagination = False
    state.all_rows = [{"@id": str(i), "name": f"N{i}"} for i in range(30)]
    state.page_size = 10
    state.page_index = 1
    rows = state.paged_rows
    assert len(rows) == 10
    assert rows[0]["@id"] == "10"


# -- refresh_page chains to load ----------------------------------------------


async def test_refresh_page_yields_load():
    """refresh_page yields BrowseClassState.load."""
    state = BrowseClassState()  # type: ignore[call-arg]
    gen = state.refresh_page()
    val = await gen.__anext__()
    assert callable(val)


# -- Load error handling ------------------------------------------------------


async def test_load_sets_error_on_client_error():
    """load() sets error when TdbBrowser raises WebuiClientError."""
    fake = _FakeClassTdb(raise_tdb_error_on="schema")
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.error != ""
    assert "Failed to load" in state.error
    assert not state.loading


async def test_load_no_class_name():
    """load() sets error when class_name is empty."""
    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "")

    with patch("firnline_webui.state.browse_class.make_tdb_browser") as mock_make:
        await _drive(state.load())
        mock_make.assert_not_called()

    assert state.error == "No class name provided."


async def test_load_class_not_found():
    """load() sets not_found when class is not in schema."""
    fake = _FakeClassTdb(
        schema=[{"@type": "Class", "@id": "Task", "title": "xsd:string"}],
    )
    browser = _make_browser(fake)

    state = BrowseClassState()  # type: ignore[call-arg]
    _mock_router(state, "Person")

    with patch("firnline_webui.state.browse_class.make_tdb_browser", return_value=browser):
        await _drive(state.load())

    assert state.not_found
    assert "not found" in state.error.lower()


# -- set_page_size invalid values ---------------------------------------------


async def test_set_page_size_invalid_noop():
    """set_page_size with invalid string is a no-op."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.page_size = 25
    state.page_index = 3

    await _drive(state.set_page_size("not_a_number"))
    assert state.page_size == 25
    assert state.page_index == 3


async def test_set_page_size_zero_noop():
    """set_page_size with zero is a no-op."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.page_size = 25
    await _drive(state.set_page_size("0"))
    assert state.page_size == 25


# ── set_sort resets page_index (Fix 1) ────────────────────────────────────────


async def test_set_sort_resets_page_index():
    """set_sort resets page_index to 0, consistent with set_search and set_page_size."""
    state = BrowseClassState()  # type: ignore[call-arg]
    state.all_rows = [{"@id": str(i), "name": f"N{i}"} for i in range(50)]
    state.page_size = 10
    state.page_index = 3  # on page 3
    state.sort_field = ""
    state.sort_dir = "asc"

    await _drive(state.set_sort("name"))
    assert state.sort_field == "name"
    assert state.sort_dir == "asc"
    assert state.page_index == 0  # reset

    # Toggling sort on same field also resets
    state.page_index = 2
    await _drive(state.set_sort("name"))
    assert state.sort_dir == "desc"
    assert state.page_index == 0  # reset again


# ── _is_known_ref requires "/" (Fix 3) ────────────────────────────────────────


def test_is_known_ref_requires_slash():
    """_is_known_ref returns False for bare class names."""
    known = {"Person", "Task"}
    assert not _is_known_ref("Person", known)
    assert not _is_known_ref("Task", known)


def test_is_known_ref_accepts_class_instance_id():
    """_is_known_ref returns True for Class/instance-id strings."""
    known = {"Person", "Task"}
    assert _is_known_ref("Person/alice", known)
    assert _is_known_ref("Task/1", known)
    assert _is_known_ref("Person/alice/sub", known)


def test_is_known_ref_rejects_non_iri_strings():
    """_is_known_ref rejects strings without '/' even if known_ids has them."""
    known = {"Person", "Task"}
    assert not _is_known_ref("Alice", known)
    assert not _is_known_ref("", known)
    assert not _is_known_ref("random_string", known)


def test_is_known_ref_rejects_unknown_prefix_with_slash():
    """_is_known_ref rejects unknown prefixes even with '/'."""
    known = {"Person"}
    assert not _is_known_ref("Task/1", known)
    assert not _is_known_ref("Unknown/X", known)


def test_is_known_ref_exact_match_with_slash():
    """_is_known_ref returns True for exact match when value contains '/'."""
    known = {"Person", "Person/alice"}
    assert not _is_known_ref("Person", known)  # no slash
    assert _is_known_ref("Person/alice", known)  # exact match with slash


def test_is_known_ref_compute_references_excludes_bare_names():
    """_compute_references does not include bare class-name string values."""
    doc = {
        "@id": "Person/alice",
        "@type": "Person",
        "name": "Alice",
        "friend": "Person/bob",  # valid ref
        "knows_class": "Person",  # bare class name → NOT a ref
        "team": {"@id": "Team/blue"},  # dict ref with slash
    }
    known = {"Person", "Team"}
    refs = _compute_references(doc, known)
    targets = {r["target"] for r in refs}
    assert "Person/bob" in targets
    assert "Team/blue" in targets
    assert "Person" not in targets  # bare class name excluded

