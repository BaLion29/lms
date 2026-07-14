"""Tests for firnline_ext_time_management.tools — time-management write tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from firnline_core.tdb import TdbClient
from firnline_ext_time_management.tools import (
    create_routine,
    create_task,
    log_activity,
    plugin as tm_plugin,
    set_event_status,
    set_task_status,
    update_routine,
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
    assert tm_plugin.name == "time_management_tools"
    reqs = tm_plugin.requires
    assert len(reqs) == 1
    assert reqs[0].name == "time_management"
    assert reqs[0].range == ">=0.1.0 <0.2.0"


def test_plugin_tools():
    tools = tm_plugin.tools(deps=None)
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "set_task_status",
        "set_event_status",
        "create_task",
        "update_task",
        "create_routine",
        "update_routine",
        "log_activity",
    }


# ---------------------------------------------------------------------------
# set_task_status (ported from planning)
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
    assert isinstance(sent, list)
    assert len(sent) == 2
    updated_doc = sent[0]
    assert updated_doc["status"] == "done"
    assert updated_doc["name"] == orig_doc["name"]
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
# set_event_status (ported from planning)
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
# create_task (ported from planning)
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
    assert "anchor_at" not in doc
    prov = doc["provenance"]
    assert prov["agent"] == "ext:time-management"
    assert prov["method"] == "tool_call"
    assert "source" not in prov

    params = req.url.params
    assert params["author"] == "service:queryd"


async def test_create_task_with_all_fields(respx_mock):
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Task/abc"])
    ctx = _make_ctx()
    due = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
    result = await create_task(ctx, "Complex Task", description="desc", due_date=due, priority=5)
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Complex Task"
    assert doc["description"] == "desc"
    assert doc["due_date"] == "2026-12-31T12:00:00Z"
    assert doc["priority"] == 5
    assert doc["provenance"]["agent"] == "ext:time-management"


# ---------------------------------------------------------------------------
# update_task (ported from planning)
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


async def test_update_task_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)
    ctx = _make_ctx()
    result = await update_task(ctx, "Task/nope")
    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# create_routine
# ---------------------------------------------------------------------------


async def test_create_routine_with_activity_steps(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Routine/new123"],
    )
    ctx = _make_ctx()
    result = await create_routine(
        ctx,
        "Morning routine",
        required_context=["health"],
        steps=[
            {"name": "Stretch", "step_type": "activity", "cadence_days": 1, "description": "Morning stretches"},
            {"name": "Meditate", "step_type": "activity", "priority": 1, "estimated_duration": 10},
        ],
    )

    assert result == {"ok": True, "iri": "terminusdb:///data/Routine/new123"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Routine"
    assert doc["name"] == "Morning routine"
    assert doc["required_context"] == ["health"]
    assert "steps" in doc

    steps = doc["steps"]
    assert len(steps) == 2

    s0 = steps[0]
    assert s0["@type"] == "RoutineStep"
    assert s0["name"] == "Stretch"
    assert s0["cadence_days"] == 1
    assert s0["activity"]["@type"] == "ActivitySpec"
    assert s0["activity"]["name"] == "Stretch"
    assert s0["activity"]["description"] == "Morning stretches"
    assert s0.get("task") is None

    s1 = steps[1]
    assert s1["@type"] == "RoutineStep"
    assert s1["name"] == "Meditate"
    assert s1.get("cadence_days") is None
    assert s1["activity"]["@type"] == "ActivitySpec"
    assert s1["activity"]["priority"] == 1
    assert s1["activity"]["estimated_duration"] == 10

    params = req.url.params
    assert params["author"] == "service:queryd"


async def test_create_routine_with_task_steps(respx_mock):
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Routine/abc"])
    ctx = _make_ctx()
    result = await create_routine(
        ctx,
        "Work checklist",
        steps=[
            {"name": "Review PRs", "step_type": "task", "priority": 2, "estimated_duration": 30},
        ],
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    step = doc["steps"][0]
    assert step["name"] == "Review PRs"
    assert step["task"]["@type"] == "TaskSpec"
    assert step["task"]["name"] == "Review PRs"
    assert step["task"]["priority"] == 2
    assert step["task"]["estimated_duration"] == 30
    assert step.get("activity") is None


async def test_create_routine_mixed_steps(respx_mock):
    """Routine with both activity-step and task-step confirms oneOf mapping."""
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Routine/mixed"])
    ctx = _make_ctx()
    result = await create_routine(
        ctx,
        "Mixed routine",
        steps=[
            {"name": "Warmup", "step_type": "activity"},
            {"name": "Coding", "step_type": "task"},
        ],
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    steps = doc["steps"]
    assert steps[0]["activity"] is not None
    assert steps[0].get("task") is None
    assert steps[1]["task"] is not None
    assert steps[1].get("activity") is None


async def test_create_routine_defaults_step_type_to_activity(respx_mock):
    """When step_type is omitted, default to 'activity'."""
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Routine/def"])
    ctx = _make_ctx()
    result = await create_routine(
        ctx,
        "Default step type",
        steps=[{"name": "Default step"}],
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    step = doc["steps"][0]
    assert step["activity"] is not None
    assert step.get("task") is None


# ---------------------------------------------------------------------------
# update_routine
# ---------------------------------------------------------------------------


async def test_update_routine_name_only(respx_mock):
    orig = {
        "@id": "Routine/r1",
        "@type": "Routine",
        "name": "Old routine",
        "required_context": [],
        "steps": [],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Routine/r1"])

    ctx = _make_ctx()
    result = await update_routine(ctx, "Routine/r1", name="New routine")

    assert result == {"ok": True, "iri": "Routine/r1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "New routine"
    assert doc["required_context"] == []
    assert doc["steps"] == []
    assert doc["updated_at"] != orig["updated_at"]


async def test_update_routine_replace_steps(respx_mock):
    orig = {
        "@id": "Routine/r1",
        "@type": "Routine",
        "name": "Old routine",
        "required_context": [],
        "steps": [{"@type": "RoutineStep", "name": "Old step", "activity": {"@type": "ActivitySpec", "name": "Old step"}}],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Routine/r1"])

    ctx = _make_ctx()
    new_steps = [
        {"name": "New step", "step_type": "task", "priority": 1},
    ]
    result = await update_routine(ctx, "Routine/r1", steps=new_steps)

    assert result["ok"] is True
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert len(doc["steps"]) == 1
    assert doc["steps"][0]["name"] == "New step"
    assert doc["steps"][0]["task"]["@type"] == "TaskSpec"


async def test_update_routine_partial_name_and_context(respx_mock):
    orig = {
        "@id": "Routine/r1",
        "@type": "Routine",
        "name": "Old",
        "required_context": [],
        "steps": [],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Routine/r1"])

    ctx = _make_ctx()
    result = await update_routine(ctx, "Routine/r1", name="Updated", required_context=["fitness"])

    assert result["ok"] is True
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Updated"
    assert doc["required_context"] == ["fitness"]
    # steps untouched
    assert doc["steps"] == []


async def test_update_routine_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)
    ctx = _make_ctx()
    result = await update_routine(ctx, "Routine/nope")
    assert result["ok"] is False
    assert "document not found" in result["error"]


async def test_update_routine_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)

    ctx = _make_ctx()
    result = await update_routine(ctx, "Task/abc", name="Not a routine")
    assert result["ok"] is False
    assert "not a Routine" in result["error"]


# ---------------------------------------------------------------------------
# log_activity
# ---------------------------------------------------------------------------


async def test_log_activity_minimal(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Activity/new123"],
    )
    ctx = _make_ctx()
    result = await log_activity(ctx, "Morning yoga")

    assert result == {"ok": True, "iri": "terminusdb:///data/Activity/new123"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Activity"
    assert doc["name"] == "Morning yoga"
    assert "start_datetime" not in doc
    assert "routine" not in doc
    assert doc["provenance"]["agent"] == "ext:time-management"


async def test_log_activity_with_routine_link(respx_mock):
    get_route = respx_mock.get(DOC_PATH).respond(
        json={"@id": "Routine/r1", "@type": "Routine", "name": "Morning routine"}
    )
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Activity/act1"],
    )
    ctx = _make_ctx()
    result = await log_activity(
        ctx,
        "Morning yoga session",
        start_datetime="2026-07-08T07:00:00Z",
        end_datetime="2026-07-08T08:00:00Z",
        priority=2,
        estimated_duration=60,
        routine_id="Routine/r1",
    )

    assert result == {"ok": True, "iri": "terminusdb:///data/Activity/act1"}
    assert get_route.called
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["routine"] == "Routine/r1"
    assert doc["start_datetime"] == "2026-07-08T07:00:00Z"
    assert doc["end_datetime"] == "2026-07-08T08:00:00Z"
    assert doc["priority"] == 2
    assert doc["estimated_duration"] == 60


async def test_log_activity_routine_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="not found")
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await log_activity(ctx, "Session", routine_id="Routine/nope")

    assert result["ok"] is False
    assert "routine not found" in result["error"]
    assert not post_route.called


async def test_log_activity_routine_wrong_type(respx_mock):
    respx_mock.get(DOC_PATH).respond(json={"@id": "Task/abc", "@type": "Task", "name": "Todo"})
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await log_activity(ctx, "Session", routine_id="Task/abc")

    assert result["ok"] is False
    assert "not a Routine" in result["error"]
    assert not post_route.called


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
