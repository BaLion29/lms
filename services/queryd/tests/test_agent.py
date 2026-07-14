"""Tests for queryd.agent — agent construction, system prompt, iteration cap."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from firnline_core.tdb import TdbClient
from queryd.agent import build_agent, usage_limits
from queryd.settings import Settings
from queryd.tools import QuerydDeps, build_tools
from firnline_ext_planning.tools import plugin as _planning_plugin
from firnline_ext_reminders.tools import plugin as _reminder_plugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    defaults: dict[str, object] = dict(
        api_token="test-token",
        tdb_db="testdb",
        tdb_password="x",
        llm_base_url="http://llm.test/v1",
        llm_api_key="sk-test",
        llm_model="test-model",
        tdb_url="http://tdb.test",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _deps(**overrides) -> QuerydDeps:
    tdb = MagicMock(spec=TdbClient)
    kwargs: dict[str, object] = dict(
        tdb=tdb,
        settings=_settings(),
        schema_summary="dummy schema",
        prompt_briefing="DUMMY_BRIEFING_MARKER",
    )
    kwargs.update(overrides)
    return QuerydDeps(**kwargs)  # type: ignore[arg-type]


def _make_all_tools(s: Settings, plugin_tools=None):
    """Build the full tool list (read + plugin)."""
    return build_tools(s, plugin_tools=plugin_tools)


# ---------------------------------------------------------------------------
# build_agent
# ---------------------------------------------------------------------------


def test_build_agent_constructs():
    """build_agent returns an Agent[QuerydDeps, str] without error."""
    s = _settings()
    agent = build_agent(s)
    assert isinstance(agent, Agent)


def test_build_agent_read_tools_only_when_writes_disabled():
    """With enable_writes=False, only the 7 read tools are registered."""
    s = _settings(enable_writes=False)
    agent = build_agent(s)
    tool_names = set(agent._function_toolset.tools.keys())
    assert tool_names == {
        "get_schema_details",
        "graphql_query",
        "get_document",
        "today",
        "find_entity",
        "find_class",
        "find_field",
    }


def test_build_agent_all_12_tools_when_writes_enabled():
    """With enable_writes=True and plugin tools passed, all 12 tools are registered."""
    s = _settings(enable_writes=True)
    plugin_tools = _planning_plugin.tools(deps=None) + _reminder_plugin.tools(deps=None)
    agent = build_agent(s, tools=_make_all_tools(s, plugin_tools))
    tool_names = set(agent._function_toolset.tools.keys())
    assert len(tool_names) == 12
    assert tool_names == {
        "get_schema_details",
        "graphql_query",
        "get_document",
        "today",
        "find_entity",
        "find_class",
        "find_field",
        "set_task_status",
        "set_event_status",
        "create_task",
        "create_reminder",
        "update_task",
    }


def test_build_agent_temperature_zero():
    """Model settings include temperature=0."""
    s = _settings()
    agent = build_agent(s)
    # The model is stored internally; we can check via the agent's model
    model = agent._model
    # ModelSettings is a TypedDict; temperature should be accessible
    ms = model.settings
    assert ms is not None
    assert ms.get("temperature") == 0


# ---------------------------------------------------------------------------
# usage_limits
# ---------------------------------------------------------------------------


def test_usage_limits_request_limit():
    s = _settings(max_tool_iterations=8)
    limits = usage_limits(s)
    assert limits.request_limit == 11  # 8 + 3


def test_usage_limits_custom_iterations():
    s = _settings(max_tool_iterations=5)
    limits = usage_limits(s)
    assert limits.request_limit == 8  # 5 + 3


# ---------------------------------------------------------------------------
# Dynamic system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dynamic_system_prompt_contains_date_and_briefing():
    """The per-request system prompt contains Europe/Zurich date + briefing marker."""
    s = _settings()
    agent = build_agent(s)

    deps = _deps()

    # Use TestModel to let the agent do its thing (it calls tools by default).
    # We only need to check what the system prompt content is.
    # The TestModel calls all tools and returns a response.
    with agent.override(model=TestModel()):
        result = await agent.run("hello", deps=deps)

    # Check that system prompt messages contain our markers.
    system_texts: list[str] = []
    for msg in result.all_messages():
        if hasattr(msg, "parts"):
            for part in msg.parts:
                if hasattr(part, "content"):
                    system_texts.append(part.content)

    combined = "\n".join(system_texts)
    assert "Europe/Zurich" in combined
    assert "DUMMY_BRIEFING_MARKER" in combined
    # Should also contain the current year
    from datetime import datetime

    assert str(datetime.now().year) in combined


# ---------------------------------------------------------------------------
# Soft iteration cap
# ---------------------------------------------------------------------------

# Number of extra requests the FunctionModel makes before giving a final answer
# (one per tool call the agent makes, plus the final answer).
# The FunctionModel we write below will loop through graphql_query calls.

_BUDGET_MSG = "Tool-call budget exhausted. Answer the user now with the information you already have."


@pytest.mark.asyncio
async def test_soft_cap_stops_after_max_tool_iterations(respx_mock):
    """After max_tool_iterations tool calls, the tool returns budget-exhausted
    and the FunctionModel produces a final answer."""
    MAX = 3
    s = _settings(max_tool_iterations=MAX)

    # Mock the graphql endpoint so it responds (the tool will be called but
    # the soft cap should kick in before the HTTP call for the (MAX+1)th).
    gql_path = f"{s.tdb_url}/api/graphql/{s.tdb_org}/{s.tdb_db}"
    respx_mock.post(gql_path).respond(json={"data": {"Task": [{"_id": "Task/1", "name": "test"}]}})

    # Track how many times the FunctionModel was called
    call_count = [0]

    async def _fn(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        call_count[0] += 1

        # Check if any tool return message contains the budget-exhausted string
        for msg in messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and _BUDGET_MSG in content:
                        return ModelResponse(parts=[TextPart(content="Final answer: budget exceeded.")])

        # Otherwise, call graphql_query
        return ModelResponse(
            parts=[
                TextPart(content="Let me query the database."),
                ToolCallPart(
                    tool_name="graphql_query",
                    args={"query": "{ Task { _id name } }"},
                    tool_call_id=f"call_{call_count[0]}",
                ),
            ]
        )

    agent = build_agent(s)
    deps = _deps(settings=s)

    # Set up deps with a real TdbClient (HTTP mocked via respx)
    from firnline_core.tdb import TdbClient

    tdb = TdbClient(
        base_url=s.tdb_url,
        org=s.tdb_org,
        db=s.tdb_db,
        user=s.tdb_user,
        password=s.tdb_password,
        timeout=10,
        author="service:queryd",
    )
    deps.tdb = tdb

    with agent.override(model=FunctionModel(function=_fn)):
        result = await agent.run("Find tasks", deps=deps)

    # The agent should have completed with the final answer
    assert "budget exceeded" in result.output.lower()

    # Trace should have MAX+1 entries: MAX actual calls (which succeeded) +
    # the refused one.
    # The refused call is ALSO traced.
    assert len(deps.trace) >= MAX + 1

    # The last trace entry should be the exhausted one
    exhausted_entries = [e for e in deps.trace if e.output_summary == "budget exhausted"]
    assert len(exhausted_entries) >= 1

    await tdb.aclose()
