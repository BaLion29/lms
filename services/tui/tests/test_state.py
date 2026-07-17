"""Tests for the framework-free state layer."""

from __future__ import annotations

import pytest

from firnline_core.uiclients import UiClientError
from firnline_tui.state.context import AppContext

from firnline_tui.state.inbox import InboxData, filter_rows, load_inbox
from firnline_tui.state.capture import submit_note
from firnline_tui.state.selection import SelectionController
from firnline_tui.state.dashboard import load_dashboard
from firnline_tui.state.browse import load_browse
from firnline_tui.state.browse_class import load_class
from firnline_tui.state.browse_helpers import (
    _compute_references,
    _row_matches,
    _sort_key,
)
from firnline_tui.state.automations import (
    _iri_tail,
    _lookup_name,
    _resolve_ref,
    _str_or,
    _int_or,
    _subject_display,
    concretes_inheriting,
    load_automations,
)
from firnline_tui.state.health import load_health
from firnline_tui.state.modules import load_modules
from firnline_tui.state.history import (
    _format_ts,
    load_commit,
    load_history,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeTdb:
    """Fake TdbBrowser for testing."""

    def __init__(
        self,
        schema=None,
        modules=None,
        docs=None,
        counts=None,
        commit_log=None,
        commit_changes=None,
        document=None,
    ):
        self._schema = schema or []
        self._modules = modules or []
        self._docs = docs or {}
        self._counts = counts or {}
        self._commit_log = commit_log or []
        self._commit_changes = commit_changes or {}
        self._document = document or {}

    async def get_schema(self):
        return self._schema

    async def get_modules(self):
        return self._modules

    async def get_documents(self, type_, *, skip=None, count=None):
        docs = self._docs.get(type_, [])
        if skip is not None and count is not None:
            return docs[skip : skip + count]
        if skip is not None:
            return docs[skip:]
        if count is not None:
            return docs[:count]
        return docs

    async def count_documents(self, type_):
        return self._counts.get(type_, len(self._docs.get(type_, [])))

    async def get_document(self, iri):
        return self._document

    async def get_commit_log(self, count=None):
        return self._commit_log[:count] if count else self._commit_log

    async def get_commit_changes(self, commit_id):
        return self._commit_changes

    async def aclose(self):
        pass


class FakeCaptured:
    """Fake CapturedClient for testing."""

    def __init__(self, healthz_data=None, capture_result=None, capture_error=None):
        self._healthz_data = healthz_data or {"status": "ok", "version": "1.0"}
        self._capture_result = capture_result or {"id": "test/doc1"}
        self._capture_error = capture_error

    async def healthz(self):
        return self._healthz_data

    async def capture_note(self, text=""):
        if self._capture_error:
            raise self._capture_error
        return self._capture_result

    async def aclose(self):
        pass


class FakeHealth:
    """Fake ServiceHealthClient / QuerydClient for testing."""

    def __init__(self, data=None, raises=None):
        self._data = data or {"status": "healthy", "version": "1.0"}
        self._raises = raises

    async def healthz(self):
        if self._raises:
            raise self._raises
        return self._data


class FakeIndexed:
    """Fake IndexedClient for testing."""

    async def healthz(self):
        return {"status": "healthy", "version": "1.0"}

    async def aclose(self):
        pass


def make_fake_ctx(make_tdb=None, make_captured=None, make_health=None, make_indexed=None):
    """Build a fake AppContext for testing."""
    return AppContext(
        org="admin",
        db="firnline",
        branch="main",
        make_tdb=make_tdb or (lambda: FakeTdb()),
        make_captured=make_captured or (lambda: FakeCaptured()),
        make_health=make_health or (
            lambda: (FakeHealth(), FakeHealth(), FakeHealth(), FakeHealth())
        ),
        make_indexed=make_indexed or (lambda: FakeIndexed()),
    )


# ---------------------------------------------------------------------------
# Inbox tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_load_with_captured_docs():
    schema = [
        {"@type": "Class", "@id": "Captured"},
        {"@type": "Class", "@id": "Other"},
    ]
    docs = {
        "Captured": [
            {
                "@id": "Captured/doc1",
                "status": "done",
                "captured_at": "2024-01-02T00:00:00Z",
                "content_type": "text/plain",
                "text": "Hello world note",
            },
            {
                "@id": "Captured/doc2",
                "status": "pending",
                "captured_at": "2024-01-01T00:00:00Z",
                "content_type": "text/plain",
                "text": "Another note",
            },
        ],
    }
    tdb = FakeTdb(schema=schema, docs=docs)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_inbox(ctx)

    assert len(result.rows) == 2
    assert result.statuses == ("done", "pending")
    # Most recent first
    assert result.rows[0]["id"] == "Captured/doc1"
    assert result.rows[0]["status"] == "done"
    assert result.rows[1]["id"] == "Captured/doc2"
    assert result.rows[1]["status"] == "pending"
    assert result.error == ""


@pytest.mark.asyncio
async def test_inbox_no_captured_class():
    schema = [{"@type": "Class", "@id": "Other"}]
    tdb = FakeTdb(schema=schema)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_inbox(ctx)

    assert len(result.rows) == 0
    assert result.statuses == ()
    assert result.error == ""


def test_inbox_filter_rows_all():
    rows = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "pending"},
        {"id": "c", "status": "done"},
    ]
    data = InboxData(rows=tuple(rows))
    result = filter_rows(data, "all")
    assert len(result) == 3


