"""Tests for queryd.tools — agent tool layer over TerminusDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from firnline_core.tdb import TdbClient
from queryd.settings import Settings
from queryd.tools import (
    QuerydDeps,
    ToolTraceEntry,
    _STRIP_PATTERN,
    _check_graphql,
    build_tools,
    get_document,
    graphql_query,
    today,
)
# Write-tool plugin imports are now from extension packages (tested there).
# queryd only tests host-level integration via fixture plugins that import
# from firnline_ext_planning / firnline_ext_reminders as dev-deps.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"

DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"
GQL_PATH = f"{TDB_URL}/api/graphql/{ORG}/{TDB_DB}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    defaults: dict[str, object] = dict(
        api_token="test-token",
        tdb_db=TDB_DB,
        tdb_password="x",
        llm_base_url="http://llm.test",
        llm_api_key="sk-test",
        llm_model="test-model",
        tdb_url=TDB_URL,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_ctx(
    tdb: TdbClient | None = None,
    settings: Settings | None = None,
    schema_summary: str = "dummy schema summary",
    trace: list[ToolTraceEntry] | None = None,
) -> RunContext[QuerydDeps]:
    """Build a minimal RunContext with QuerydDeps for testing."""
    if tdb is None:
        tdb = TdbClient(
            base_url=TDB_URL, org=ORG, db=TDB_DB, user="admin", password="pw"
        )
    if settings is None:
        settings = _settings()
    deps = QuerydDeps(
        tdb=tdb,
        settings=settings,
        schema_summary=schema_summary,
        trace=trace if trace is not None else [],
    )
    fake_model = MagicMock()
    fake_usage = MagicMock()
    return RunContext(deps=deps, model=fake_model, usage=fake_usage)


async def _aclose_tdb(tdb: TdbClient) -> None:
    try:
        await tdb.aclose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# build_tools
# ---------------------------------------------------------------------------


def test_build_tools_no_writes():
    s = _settings(enable_writes=False)
    tools = build_tools(s)
    names = {t.name for t in tools}
    assert names == {"get_schema_details", "graphql_query", "get_document", "today"}


def test_build_tools_with_writes():
    s = _settings(enable_writes=True)
    from firnline_ext_planning.tools import plugin as _planning_plugin
    from firnline_ext_reminders.tools import plugin as _reminder_plugin
    plugin_tools = _planning_plugin.tools(deps=None) + _reminder_plugin.tools(deps=None)
    tools = build_tools(s, plugin_tools=plugin_tools)
    names = {t.name for t in tools}
    assert names == {
        "get_schema_details",
        "graphql_query",
        "get_document",
        "today",
        "set_task_status",
        "set_event_status",
        "create_task",
        "create_reminder",
        "update_task",
    }


# ---------------------------------------------------------------------------
# get_schema_details
# ---------------------------------------------------------------------------


async def test_get_schema_details_returns_summary():
    from queryd.tools import get_schema_details as _fn

    ctx = _make_ctx(schema_summary="the full schema")
    result = await _fn(ctx)
    assert result == "the full schema"
    assert len(ctx.deps.trace) == 1
    assert ctx.deps.trace[0].tool == "get_schema_details"


# ---------------------------------------------------------------------------
# graphql_query
# ---------------------------------------------------------------------------


async def test_graphql_query_happy_path(respx_mock):
    respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "terminusdb:///data/Task/abc"}]}},
    )
    ctx = _make_ctx()
    result = await graphql_query(ctx, "{ Task { _id } }")

    parsed = json.loads(result)
    assert parsed["Task"][0]["_id"] == "terminusdb:///data/Task/abc"
    assert len(ctx.deps.trace) == 1


async def test_graphql_query_mutation_rejected(respx_mock):
    """Mutation keyword is rejected BEFORE any HTTP call."""
    route = respx_mock.post(GQL_PATH).respond(json={"data": {}})
    ctx = _make_ctx()
    result = await graphql_query(ctx, "mutation { _insertDocuments(doc:{}) }")
    assert "prohibited keyword" in result
    assert not route.called


async def test_graphql_query_subscription_rejected(respx_mock):
    route = respx_mock.post(GQL_PATH).respond(json={"data": {}})
    ctx = _make_ctx()
    result = await graphql_query(ctx, "subscription { ... }")
    assert "prohibited keyword" in result
    assert not route.called


async def test_graphql_query_delete_documents_bare_rejected(respx_mock):
    """Bare _deleteDocuments mention without mutation keyword is caught."""
    route = respx_mock.post(GQL_PATH).respond(json={"data": {}})
    ctx = _make_ctx()
    result = await graphql_query(ctx, 'query { _deleteDocuments(id:"x") { _id } }')
    assert "prohibited function" in result
    assert not route.called


async def test_graphql_query_mutation_inside_comment_allowed(respx_mock):
    """mutation keyword inside a #-comment is stripped and allowed."""
    route = respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "Task/1"}]}},
    )
    ctx = _make_ctx()
    result = await graphql_query(
        ctx,
        "# this query has mutation in a comment\nquery { Task { _id } }",
    )
    assert route.called
    parsed = json.loads(result)
    assert parsed["Task"][0]["_id"] == "Task/1"


