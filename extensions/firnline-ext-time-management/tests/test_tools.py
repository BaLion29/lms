"""Tests for firnline_ext_time_management.tools — time-management write tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from firnline_core.tdb import TdbClient
from firnline_ext_time_management.tools import (
    assign_contexts,
    create_area,
    create_goal,
    create_project,
    create_routine,
    create_task,
    log_activity,
    plugin as tm_plugin,
    remove_contexts,
    set_event_status,
    set_goal_status,
    set_project_status,
    set_task_status,
    update_project,
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
    assert reqs[0].range == ">=0.2.0 <0.3.0"


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
        "create_project",
        "update_project",
        "set_project_status",
        "create_goal",
        "set_goal_status",
        "create_area",
        "assign_contexts",
        "remove_contexts",
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


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


async def test_create_project_happy_path(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Project/proj1"],
    )
    ctx = _make_ctx()
    result = await create_project(ctx, "My Project")

    assert result == {"ok": True, "iri": "terminusdb:///data/Project/proj1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Project"
    assert doc["name"] == "My Project"
    assert doc["status"] == "active"
    assert "created_at" in doc
    assert "updated_at" in doc
    assert doc["provenance"]["agent"] == "ext:time-management"
    assert doc["provenance"]["method"] == "tool_call"


async def test_create_project_with_all_fields(respx_mock):
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Project/p2"])
    ctx = _make_ctx()
    result = await create_project(
        ctx,
        "Complex Project",
        description="A detailed project",
        target_date="2026-12-31T12:00:00Z",
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Complex Project"
    assert doc["description"] == "A detailed project"
    assert doc["target_date"] == "2026-12-31T12:00:00Z"
    assert doc["status"] == "active"


# ---------------------------------------------------------------------------
# update_project
# ---------------------------------------------------------------------------


async def test_update_project_only_provided_fields_changed(respx_mock):
    orig = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "Old Project",
        "description": "Old desc",
        "status": "active",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Project/p1"])

    ctx = _make_ctx()
    result = await update_project(ctx, "Project/p1", name="New Project")

    assert result == {"ok": True, "iri": "Project/p1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "New Project"
    assert doc["description"] == "Old desc"
    assert doc["status"] == "active"
    assert doc["updated_at"] != orig["updated_at"]


async def test_update_project_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)
    ctx = _make_ctx()
    result = await update_project(ctx, "Project/nope")
    assert result["ok"] is False
    assert "document not found" in result["error"]


async def test_update_project_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)

    ctx = _make_ctx()
    result = await update_project(ctx, "Task/abc", name="Not a project")
    assert result["ok"] is False
    assert "not a Project" in result["error"]


# ---------------------------------------------------------------------------
# set_project_status
# ---------------------------------------------------------------------------


async def test_set_project_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "My Project",
        "status": "active",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Project/p1"])

    ctx = _make_ctx()
    result = await set_project_status(ctx, "Project/p1", "on_hold")

    assert result == {"ok": True, "iri": "Project/p1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    updated_doc = sent[0]
    assert updated_doc["status"] == "on_hold"


async def test_set_project_status_on_hold_to_active(respx_mock):
    orig_doc = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "My Project",
        "status": "on_hold",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Project/p1"])

    ctx = _make_ctx()
    result = await set_project_status(ctx, "Project/p1", "active")

    assert result == {"ok": True, "iri": "Project/p1"}
    assert post_route.called


async def test_set_project_status_illegal_transition(respx_mock):
    """on_hold -> completed is illegal (only active is allowed from on_hold)."""
    orig_doc = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "My Project",
        "status": "on_hold",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Project/p1"])

    ctx = _make_ctx()
    result = await set_project_status(ctx, "Project/p1", "completed")

    assert result["ok"] is False
    assert "Illegal transition" in result["error"]
    assert not post_route.called


async def test_set_project_status_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    ctx = _make_ctx()
    result = await set_project_status(ctx, "Project/nope", "active")
    assert result["ok"] is False
    assert "document not found" in result["error"]


async def test_set_project_status_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await set_project_status(ctx, "Task/abc", "on_hold")
    assert result["ok"] is False
    assert "not a Project" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# create_goal
# ---------------------------------------------------------------------------


async def test_create_goal_happy_path(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Goal/g1"],
    )
    ctx = _make_ctx()
    result = await create_goal(ctx, "Learn Rust")

    assert result == {"ok": True, "iri": "terminusdb:///data/Goal/g1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Goal"
    assert doc["name"] == "Learn Rust"
    assert doc["status"] == "active"
    assert "created_at" in doc
    assert doc["provenance"]["agent"] == "ext:time-management"


async def test_create_goal_with_all_fields(respx_mock):
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Goal/g2"])
    ctx = _make_ctx()
    result = await create_goal(
        ctx,
        "Complex Goal",
        description="Goal description",
        success_criteria="Did the thing",
        target_date="2026-12-31T12:00:00Z",
    )
    assert result["ok"] is True

    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Complex Goal"
    assert doc["description"] == "Goal description"
    assert doc["success_criteria"] == "Did the thing"
    assert doc["target_date"] == "2026-12-31T12:00:00Z"
    assert doc["status"] == "active"


# ---------------------------------------------------------------------------
# set_goal_status
# ---------------------------------------------------------------------------


async def test_set_goal_status_happy_path(respx_mock):
    orig_doc = {
        "@id": "Goal/g1",
        "@type": "Goal",
        "name": "Learn Rust",
        "status": "active",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Goal/g1"])

    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Goal/g1", "achieved")

    assert result == {"ok": True, "iri": "Goal/g1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    updated_doc = sent[0]
    assert updated_doc["status"] == "achieved"


async def test_set_goal_status_abandoned_to_active(respx_mock):
    orig_doc = {
        "@id": "Goal/g1",
        "@type": "Goal",
        "name": "Old goal",
        "status": "abandoned",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Goal/g1"])

    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Goal/g1", "active")

    assert result == {"ok": True, "iri": "Goal/g1"}
    assert post_route.called


async def test_set_goal_status_illegal_transition(respx_mock):
    """abandoned -> achieved is illegal (only active is allowed from abandoned)."""
    orig_doc = {
        "@id": "Goal/g1",
        "@type": "Goal",
        "name": "Goal",
        "status": "abandoned",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Goal/g1"])

    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Goal/g1", "achieved")

    assert result["ok"] is False
    assert "Illegal transition" in result["error"]
    assert not post_route.called


async def test_set_goal_status_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Goal/nope", "active")
    assert result["ok"] is False
    assert "document not found" in result["error"]


async def test_set_goal_status_wrong_type(respx_mock):
    task_doc = {"@id": "Task/abc", "@type": "Task", "name": "Todo"}
    respx_mock.get(DOC_PATH).respond(json=task_doc)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Task/abc", "achieved")
    assert result["ok"] is False
    assert "not a Goal" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# create_area
# ---------------------------------------------------------------------------


async def test_create_area_happy_path(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Area/a1"],
    )
    ctx = _make_ctx()
    result = await create_area(ctx, "Health")

    assert result == {"ok": True, "iri": "terminusdb:///data/Area/a1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Area"
    assert doc["name"] == "Health"
    assert "created_at" in doc
    assert doc["provenance"]["agent"] == "ext:time-management"


async def test_create_area_with_description(respx_mock):
    respx_mock.post(DOC_PATH).respond(json=["terminusdb:///data/Area/a2"])
    ctx = _make_ctx()
    result = await create_area(ctx, "Finance", description="Money matters")

    assert result["ok"] is True
    req = respx_mock.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Finance"
    assert doc["description"] == "Money matters"


async def test_create_area_duplicate_name(respx_mock):
    """When an Area with the same lexical key already exists, report the error."""
    respx_mock.post(DOC_PATH).respond(
        status_code=400,
        json={"@type": "api:ErrorResponse",
              "api:status": "api:failure",
              "api:message": "Duplicate key: Area/Health"},
    )
    ctx = _make_ctx()
    result = await create_area(ctx, "Health")

    assert result["ok"] is False
    assert "Duplicate" in result["error"] or "Duplicate key" in result["error"]


# ---------------------------------------------------------------------------
# assign_contexts
# ---------------------------------------------------------------------------


async def test_assign_contexts_happy_path(respx_mock):
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Review PR",
        "status": "open",
        "contexts": [],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    project_doc = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "Q3 Release",
        "status": "active",
    }

    respx_mock.get(DOC_PATH, params={"id": "Task/abc"}).respond(json=dict(task_doc))
    respx_mock.get(DOC_PATH, params={"id": "Project/p1"}).respond(json=dict(project_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await assign_contexts(ctx, "Task/abc", ["Project/p1"])

    assert result == {"ok": True, "iri": "Task/abc"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert "Project/p1" in doc["contexts"]


async def test_assign_contexts_dedupe(respx_mock):
    """Adding an already-present context IRI should not duplicate it."""
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Task",
        "status": "open",
        "contexts": ["Project/p1", "Area/a1"],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    ctx_doc = {"@id": "Area/a1", "@type": "Area", "name": "Health"}

    respx_mock.get(DOC_PATH, params={"id": "Task/abc"}).respond(json=dict(task_doc))
    respx_mock.get(DOC_PATH, params={"id": "Area/a1"}).respond(json=dict(ctx_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await assign_contexts(ctx, "Task/abc", ["Area/a1"])

    assert result["ok"] is True
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["contexts"] == ["Project/p1", "Area/a1"]  # No duplicate


async def test_assign_contexts_context_not_found(respx_mock):
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Task",
        "status": "open",
        "contexts": [],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH, params={"id": "Task/abc"}).respond(json=dict(task_doc))
    respx_mock.get(DOC_PATH, params={"id": "Project/missing"}).respond(status_code=404)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await assign_contexts(ctx, "Task/abc", ["Project/missing"])

    assert result["ok"] is False
    assert "context document not found" in result["error"]
    assert not post_route.called


async def test_assign_contexts_entity_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    ctx = _make_ctx()
    result = await assign_contexts(ctx, "Task/nope", ["Project/p1"])
    assert result["ok"] is False
    assert "document not found" in result["error"]


async def test_assign_contexts_wrong_type(respx_mock):
    """Entity without a contexts field (e.g. RoutineStep) should be rejected."""
    doc = {"@id": "RoutineStep/1", "@type": "RoutineStep", "name": "Step"}
    respx_mock.get(DOC_PATH).respond(json=dict(doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await assign_contexts(ctx, "RoutineStep/1", ["Project/p1"])
    assert result["ok"] is False
    assert "does not support contexts" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# remove_contexts
# ---------------------------------------------------------------------------


async def test_remove_contexts_happy_path(respx_mock):
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Task",
        "status": "open",
        "contexts": ["Project/p1", "Area/a1"],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(task_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await remove_contexts(ctx, "Task/abc", ["Project/p1"])

    assert result == {"ok": True, "iri": "Task/abc"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["contexts"] == ["Area/a1"]
    assert "Project/p1" not in doc["contexts"]


async def test_remove_contexts_non_present_iri(respx_mock):
    """Removing an IRI not in contexts should silently succeed."""
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Task",
        "status": "open",
        "contexts": ["Project/p1"],
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(task_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    ctx = _make_ctx()
    result = await remove_contexts(ctx, "Task/abc", ["Project/missing"])

    assert result["ok"] is True
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["contexts"] == ["Project/p1"]


async def test_remove_contexts_entity_not_found(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    ctx = _make_ctx()
    result = await remove_contexts(ctx, "Task/nope", ["Project/p1"])
    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# assign_contexts / remove_contexts — archived guard
# ---------------------------------------------------------------------------


async def test_assign_contexts_archived_document_rejected(respx_mock):
    """Assigning contexts to an archived document should fail."""
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Old task",
        "status": "open",
        "contexts": [],
        "archived_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(task_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await assign_contexts(ctx, "Task/abc", ["Project/p1"])

    assert result["ok"] is False
    assert "archived" in result["error"]
    assert not post_route.called


async def test_remove_contexts_archived_document_rejected(respx_mock):
    """Removing contexts from an archived document should fail."""
    task_doc = {
        "@id": "Task/abc",
        "@type": "Task",
        "name": "Old task",
        "status": "open",
        "contexts": ["Project/p1"],
        "archived_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(task_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await remove_contexts(ctx, "Task/abc", ["Project/p1"])

    assert result["ok"] is False
    assert "archived" in result["error"]
    assert not post_route.called


# ---------------------------------------------------------------------------
# set_project_status / set_goal_status — terminal state guard
# ---------------------------------------------------------------------------


async def test_set_project_status_completed_is_terminal(respx_mock):
    """completed -> active should be rejected at the tool level."""
    orig_doc = {
        "@id": "Project/p1",
        "@type": "Project",
        "name": "Done Project",
        "status": "completed",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Project/p1"])

    ctx = _make_ctx()
    result = await set_project_status(ctx, "Project/p1", "active")

    assert result["ok"] is False
    assert "terminal" in result["error"]
    assert not post_route.called


async def test_set_goal_status_achieved_is_terminal(respx_mock):
    """achieved -> active should be rejected at the tool level."""
    orig_doc = {
        "@id": "Goal/g1",
        "@type": "Goal",
        "name": "Achieved Goal",
        "status": "achieved",
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-01T10:00:00Z",
    }
    respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Goal/g1"])

    ctx = _make_ctx()
    result = await set_goal_status(ctx, "Goal/g1", "active")

    assert result["ok"] is False
    assert "terminal" in result["error"]
    assert not post_route.called
