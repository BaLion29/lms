"""Integration tests for the /v1/chat endpoint covering read, write,
timeout, error mapping, history, iteration cap, mutation guard, and
startup resilience.

All tests use ``FunctionModel`` to script the LLM and ``respx`` for
TerminusDB HTTP mocks — no real network or LLM calls.
"""

from __future__ import annotations

import asyncio
import json

import respx
from fastapi.testclient import TestClient

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from queryd.app import create_app
from queryd.settings import Settings
from queryd.tools import ToolTraceEntry
from firnline_ext_planning.tools import plugin as _planning_plugin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"

GQL_PATH = f"{TDB_URL}/api/graphql/{ORG}/{TDB_DB}"
DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"

AUTH = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
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


def _tdb_exists_route() -> str:
    return f"{TDB_URL}/api/db/admin/{TDB_DB}"


def _chat_json(messages: list[dict[str, str]]) -> dict:
    return {"messages": messages}


# ---------------------------------------------------------------------------
# a) Read flow: FunctionModel → graphql_query → final answer
# ---------------------------------------------------------------------------


def test_read_flow_graphql_query_to_final_answer(respx_mock: respx.MockRouter):
    """End-to-end read: model calls graphql_query, gets task data, answers."""
    gql_route = respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "Task": [
                    {"_id": "terminusdb:///data/Task/abc", "name": "Buy groceries"}
                ]
            }
        },
    )
    # DB must exist for healthz in lifespan
    respx_mock.get(_tdb_exists_route()).respond(200)

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        # Check if we already got a tool-result containing task data
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and "Buy groceries" in content:
                        return ModelResponse(
                            parts=[TextPart(content="You have a task: Buy groceries.")]
                        )

        # First call: request graphql_query
        return ModelResponse(
            parts=[
                TextPart(content="Let me query your tasks."),
                ToolCallPart(
                    tool_name="graphql_query",
                    args={"query": "{ Task { _id name } }"},
                    tool_call_id="call_1",
                ),
            ]
        )

    settings = _make_settings()
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "What are my tasks?"}]),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Buy groceries" in data["message"]
    assert gql_route.called

    # tool_trace must contain a graphql_query entry with output_summary
    trace = [ToolTraceEntry(**e) for e in data["tool_trace"]]
    gql_entries = [e for e in trace if e.tool == "graphql_query"]
    assert len(gql_entries) == 1
    assert "chars" in gql_entries[0].output_summary


# ---------------------------------------------------------------------------
# b) Mutation guard e2e: model tries graphql_query with mutation → refused
# ---------------------------------------------------------------------------


def test_mutation_guard_graphql_rejected(respx_mock: respx.MockRouter):
    """Model tries mutation via graphql_query; tool refuses; model answers normally."""
    gql_route = respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and "prohibited" in content:
                        return ModelResponse(
                            parts=[
                                TextPart(content="Cannot execute that mutation, sorry.")
                            ]
                        )

        # First call: attempt a mutation query
        return ModelResponse(
            parts=[
                TextPart(content="Let me delete that document."),
                ToolCallPart(
                    tool_name="graphql_query",
                    args={"query": 'mutation { _deleteDocuments(ids: ["x"]) { _id } }'},
                    tool_call_id="call_1",
                ),
            ]
        )

    settings = _make_settings()
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "Delete task x"}]),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Cannot execute that mutation" in data["message"]
    # Only the startup introspection call should have hit the GQL route;
    # the mutation was blocked before any HTTP call.
    assert gql_route.call_count == 1


# ---------------------------------------------------------------------------
# c) Writes disabled: model only sees read tools, states writes are disabled
# ---------------------------------------------------------------------------


def test_writes_disabled_model_answers_accordingly(respx_mock: respx.MockRouter):
    """enable_writes=False → model only gets read tools and explains write
    mode is disabled."""
    # Mock introspection so startup succeeds
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )
    respx_mock.get(_tdb_exists_route()).respond(200)
    # Mock specific document routes (should NOT be called)
    doc_put = respx_mock.put(DOC_PATH).respond(json=[])
    doc_post = respx_mock.post(DOC_PATH).respond(json=[])

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content="Write mode is disabled; I cannot make changes.")]
        )

    settings = _make_settings(enable_writes=False)
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "Mark task abc as done"}]),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "write mode is disabled" in data["message"].lower()
    # No PUT or POST document requests should have happened
    assert not doc_put.called
    assert not doc_post.called


