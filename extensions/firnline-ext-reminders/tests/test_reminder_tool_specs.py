"""Tests for ToolSpecPlugin conformance and handler end-to-end for reminder tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from firnline_core.plugins import ToolSpecPlugin, validate_plugin
from firnline_core.tdb import TdbClient
from firnline_core.toolspec import ToolContext

from firnline_ext_reminders.tools import (
    plugin as r_plugin,
    _remindable_cache,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"

DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"

SCHEMA_REMINDABLE = [
    {"@id": "Task", "@inherits": ["Remindable"]},
    {"@id": "Event", "@inherits": ["Remindable"]},
    {"@id": "InboxNote", "@inherits": ["Document"]},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Module-level _remindable_cache leaks between tests — clear it."""
    _remindable_cache.clear()


def _tdb_client() -> TdbClient:
    return TdbClient(base_url=TDB_URL, org=ORG, db=TDB_DB, user="admin", password="pw", author="service:queryd")


# ---------------------------------------------------------------------------
# Plugin conformance
# ---------------------------------------------------------------------------


def test_plugin_satisfies_toolspec_protocol():
    """The plugin object passes isinstance check against ToolSpecPlugin."""
    assert isinstance(r_plugin, ToolSpecPlugin)
    violations = validate_plugin(r_plugin, ToolSpecPlugin)
    assert violations == [], f"ToolSpecPlugin violations: {violations}"


def test_tool_specs_returns_create_reminder():
    """tool_specs() returns a single ToolSpec for create_reminder."""
    specs = r_plugin.tool_specs()
    names = {s.name for s in specs}
    assert names == {"create_reminder"}
    assert len(specs) == 1


def test_create_reminder_input_schema():
    spec = r_plugin.tool_specs()[0]
    schema = spec.input_schema
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"name"}
    props = set(schema["properties"].keys())
    assert "description" in props
    assert "refers_to_iri" in props


# ---------------------------------------------------------------------------
# Handler tests — create_reminder (no refers_to_iri)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_reminder_no_refers_to(respx_mock):
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Reminder/r1"],
    )
    spec = r_plugin.tool_specs()[0]
    args = spec.args_model(name="Buy milk", description="don't forget")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "terminusdb:///data/Reminder/r1"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["@type"] == "Reminder"
    assert doc["name"] == "Buy milk"
    assert doc["description"] == "don't forget"
    assert doc["provenance"]["agent"] == "ext:reminders"


# ---------------------------------------------------------------------------
# Handler tests — create_reminder (valid refers_to_iri)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_reminder_with_valid_refers_to(respx_mock):
    target = {"@id": "Task/abc", "@type": "Task", "name": "Some task"}
    respx_mock.get(DOC_PATH).respond(json=target)
    post_route = respx_mock.post(DOC_PATH).respond(
        json=["terminusdb:///data/Reminder/r2"],
    )

    tdb = _tdb_client()
    tdb.get_schema = AsyncMock(return_value=SCHEMA_REMINDABLE)

    spec = r_plugin.tool_specs()[0]
    args = spec.args_model(name="Follow up", refers_to_iri="Task/abc")
    ctx = ToolContext(tdb=tdb, branch="main")

    result = await spec.handler(args, ctx)

    assert result == {"ok": True, "iri": "terminusdb:///data/Reminder/r2"}
    assert post_route.called

    req = post_route.calls.last.request
    sent = json.loads(req.read())
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["refers_to"] == "Task/abc"
    assert doc["provenance"]["agent"] == "ext:reminders"


# ---------------------------------------------------------------------------
# Handler tests — create_reminder (refers_to_iri 404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_reminder_refers_to_404(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="nope")
    post_route = respx_mock.post(DOC_PATH).respond(json=[])

    spec = r_plugin.tool_specs()[0]
    args = spec.args_model(name="Nope", refers_to_iri="Task/ghost")
    ctx = ToolContext(tdb=_tdb_client(), branch="main")

    result = await spec.handler(args, ctx)

    assert result["ok"] is False
    assert "document not found" in result["error"]
    assert not post_route.called