def test_inbox_filter_rows_by_status():
    rows = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "pending"},
        {"id": "c", "status": "done"},
    ]
    data = InboxData(rows=tuple(rows))
    result = filter_rows(data, "done")
    assert len(result) == 2
    assert all(r["status"] == "done" for r in result)


def test_inbox_filter_rows_no_match():
    rows = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "done"},
    ]
    data = InboxData(rows=tuple(rows))
    result = filter_rows(data, "pending")
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Capture tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_submit_note_empty():
    ctx = make_fake_ctx()
    result = await submit_note(ctx, "   ")
    assert result.ok is False
    assert result.error == "Text must not be empty."
    assert result.doc_id == ""


@pytest.mark.asyncio
async def test_capture_submit_note_success():
    captured = FakeCaptured(capture_result={"id": "Captured/new_note"})
    ctx = make_fake_ctx(make_captured=lambda: captured)

    result = await submit_note(ctx, "Hello world")
    assert result.ok is True
    assert result.doc_id == "Captured/new_note"
    assert result.error == ""


@pytest.mark.asyncio
async def test_capture_submit_note_error():
    captured = FakeCaptured(
        capture_error=UiClientError(500, "Internal error")
    )
    ctx = make_fake_ctx(make_captured=lambda: captured)

    result = await submit_note(ctx, "Hello world")
    assert result.ok is False
    assert "Internal error" in result.error


# ---------------------------------------------------------------------------
# SelectionController tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selection_controller_select():
    doc = {"@id": "Test/doc1", "name": "My Document", "status": "done"}
    tdb = FakeTdb(document=doc)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    ctrl = SelectionController(ctx)
    result = await ctrl.select("Test/doc1")

    assert "My Document" in result
    assert ctrl.selected_iri == "Test/doc1"


@pytest.mark.asyncio
async def test_selection_controller_select_empty():
    ctx = make_fake_ctx()
    ctrl = SelectionController(ctx)
    result = await ctrl.select("")
    assert result == ""
    assert ctrl.selected_iri is None


def test_selection_controller_clear():
    ctx = make_fake_ctx()
    ctrl = SelectionController(ctx)
    ctrl._selected_iri = "Test/doc1"
    ctrl.clear()
    assert ctrl.selected_iri is None