# ---------------------------------------------------------------------------
# d) Writes enabled e2e: set_task_status → GET + PUT with correct fields
# ---------------------------------------------------------------------------


def test_writes_enabled_set_task_status_e2e(respx_mock: respx.MockRouter):
    """enable_writes=True; model calls set_task_status; GET + PUT with
    correct body and params."""
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
    # Mock introspection (so startup and lazy refetch succeed)
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )
    get_route = respx_mock.get(DOC_PATH).respond(json=dict(orig_doc))
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])
    respx_mock.get(_tdb_exists_route()).respond(200)

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        # Check if set_task_status already returned ok=true
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        if part.tool_name == "set_task_status":
                            content = part.content
                            if isinstance(content, dict) and content.get("ok"):
                                return ModelResponse(
                                    parts=[TextPart(content="Task abc is now done.")]
                                )

        return ModelResponse(
            parts=[
                TextPart(content="I'll mark task abc as done."),
                ToolCallPart(
                    tool_name="set_task_status",
                    args={"task_iri": "Task/abc", "status": "done"},
                    tool_call_id="call_set",
                ),
            ]
        )

    settings = _make_settings(enable_writes=True)
    app = create_app(
        settings,
        model=FunctionModel(function=_fn),
        plugin_tools=_planning_plugin.tools(deps=None),
    )

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "Mark task abc done"}]),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "done" in data["message"].lower()
    assert get_route.called
    assert post_route.called

    # Verify POST body (transition sends [updated_doc, transition_audit_doc])
    req = post_route.calls.last.request
    sent = json.loads(req.read())
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

    # Verify commit params
    params = req.url.params
    assert params["author"] == "service:queryd"
    assert "transition" in params["message"]

    # Trace must contain a set_task_status entry
    trace = [ToolTraceEntry(**e) for e in data["tool_trace"]]
    write_entries = [e for e in trace if e.tool == "set_task_status"]
    assert len(write_entries) == 1
    assert "ok iri" in write_entries[0].output_summary


# ---------------------------------------------------------------------------
# e) Iteration cap e2e: FunctionModel loops until budget exhausted
# ---------------------------------------------------------------------------


def test_iteration_cap_exhausted_tool_budget(respx_mock: respx.MockRouter):
    """max_tool_iterations=3; model loops graphql_query \u22654 times;
    gets budget-exhausted refusal, then answers. Trace = 3 executed + 1
    refusal = 4."""
    gql_route = respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "Task/1", "name": "test"}]}}
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    MAX = 3
    _BUDGET_MSG = (
        "Tool-call budget exhausted. "
        "Answer the user now with the information you already have."
    )

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        # Check if we hit the budget-exhausted message
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and _BUDGET_MSG in content:
                        return ModelResponse(
                            parts=[
                                TextPart(content="Budget exceeded; here is my answer.")
                            ]
                        )

        # Otherwise keep querying
        return ModelResponse(
            parts=[
                TextPart(content="Let me query again."),
                ToolCallPart(
                    tool_name="graphql_query",
                    args={"query": "{ Task { _id name } }"},
                    tool_call_id="cq",
                ),
            ]
        )

    settings = _make_settings(max_tool_iterations=MAX)
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "Find tasks"}]),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Budget exceeded" in data["message"]

    trace = [ToolTraceEntry(**e) for e in data["tool_trace"]]
    # 3 executed + 1 refusal = 4 trace entries
    assert len(trace) == MAX + 1
    exhausted = [e for e in trace if e.output_summary == "budget exhausted"]
    assert len(exhausted) == 1
    # The graphql route should have been called MAX times (for the tool)
    # plus 1 (startup introspection) = MAX + 1
    assert gql_route.call_count == MAX + 1


# ---------------------------------------------------------------------------
# f) Timeout: slow model → 504
# ---------------------------------------------------------------------------