async def test_graphql_query_mutation_inside_string_allowed(respx_mock):
    """The word 'mutation' inside a string literal is stripped and allowed."""
    route = respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "Task/2"}]}},
    )
    ctx = _make_ctx()
    result = await graphql_query(
        ctx,
        'query { Task(filter: { name: { eq: "some mutation" } }) { _id } }',
    )
    assert route.called
    parsed = json.loads(result)
    assert parsed["Task"][0]["_id"] == "Task/2"


async def test_graphql_query_mutation_after_comment_strip_caught(respx_mock):
    """Leading comment with mutation keyword doesn't hide a real mutation."""
    route = respx_mock.post(GQL_PATH).respond(json={"data": {}})
    ctx = _make_ctx()
    result = await graphql_query(
        ctx,
        "# this comment mentions mutation\n"
        "mutation { _insertDocuments(doc: {}) { _id } }",
    )
    assert "prohibited keyword" in result
    assert not route.called


async def test_graphql_query_truncation(respx_mock):
    """Response >50KB is truncated with a marker."""
    respx_mock.post(GQL_PATH).respond(
        json={"data": {"big": "x" * 52_000}},
    )
    ctx = _make_ctx()
    result = await graphql_query(ctx, "{ big }")
    assert result.endswith(
        "\n\u2026[TRUNCATED: response exceeded 50000 chars;"
        " refine your query with limit/filter]"
    )
    assert len(result) < 51_500


async def test_graphql_query_server_error_returned_as_text(respx_mock):
    """GraphQL errors from server are returned as error text."""
    respx_mock.post(GQL_PATH).respond(
        status_code=200,
        json={"data": None, "errors": [{"message": "Field does not exist"}]},
    )
    ctx = _make_ctx()
    result = await graphql_query(ctx, "{ BadField }")
    assert "TdbError" in result
    assert "Field does not exist" in result


async def test_graphql_query_timeout_error_string(monkeypatch, respx_mock):
    """Use a very short timeout to trigger the timeout error string."""
    import asyncio

    import httpx

    async def slow(_request):
        await asyncio.sleep(999)
        return httpx.Response(200, json={"data": {}})

    respx_mock.post(GQL_PATH).mock(side_effect=slow)

    # Override asyncio.timeout to be extremely short
    original = asyncio.timeout

    def fake_timeout(secs):
        return original(0.001)  # 1ms

    monkeypatch.setattr(asyncio, "timeout", fake_timeout)

    ctx = _make_ctx()
    result = await graphql_query(ctx, "{ Task { _id } }")
    assert "timed out" in result.lower()


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


async def test_get_document_happy_path(respx_mock):
    doc = {"@id": "Task/abc", "@type": "Task", "name": "Test"}
    respx_mock.get(DOC_PATH).respond(json=doc)
    ctx = _make_ctx()
    result = await get_document(ctx, "Task/abc")
    parsed = json.loads(result)
    assert parsed["@id"] == "Task/abc"


async def test_get_document_404(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404, text="not found")
    ctx = _make_ctx()
    result = await get_document(ctx, "Task/nope")
    assert "document not found" in result