# ---------------------------------------------------------------------------
# Browse tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_load():
    schema = [
        {"@type": "Class", "@id": "Person"},
        {"@type": "Class", "@id": "Note"},
    ]
    modules = [
        {
            "@id": "mod1",
            "name": "test_module",
            "version": "1.0",
            "exports": ["Person"],
        },
    ]
    tdb = FakeTdb(schema=schema, modules=modules, counts={"Person": 5, "Note": 3})
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_browse(ctx)

    assert len(result.groups) == 2  # test_module + other
    assert result.groups[0][0] == "test_module" or result.groups[0][0] == "other"
    assert result.module_versions.get("test_module") == "1.0"
    assert result.class_counts.get("Person") == "5"
    assert result.class_counts.get("Note") == "3"
    assert result.error == ""


@pytest.mark.asyncio
async def test_browse_load_empty():
    schema = []
    modules = []
    tdb = FakeTdb(schema=schema, modules=modules)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_browse(ctx)
    assert len(result.groups) == 0
    assert result.error == ""


# ---------------------------------------------------------------------------
# Browse class tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_class_hybrid():
    """Test loading a class with <= 1000 docs (hybrid mode)."""
    schema = [{"@type": "Class", "@id": "Note", "name": "xsd:string"}]
    docs = [
        {"@id": "Note/a", "name": "Alpha"},
        {"@id": "Note/b", "name": "Beta"},
    ]
    tdb = FakeTdb(schema=schema, docs={"Note": docs}, counts={"Note": 2})
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_class(ctx, "Note", page_index=0, page_size=25, sort_field="name")

    assert result.not_found is False
    assert result.error == ""
    assert result.total_count == 2
    assert result.use_server_pagination is False
    assert len(result.rows) == 2
    # Sorted by name ascending
    assert result.rows[0]["name"] == "Alpha"
    assert result.rows[1]["name"] == "Beta"


@pytest.mark.asyncio
async def test_load_class_not_found():
    schema = [{"@type": "Class", "@id": "Note"}]
    tdb = FakeTdb(schema=schema)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_class(ctx, "Missing")
    assert result.not_found is True
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_load_class_empty_name():
    ctx = make_fake_ctx()
    result = await load_class(ctx, "")
    assert result.error == "No class name provided."


# ---------------------------------------------------------------------------
# Browse helpers tests
# ---------------------------------------------------------------------------


def test_row_matches():
    row = {"name": "Alpha", "status": "Done"}
    assert _row_matches(row, "alpha") is True
    assert _row_matches(row, "done") is True
    assert _row_matches(row, "beta") is False
    assert _row_matches(row, "") is True


def test_sort_key():
    assert _sort_key("Alpha") == "alpha"
    assert _sort_key("BETA") == "beta"
    assert _sort_key("123") == "123"


def test_compute_references():
    doc = {
        "@id": "Test/a",
        "friend": "Person/42",
        "nested": {"@id": "Org/1"},
        "items": ["Note/1", "Note/2"],
        "@type": "Test",
    }
    known = {"Person", "Note", "Org"}
    refs = _compute_references(doc, known)

    # 4 unique refs: friend=Person/42, nested=Org/1, items=Note/1, items=Note/2
    assert len(refs) == 4


def test_compute_references_no_match():
    doc = {"@id": "Test/a", "text": "hello"}
    known = {"Person", "Note"}
    refs = _compute_references(doc, known)
    assert len(refs) == 0


# ---------------------------------------------------------------------------
# Automations tests
# ---------------------------------------------------------------------------


def test_iri_tail():
    assert _iri_tail("") == ""
    assert _iri_tail("Trigger/abc") == "abc"
    assert _iri_tail("terminusdb:///data/Trigger/abc/") == "abc"
    assert _iri_tail("simple") == "simple"


def test_subject_display():
    assert _subject_display(None) == ""
    assert _subject_display("Note/42") == "42"
    assert _subject_display({"@id": "Person/55"}) == "55"