def test_timeout_returns_504_json(respx_mock: respx.MockRouter):
    """FunctionModel sleeps 1s; request_timeout=0.05s → 504."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(1)
        return ModelResponse(parts=[TextPart(content="too late")])

    settings = _make_settings(request_timeout_seconds=0.05)
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "hello"}]),
            headers=AUTH,
        )

    assert resp.status_code == 504
    data = resp.json()
    assert data["detail"] == "request timed out"


# ---------------------------------------------------------------------------
# g) Provider error: model raises ModelHTTPError → 502, no secret leaked
# ---------------------------------------------------------------------------


def test_provider_error_returns_502_no_secrets(respx_mock: respx.MockRouter):
    """Model raises ModelHTTPError → 502, body does NOT contain api key."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    # Mock GQL introspection so lifespan / lazy refetch don't fail
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        # Simulate a provider error
        raise ModelHTTPError(
            status_code=500,
            model_name="test-model",
            body='{"error": "internal server error", "api_key": "sk-leaked"}',
        )

    settings = _make_settings(llm_api_key="sk-test-secret-key")
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "hello"}]),
            headers=AUTH,
        )

    assert resp.status_code == 502
    data = resp.json()
    assert data["detail"] == "llm provider error"
    # Body must NOT contain any API key-like strings
    body_text = resp.text.lower()
    assert "sk-" not in body_text
    assert "api_key" not in body_text
    assert "sk-test-secret-key" not in body_text


# ---------------------------------------------------------------------------
# h) History mapping: user/assistant/user → history + prompt split correctly
# ---------------------------------------------------------------------------


def test_history_mapping_prior_turns_become_history(respx_mock: respx.MockRouter):
    """Send 3 messages (user/assistant/user); FunctionModel sees first two as
    history and the last as prompt."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    seen_messages: list[list[ModelMessage]] = []

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        seen_messages.append(messages)
        return ModelResponse(
            parts=[TextPart(content="I received the history correctly.")]
        )

    settings = _make_settings()
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat",
            json=_chat_json(
                [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi, how can I help?"},
                    {"role": "user", "content": "What are my tasks?"},
                ]
            ),
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "correctly" in data["message"]

    # Verify the messages the model received include the history
    assert len(seen_messages) == 1
    model_msgs = seen_messages[0]

    # Flatten all text content from parts
    all_text: list[str] = []
    for msg in model_msgs:
        if hasattr(msg, "parts"):
            for part in msg.parts:
                content = getattr(part, "content", "")
                if isinstance(content, str):
                    all_text.append(content)

    combined = " ".join(all_text)
    assert "Hello" in combined
    assert "Hi, how can I help?" in combined
    assert "What are my tasks?" in combined


# ---------------------------------------------------------------------------
# i) Startup resilience: introspection fails at startup, lazy refetch works
# ---------------------------------------------------------------------------


def test_startup_resilience_lazy_refetch(respx_mock: respx.MockRouter):
    """Introspection fails at startup → app starts, /healthz works;
    fix route → next /v1/chat refetches and succeeds."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    import httpx

    gql_call_count = [0]

    def _dynamic_gql(request: httpx.Request) -> httpx.Response:
        gql_call_count[0] += 1
        if gql_call_count[0] == 1:
            # startup introspection → fail
            return httpx.Response(
                500,
                json={"error": "introspection failed"},
            )
        else:
            # lazy refetch or tool call → succeed
            return httpx.Response(
                200,
                json={
                    "data": {
                        "__schema": {
                            "queryType": {"name": "Query"},
                            "types": [],
                        }
                    }
                },
            )

    respx_mock.post(GQL_PATH).mock(side_effect=_dynamic_gql)

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Answer after lazy refetch.")])

    settings = _make_settings()
    app = create_app(settings, model=FunctionModel(function=_fn))

    with TestClient(app) as client:
        # 1. Healthz still works despite introspection failure
        r = client.get("/healthz")
        assert r.status_code == 200

        # 2. /v1/chat triggers lazy refetch
        resp = client.post(
            "/v1/chat",
            json=_chat_json([{"role": "user", "content": "hello"}]),
            headers=AUTH,
        )
        assert resp.status_code == 200
        assert "Answer after lazy refetch" in resp.json()["message"]

        # After the chat call, graphQL should have been called at least 2 times
        # (1 = startup fail, 2 = lazy refetch)
        assert gql_call_count[0] >= 2
