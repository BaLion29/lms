"""Tests for firnline_ext_planning.tools — planning write tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from firnline_core.tdb import TdbClient
from firnline_ext_planning.tools import (
    create_task,
    plugin as planning_plugin,
    set_event_status,
    set_task_status,
    update_task,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"

DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal settings matching what tool functions access."""

    tdb_branch = "main"
    max_tool_iterations = 50
    enable_writes = True


class _FakeDeps:
    """Minimal deps matching QuerydDeps shape."""

    def __init__(self, tdb):
        self.tdb = tdb
        self.settings = _FakeSettings()
        self.trace: list[object] = []
        self.tool_calls_used = 0
        self.prompt_briefing = ""
        self.schema_summary = "dummy schema"


def _make_ctx(tdb: TdbClient | None = None) -> RunContext:
    """Build a minimal RunContext for testing."""
    if tdb is None:
        tdb = TdbClient(base_url=TDB_URL, org=ORG, db=TDB_DB, user="admin", password="pw", author="service:queryd")
    deps = _FakeDeps(tdb)
    fake_model = MagicMock()
    fake_usage = MagicMock()
    return RunContext(deps=deps, model=fake_model, usage=fake_usage)


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


def test_plugin_name_and_requires():
    assert planning_plugin.name == "planning_tools"
    reqs = planning_plugin.requires
    assert len(reqs) == 1
    assert reqs[0].name == "planning"
    assert reqs[0].range == ">=0.1.0 <0.2.0"


def test_plugin_tools():
    tools = planning_plugin.tools(deps=None)
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "set_task_status",
        "set_event_status",
        "create_task",
        "update_task",
    }


# ---------------------------------------------------------------------------
# set_task_status
# ---------------------------------------------------------------------------


async def test_set_task_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Review PR",
        "status": "open",
        "description": "look at the diff",
        "priority": 3,
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
        "required_context": [],
    }
    get_route = respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await set_task_status(ctx, "Task/abc", "done")

    assert result == {"ok": True, "iri": "Task/abc"}
    assert get_route.called
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    # transition sends [updated_doc, transition_audit_doc]
    assert isinstance(sent, list)
    assert len(sent) == 2
    updated_doc = sent[0]
    assert updated_doc["status"] == "done"
    assert updated_doc["updated_at"] != orig_doc["updated_at"]
    assert updated_doc["name"] == orig_doc["name"]
    assert updated_doc["description"] == orig_doc["description"]
    assert updated_doc["priority"] == orig_doc["priority"]
    assert updated_doc["created_at"] == orig_doc["created_at"]
    assert updated_doc["@type"] == "Task"

    params = req.url.params
    assert params["author"] == "service:queryd"
    assert "transition" in params["message"]


async def test_set_task_status_wrong_type(respx_mock):
    event_doc = {"@id": "Event/abc", "@type": "Event", "name": "Meeting"}
    get_route = respx_mock.get(DOC_PATH).respond(json=event_doc)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await set_task_status(ctx, "Event/abc", "done")

    assert result["ok"] is False
    assert "not a Task" in result["error"]
    assert get_route.called
    assert not post_route.called


async def test_set_task_status_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    ctx = _make_ctx()
    result = await set_task_status(ctx, "Task/nope", "open")
    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# set_event_status
# ---------------------------------------------------------------------------


async def test_set_event_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Event/xyz",
        "@type": "Event",
        "name": "Team sync",
        "status": "open",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Event/xyz"])

    ctx = _make_ctx()
    result = await set_event_status(ctx, "Event/xyz", "closed")

    assert result == {"ok": True, "iri": "Event/xyz"}
    assert post_route.called
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    assert isinstance(sent, list)
    assert len(sent) == 2
    updated_doc = sent[0]
    assert updated_doc["status"] == "closed"
    assert updated_doc["updated_at"] != orig_doc["updated_at"]
    assert req.url.params["author"] == "service:queryd"


async def test_set_event_status_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await set_event_status(ctx, "Task/abc", "closed")
    assert result["ok"] is False
    assert "not an Event" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


async def test_create_task(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Task/new123"],
    )
    ctx = _make_ctx()
    result = await create_task(ctx, "New Task")

    assert result == {"ok": True, "iri": "terminusdb:///data/Task/new123"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent

    assert doc["@type"] == "Task"
    assert doc["name"] == "New Task"
    assert doc["status"] == "open"
    assert "created_at" in doc
    assert "updated_at" in doc
    assert doc["created_at"] == doc["updated_at"]
    # No due_date → anchor_at should be None → excluded by exclude_none
    assert "anchor_at" not in doc
    assert "derived_from" not in doc
    prov = doc["provenance"]
    # @type is stripped by repo.create() for provenance subdoc
    assert prov["agent"] == "ext:planning"
    assert prov["method"] == "tool_call"
    # source=None should be excluded
    assert "source" not in prov

    params = req.url.params
    assert params["author"] == "service:queryd"


async def test_create_task_with_all_fields(respx_mock):
    respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Task/abc"],
    )
    ctx = _make_ctx()
    due = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
    result = await create_task(
        ctx,
        "Complex Task",
        description="desc",
        due_date=due,
        priority=5,
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Complex Task"
    assert doc["description"] == "desc"
    assert doc["due_date"] == "2026-12-31T12:00:00Z"
    assert doc["priority"] == 5
    assert doc["anchor_at"] == "2026-12-31T12:00:00Z"
    assert doc["provenance"]["agent"] == "ext:planning"
    assert "source" not in doc["provenance"]


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


async def test_update_task_only_provided_fields_changed(respx_mock):
    orig = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Old name",
        "description": "Old desc",
        "priority": 1,
        "status": "open",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
        "required_context": [],
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await update_task(ctx, "Task/abc", name="New name")

    assert result == {"ok": True, "iri": "Task/abc"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "New name"
    assert doc["description"] == "Old desc"
    assert doc["priority"] == 1
    assert doc["status"] == "open"
    assert doc["updated_at"] != orig["updated_at"]
    assert doc["created_at"] == orig["created_at"]


async def test_update_task_multiple_fields(respx_mock):
    orig = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Old",
        "description": "Old desc",
        "priority": 1,
        "status": "open",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    due = "2026-08-01T12:00:00Z"
    ctx = _make_ctx()
    result = await update_task(ctx, "Task/abc", name="Updated", description=None, priority=5, due_date=due)

    assert result["ok"] is True
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["description"] == "Old desc"
    assert doc["name"] == "Updated"
    assert doc["priority"] == 5
    assert doc["due_date"] == "2026-08-01T12:00:00Z"


async def test_update_task_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)
    ctx = _make_ctx()
    result = await update_task(ctx, "Task/nope")
    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# IRI normalization
# ---------------------------------------------------------------------------


async def test_set_task_status_normalizes_full_iri(respx_mock):
    doc = {"@id": "Task/abc", "@type": "Task", "name": "X", "status": "open"}
    respx_mock.get(DOC_PATH).respond(json=dict(doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await set_task_status(ctx, "terminusdb:///data/Task/abc", "done")
    assert result["ok"] is True
    assert "Task/abc" in result["iri"]
    assert post_route.called