def test_resolve_ref():
    assert _resolve_ref(None) == ""
    assert _resolve_ref("Trigger/1") == "Trigger/1"
    assert _resolve_ref({"@id": "Trigger/1"}, default="x") == "Trigger/1"


def test_lookup_name():
    name_map = {
        "Trigger/hello": "My Hello Trigger",
        "t1": "Simple Trigger",
    }
    assert _lookup_name(name_map, "Trigger/hello") == "My Hello Trigger"
    # Suffix match: key "t1" matches when ref ends with "/t1"
    assert _lookup_name(name_map, "terminusdb:///data/T/t1") == "Simple Trigger"
    assert _lookup_name(name_map, "") == ""
    assert _lookup_name(name_map, "unknown") == "unknown"


def test_str_or():
    assert _str_or(None) == ""
    assert _str_or("hello") == "hello"
    assert _str_or(42) == "42"
    assert _str_or(None, "fallback") == "fallback"


def test_int_or():
    assert _int_or(None) == 0
    assert _int_or("5") == 5
    assert _int_or("abc") == 0
    assert _int_or(10) == 10


def test_concretes_inheriting():
    schema = [
        {"@type": "Class", "@id": "Trigger", "@abstract": True},
        {"@type": "Class", "@id": "OneShotTrigger", "@inherits": "Trigger"},
        {"@type": "Class", "@id": "Action", "@abstract": True},
        {"@type": "Class", "@id": "SendEmailAction", "@inherits": "Action"},
        {"@type": "Class", "@id": "NotATrigger", "@inherits": "SomethingElse"},
    ]
    triggers = concretes_inheriting(schema, "Trigger")
    assert triggers == ["OneShotTrigger"]

    actions = concretes_inheriting(schema, "Action")
    assert actions == ["SendEmailAction"]


@pytest.mark.asyncio
async def test_automations_load():
    schema = [
        {"@type": "Class", "@id": "TriggerFiring"},
        {"@type": "Class", "@id": "ActionExecution"},
    ]
    docs = {
        "TriggerFiring": [
            {
                "@id": "TriggerFiring/tf1",
                "trigger": "OneShotTrigger/t1",
                "status": "done",
                "scheduled_for": "2024-06-15",
            },
        ],
        "ActionExecution": [
            {
                "@id": "ActionExecution/ae1",
                "action": {"@id": "SendEmailAction/a1"},
                "status": "pending",
                "executed_at": "2024-06-10",
            },
        ],
    }
    tdb = FakeTdb(schema=schema, docs=docs)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_automations(ctx)

    assert result.triggers_available is True
    assert result.actions_available is True
    assert len(result.firing_rows) == 1
    assert result.firing_rows[0]["status"] == "done"
    assert len(result.execution_rows) == 1
    assert result.execution_rows[0]["status"] == "pending"
    assert result.firing_statuses == ("done",)
    assert result.execution_statuses == ("pending",)
    assert result.error == ""


# ---------------------------------------------------------------------------
# Health tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_load():
    def make_health():
        return (
            FakeHealth({"status": "healthy", "version": "1.0", "plugins": ["p1"]}),
            FakeHealth({"status": "healthy", "version": "2.0", "plugins": ["q1", "q2"]}),
            FakeHealth({"status": "degraded", "store": "ok"}),
            FakeHealth({"status": "healthy"}),
        )

    ctx = make_fake_ctx(make_health=make_health)

    result = await load_health(ctx)

    assert result.captured.status == "healthy"
    assert result.captured.version == "1.0"
    assert result.captured.handlers == ("p1",)
    assert result.queryd.status == "healthy"
    assert result.queryd.plugins == ("q1", "q2")
    assert result.indexed.status == "degraded"
    assert result.mcpd_status == "healthy"


