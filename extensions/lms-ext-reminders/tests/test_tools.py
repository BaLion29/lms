"""Tests for lms_ext_reminders.tools — create_reminder tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from lms_core.tdb import TdbClient
from lms_ext_reminders.tools import (
    create_reminder,
    plugin as reminder_plugin,
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
    tdb_branch = "main"
    max_tool_iterations = 50
    enable_writes = True


class _FakeDeps:
    def __init__(self, tdb):
        self.tdb = tdb
        self.settings = _FakeSettings()
        self.trace: list[object] = []
        self.tool_calls_used = 0
        self.prompt_briefing = ""
        self.schema_summary = "dummy schema"


def _make_ctx(tdb: TdbClient | None = None) -> RunContext:
    if tdb is None:
        tdb = TdbClient(
            base_url=TDB_URL, org=ORG, db=TDB_DB, user="admin", password="pw"
        )
    deps = _FakeDeps(tdb)
    fake_model = MagicMock()
    fake_usage = MagicMock()
    return RunContext(deps=deps, model=fake_model, usage=fake_usage)


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


def test_plugin_name_and_requires():
    assert reminder_plugin.name == "reminder_tools"
    reqs = reminder_plugin.requires
    assert len(reqs) == 1
    assert reqs[0].name == "reminders"
    assert reqs[0].range == ">=1.0.0 <2.0.0"


def test_plugin_tools():
    tools = reminder_plugin.tools(deps=None)
    tool_names = {t.name for t in tools}
    assert tool_names == {"create_reminder"}


# ---------------------------------------------------------------------------
# create_reminder
# ---------------------------------------------------------------------------


async def test_create_reminder_no_refers_to(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Reminder/r1"],
    )
    ctx = _make_ctx()
    result = await create_reminder(ctx, "Buy milk", description="don't forget")

    assert result == {"ok": True, "iri": "Reminder/r1"}
    assert post_route.called
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Reminder"
    assert doc["name"] == "Buy milk"
    assert doc["description"] == "don't forget"
    assert doc.get("refers_to") is None or "refers_to" not in doc


async def test_create_reminder_with_valid_refers_to(respx_mock):
    target = {"@id": "Task/abc", "@type": "Task", "name": "Some task"}
    get_route = respx_mock.get(DOC_PATH).respond(json=target)
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Reminder/r2"],
    )

    ctx = _make_ctx()
    result = await create_reminder(ctx, "Follow up", refers_to_iri="Task/abc")

    assert result == {"ok": True, "iri": "Reminder/r2"}
    assert get_route.called
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["refers_to"] == "Task/abc"


async def test_create_reminder_refers_to_404_no_insert(respx_mock):
    get_route = respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await create_reminder(ctx, "Nope", refers_to_iri="Task/ghost")

    assert result["ok"] is False
    assert "document not found" in result["error"]
    assert get_route.called
    assert not post_route.called


async def test_create_reminder_refers_to_wrong_type(respx_mock):
    target = {"@id": "InboxNote/x", "@type": "InboxNote", "content": "nope"}
    respx_mock.get(DOC_PATH).respond(json=target)
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    ctx = _make_ctx()
    result = await create_reminder(ctx, "Nope", refers_to_iri="InboxNote/x")

    assert result["ok"] is False
    assert "expected Task or Event" in result["error"]
    assert not post_route.called
