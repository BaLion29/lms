"""Tests for ToolSpecPlugin conformance and handler end-to-end for time-management tools."""

from __future__ import annotations

import json

import pytest

from firnline_core.plugins import ToolSpecPlugin, validate_plugin
from firnline_core.tdb import TdbClient
from firnline_core.toolspec import ToolContext

from firnline_ext_time_management.tools import plugin as tm_plugin


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


def _tdb_client() -> TdbClient:
    return TdbClient(base_url=TDB_URL, org=ORG, db=TDB_DB, user="admin", password="pw", author="service:queryd")


# ---------------------------------------------------------------------------
# Plugin conformance
# ---------------------------------------------------------------------------


def test_plugin_satisfies_toolspec_protocol():
    """The plugin object passes isinstance check against ToolSpecPlugin."""
    assert isinstance(tm_plugin, ToolSpecPlugin)
    violations = validate_plugin(tm_plugin, ToolSpecPlugin)
    assert violations == [], f"ToolSpecPlugin violations: {violations}"


def test_tool_specs_returns_all_seven_tools():
    """tool_specs() returns ToolSpec objects for all 7 tools."""
    specs = tm_plugin.tool_specs()
    names = {s.name for s in specs}
    assert names == {
        "set_task_status",
        "set_event_status",
        "create_task",
        "update_task",
        "create_routine",
        "update_routine",
        "log_activity",
    }
    assert len(specs) == 7


def test_set_task_status_input_schema():
    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_task_status")
    schema = spec.input_schema
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"task_iri", "status"}
    assert set(schema["properties"].keys()) == {"task_iri", "status"}
    assert "open" in schema["properties"]["status"]["enum"]


def test_create_task_input_schema():
    spec = next(s for s in tm_plugin.tool_specs() if s.name == "create_task")
    schema = spec.input_schema
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"name"}
    props = set(schema["properties"].keys())
    assert "description" in props
    assert "due_date" in props
    assert "priority" in props


# ---------------------------------------------------------------------------
# Handler tests — create_task (happy path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_task(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Task/new123"],
    )
    spec = next(s for s in tm_plugin.tool_specs() if s.name == "create_task")
    args = spec.args_model(name="New Task")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "terminusdb:///data/Task/new123"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Task"
    assert doc["name"] == "New Task"
    assert doc["status"] == "open"
    assert doc["provenance"]["agent"] == "ext:time-management"


# ---------------------------------------------------------------------------
# Handler tests — set_task_status (invalid transition → ok:False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_set_task_status_invalid_transition(respx_mock):
    """Transition from 'done' to 'planned' is invalid → returns ok:False."""
    doc = {"@id": "Task/abc", "@type": "Task", "name": "X", "status": "done"}
    respx_mock.get(DOC_PATH).respond(json=dict(doc))
    # No POST should be called (invalid transition rejected before POST)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_task_status")
    args = spec.args_model(task_iri="Task/abc", status="planned")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result["ok"] is False
    assert "error" in result
    assert not post_route.called  # transition failed before insert


# ---------------------------------------------------------------------------
# Handler tests — set_task_status (happy path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_set_task_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Review PR",
        "status": "open",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_task_status")
    args = spec.args_model(task_iri="Task/abc", status="done")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "Task/abc"}
    assert post_route.called


# ---------------------------------------------------------------------------
# Handler tests — set_task_status (not found)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_set_task_status_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_task_status")
    args = spec.args_model(task_iri="Task/nope", status="open")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# Handler tests — update_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_update_task_only_provided_fields_changed(respx_mock):
    orig = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Old name",
        "description": "Old desc",
        "priority": 1,
        "status": "open",
        "required_context": [],
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "update_task")
    args = spec.args_model(task_iri="Task/abc", name="New name")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "Task/abc"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "New name"
    assert doc["description"] == "Old desc"
    assert doc["priority"] == 1
    assert doc["status"] == "open"


@pytest.mark.asyncio
async def test_handle_update_task_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "update_task")
    args = spec.args_model(task_iri="Task/nope")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# Handler tests — update_routine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_update_routine_name_only(respx_mock):
    orig = {
        "@id": "Routine/r1",
        "@type": "Routine",
        "name": "Old routine",
        "required_context": [],
        "steps": [],
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Routine/r1"])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "update_routine")
    args = spec.args_model(routine_iri="Routine/r1", name="New routine")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "Routine/r1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "New routine"
    assert doc["required_context"] == []
    assert doc["steps"] == []


# ---------------------------------------------------------------------------
# Handler tests — set_event_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_set_event_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Event/xyz",
        "@type": "Event",
        "name": "Team sync",
        "status": "open",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Event/xyz"])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_event_status")
    args = spec.args_model(event_iri="Event/xyz", status="closed")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "Event/xyz"}
    assert post_route.called


@pytest.mark.asyncio
async def test_handle_set_event_status_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "set_event_status")
    args = spec.args_model(event_iri="Task/abc", status="closed")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result["ok"] is False
    assert "not an Event" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# Handler tests — log_activity with routine_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_log_activity_with_routine_link(respx_mock):
    respx_mock.get(DOC_PATH).respond(
        json={"@id": "Routine/r1", "@type": "Routine", "name": "Morning routine"}
    )
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Activity/act1"],
    )

    spec = next(s for s in tm_plugin.tool_specs() if s.name == "log_activity")
    args = spec.args_model(
        name="Morning yoga session",
        start_datetime="2026-07-08T07:00:00Z",
        end_datetime="2026-07-08T08:00:00Z",
        priority=2,
        estimated_duration=60,
        routine_id="Routine/r1",
    )
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "terminusdb:///data/Activity/act1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["routine"] == "Routine/r1"
    assert doc["start_datetime"] == "2026-07-08T07:00:00Z"
    assert doc["end_datetime"] == "2026-07-08T08:00:00Z"
    assert doc["priority"] == 2
    assert doc["estimated_duration"] == 60