@pytest.mark.asyncio
async def test_health_load_unreachable():
    def make_health():
        return (
            FakeHealth(raises=Exception("connection refused")),
            FakeHealth({"status": "healthy"}),
            FakeHealth(raises=Exception("timeout")),
            FakeHealth({"status": "healthy"}),
        )

    ctx = make_fake_ctx(make_health=make_health)
    result = await load_health(ctx)

    assert result.captured.status == "unreachable"
    assert result.queryd.status == "healthy"
    assert result.indexed.status == "unreachable"
    assert result.mcpd_status == "healthy"


# ---------------------------------------------------------------------------
# Modules tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modules_load():
    modules_raw = [
        {
            "@id": "firnline/core",
            "name": "firnline/core",
            "version": "1.0",
            "description": "Core module",
            "exports": ["Person", "Note"],
            "depends_on": ["base"],
        },
    ]

    def make_health():
        return (
            FakeHealth({"plugins": ["capture_plugin"]}),
            FakeHealth({"plugins": ["query_plugin"]}),
            FakeHealth({"handlers": ["index_plugin"]}),
            FakeHealth(),
        )

    tdb = FakeTdb(modules=modules_raw)
    ctx = make_fake_ctx(make_tdb=lambda: tdb, make_health=make_health)

    result = await load_modules(ctx)

    assert len(result.modules) == 1
    assert result.modules[0].name == "firnline/core"
    assert result.modules[0].version == "1.0"
    assert result.modules[0].exports == ("Person", "Note")
    assert result.modules[0].depends_on == ("base",)
    assert result.captured_plugins == ("capture_plugin",)
    assert result.queryd_plugins == ("query_plugin",)
    assert result.indexed_plugins == ("index_plugin",)
    assert result.error == ""


# ---------------------------------------------------------------------------
# History tests
# ---------------------------------------------------------------------------


def test_format_ts():
    assert _format_ts(None) == ""
    assert _format_ts(0) != ""  # Valid POSIX epoch
    assert _format_ts(1700000000) != ""


@pytest.mark.asyncio
async def test_history_load():
    commits = [
        {
            "id": "abc123def456",
            "short_id": "abc123def4",
            "author": "test_user",
            "message": "Initial commit",
            "timestamp": 1700000000.0,
        },
    ]
    tdb = FakeTdb(commit_log=commits)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_history(ctx)

    assert len(result.commits) == 1
    assert result.commits[0]["id"] == "abc123def456"
    assert result.commits[0]["short_id"] == "abc123def4"
    assert result.commits[0]["author"] == "test_user"
    assert result.commits[0]["message"] == "Initial commit"
    assert "timestamp_fmt" in result.commits[0]
    assert result.error == ""


@pytest.mark.asyncio
async def test_load_commit():
    changes = {
        "inserted": ["Person/p1"],
        "updated": ["Note/n1"],
        "deleted": ["OldDoc/o1"],
    }
    tdb = FakeTdb(commit_changes=changes)
    ctx = make_fake_ctx(make_tdb=lambda: tdb)

    result = await load_commit(ctx, "abc123")

    assert result.inserted == ("Person/p1",)
    assert result.updated == ("Note/n1",)
    assert result.deleted == ("OldDoc/o1",)
    assert result.error == ""


@pytest.mark.asyncio
async def test_load_commit_empty_id():
    ctx = make_fake_ctx()
    result = await load_commit(ctx, "")
    assert result.error == "No commit ID provided."


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_load():
    def make_health():
        return (
            FakeHealth({"status": "healthy", "version": "1.0"}),
            FakeHealth({"status": "healthy", "version": "2.0"}),
            FakeHealth({"status": "healthy"}),
            FakeHealth({"status": "healthy"}),
        )

    ctx = make_fake_ctx(make_health=make_health)

    result = await load_dashboard(ctx)

    assert len(result.services) == 4
    assert result.services[0].name == "captured"
    assert result.services[0].status == "healthy"