# ---------------------------------------------------------------------------
# today
# ---------------------------------------------------------------------------


async def test_today_contains_weekday_and_iso_week():
    ctx = _make_ctx()
    result = await today(ctx)
    # Contains ISO format datetime
    assert result.startswith("20")
    # Contains weekday name
    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    assert any(w in result for w in weekdays)
    # Contains ISO week
    assert "ISO week" in result
    # Contains timezone
    assert "Europe/Zurich" in result
    # Contains a tz offset (+01:00 or +02:00)
    assert "+01:00" in result or "+02:00" in result


# ---------------------------------------------------------------------------
# _check_graphql edge cases
# ---------------------------------------------------------------------------


def test_check_graphql_clean():
    assert _check_graphql("{ Task { _id name } }") is None


def test_check_graphql_query_keyword_ignored():
    """The word 'query' (operation type) is fine."""
    assert _check_graphql("query { Task { _id } }") is None


def test_check_graphql_mutation_word_in_string_ok():
    assert (
        _check_graphql(
            '{ InboxNote(filter: { content: { eq: "mutation observed" } }) { _id } }'
        )
        is None
    )


def test_check_graphql_mutation_in_comment_ok():
    assert _check_graphql("# a mutation here would be bad\n{ Task { _id } }") is None


def test_strip_pattern_removes_strings_and_comments():
    q = """# comment line
    query {
        Task(filter: { name: { eq: "mutation inside string" } }) {
            _id
            # inline comment
            name
        }
    }"""
    stripped = _STRIP_PATTERN.sub(" ", q)
    assert "mutation" not in stripped
    assert "comment" not in stripped
    assert "Task" in stripped


def test_check_graphql_mutation_at_document_start_rejected():
    """mutation keyword at start of document is rejected."""
    assert "prohibited keyword" in _check_graphql("mutation { _deleteDocuments(x:1) }")


def test_check_graphql_mutation_after_newline_rejected():
    """mutation after leading whitespace is rejected."""
    assert "prohibited keyword" in _check_graphql("  \n mutation Foo { x }")


def test_check_graphql_mutation_after_other_operation_rejected():
    """mutation after query in same document is rejected."""
    assert "prohibited keyword" in _check_graphql("query A { x } mutation B { y }")


def test_check_graphql_mutation_as_alias_allowed():
    """mutation used as a field alias is allowed."""
    assert _check_graphql("{ mutation: Task { _id } }") is None


def test_check_graphql_mutation_as_operation_name_allowed():
    """mutation used as operation name (query mutation { ... }) is allowed."""
    assert _check_graphql("query mutation { Task { _id } }") is None


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


async def test_trace_entry_recorded(respx_mock):
    """Every tool call records exactly one ToolTraceEntry."""
    respx_mock.get(DOC_PATH).respond(
        json={"@id": "Task/abc", "@type": "Task", "name": "X"}
    )
    trace: list[ToolTraceEntry] = []
    ctx = _make_ctx(trace=trace)
    await get_document(ctx, "Task/abc")

    assert len(trace) == 1
    entry = trace[0]
    assert entry.tool == "get_document"
    assert "iri" in entry.input
    assert entry.input["iri"] == "Task/abc"
    assert "chars" in entry.output_summary


async def test_trace_long_values_truncated(respx_mock):
    """Input values >200 chars are truncated."""
    respx_mock.get(DOC_PATH).respond(json={"@id": "Task/x", "@type": "Task"})
    ctx = _make_ctx()
    long_str = "x" * 300
    await get_document(ctx, long_str)
    entry = ctx.deps.trace[0]
    assert len(str(entry.input["iri"])) <= 204  # 200 + "…"
    assert str(entry.input["iri"]).endswith("\u2026")


async def test_trace_output_summary_on_error(respx_mock):
    respx_mock.get(DOC_PATH).respond(status_code=404)
    ctx = _make_ctx()
    await get_document(ctx, "Task/nope")
    entry = ctx.deps.trace[0]
    assert entry.output_summary.startswith("error: ")
    assert "document not found" in entry.output_summary
