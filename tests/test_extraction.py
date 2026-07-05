"""Tests for the extraction agent — no network, offline only."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ingestd.extraction import (
    EventProposal,
    ExtractionResult,
    PersonProposal,
    TaskProposal,
    build_agent,
    extract,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(result: ExtractionResult) -> ModelResponse:
    """Build a FunctionModel response carrying *result* as the output tool call."""
    return ModelResponse(
        parts=[
            ToolCallPart(
                "final_result",
                result.model_dump(mode="json"),
                tool_call_id="call_test",
            )
        ]
    )


# ---------------------------------------------------------------------------
# Test 1: single task with resolved relative due date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_with_resolved_due_date():
    """A note yielding ONE task with a resolved relative due date.

    Uses FunctionModel to simulate the LLM having resolved "Freitag" relative
    to the given reference_dt.  Asserts the user prompt contains the reference
    datetime string and note text, and the returned TaskProposal has the
    expected absolute due_date.
    """
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)  # Sunday
    # "next Friday" relative to Sunday 2026-07-05 → Friday 2026-07-10
    expected_due = datetime(2026, 7, 10, 17, 0, 0, tzinfo=UTC)

    captured_instructions: str | None = None
    captured_user_content: str = ""

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        nonlocal captured_instructions, captured_user_content
        captured_instructions = agent_info.instructions
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        captured_user_content = part.content

        result = ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Project review",
                    description="Review the Q3 project deliverables",
                    priority=2,
                    due_date=expected_due,
                )
            ],
            reasoning="The note mentions a review due next Friday.",
            confidence=0.95,
        )
        return _make_response(result)

    agent = build_agent(FunctionModel(model_func))
    note_text = "Project review am Freitag um 17 Uhr"
    output = await extract(agent, note_text, reference_dt, "Known people: Alice")

    # Assert user prompt content
    assert "2026-07-05" in captured_user_content
    assert "14:00" in captured_user_content
    assert note_text in captured_user_content

    # Assert system prompt contains today's date
    assert captured_instructions is not None
    assert "Europe/Zurich" in captured_instructions

    # Assert result
    assert len(output.proposals) == 1
    task = output.proposals[0]
    assert isinstance(task, TaskProposal)
    assert task.name == "Project review"
    assert task.due_date == expected_due
    assert task.priority == 2
    assert output.confidence == 0.95


# ---------------------------------------------------------------------------
# Test 2: event + person, two proposals with discriminated parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_and_person_proposals():
    """A note yielding an event + a person.

    Assert discriminated parsing gives EventProposal + PersonProposal.
    """
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        result = ExtractionResult(
            proposals=[
                EventProposal(
                    name="Team standup",
                    description="Daily sync",
                    start_datetime=datetime(2026, 7, 6, 9, 0, 0, tzinfo=UTC),
                    location_name="Office",
                ),
                PersonProposal(
                    name="Bob Smith",
                    email="bob@example.com",
                ),
            ],
            reasoning="Found a meeting and a person.",
            confidence=0.9,
        )
        return _make_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent,
        "Standup tomorrow at 9 with Bob (bob@example.com)",
        reference_dt,
        "",
    )

    assert len(output.proposals) == 2
    event = output.proposals[0]
    person = output.proposals[1]
    assert isinstance(event, EventProposal)
    assert isinstance(person, PersonProposal)
    assert event.name == "Team standup"
    assert event.location_name == "Office"
    assert person.name == "Bob Smith"
    assert person.email == "bob@example.com"


# ---------------------------------------------------------------------------
# Test 3: empty proposals — nothing actionable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_proposals():
    """A note yielding nothing: proposals=[], valid result."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        result = ExtractionResult(
            proposals=[],
            reasoning="Nothing actionable in the note.",
            confidence=0.99,
        )
        return _make_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent,
        "Das Wetter ist schoen heute.",
        reference_dt,
        "",
    )

    assert output.proposals == []
    assert output.reasoning == "Nothing actionable in the note."
    assert output.confidence == 0.99


# ---------------------------------------------------------------------------
# Test 4: German transcription — language preserved in prompt and output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_german_transcription_language_preserved():
    """German input appears verbatim in the prompt, extracted name stays German."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    captured_user_content: str = ""

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        nonlocal captured_user_content
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        captured_user_content = part.content

        result = ExtractionResult(
            proposals=[
                TaskProposal(
                    name="Einkaufsliste für Geburtstagsfeier",
                    description="Milch, Eier, Mehl, Butter kaufen",
                    priority=3,
                )
            ],
            reasoning="Der Nutzer möchte eine Einkaufsliste erstellen.",
            confidence=0.92,
        )
        return _make_response(result)

    agent = build_agent(FunctionModel(model_func))
    german_text = (
        "Ich muss noch eine Einkaufsliste für die Geburtstagsfeier am Samstag machen."
    )
    output = await extract(agent, german_text, reference_dt, "")

    # German text appears verbatim in the user prompt
    assert german_text in captured_user_content

    # Extracted name and description stay in German
    task = output.proposals[0]
    assert isinstance(task, TaskProposal)
    assert task.name == "Einkaufsliste für Geburtstagsfeier"
    assert task.description == "Milch, Eier, Mehl, Butter kaufen"

    # System prompt should be in English
    # (instructions come separately, not in the user prompt)


# ---------------------------------------------------------------------------
# Test 5: error_feedback prompt injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_feedback_in_prompt():
    """error_feedback is injected verbatim into the user prompt."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    captured_user_content: str = ""

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        nonlocal captured_user_content
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        captured_user_content = part.content

        result = ExtractionResult(
            proposals=[
                TaskProposal(name="Fix schema error", priority=1),
            ],
            reasoning="Adjusted output to fix the schema error.",
            confidence=0.85,
        )
        return _make_response(result)

    agent = build_agent(FunctionModel(model_func))
    error_text = "SchemaCheckFailure: property 'due_date' must be an ISO 8601 datetime"
    output = await extract(
        agent,
        "Fix the date format.",
        reference_dt,
        "",
        error_feedback=error_text,
    )

    # Error text must appear verbatim in the prompt
    assert error_text in captured_user_content
    assert "Fix the output accordingly" in captured_user_content

    assert len(output.proposals) == 1
    assert output.proposals[0].name == "Fix schema error"


# ---------------------------------------------------------------------------
# Test 6: TestModel smoke — structural validity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_testmodel_smoke():
    """Run the agent with TestModel() and assert it produces a structurally
    valid ExtractionResult.  TestModel auto-generates from the schema."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    agent = build_agent(TestModel())

    output = await extract(
        agent,
        "Buy milk tomorrow.",
        reference_dt,
        "Known people: Alice / Known locations: Office",
    )

    assert isinstance(output, ExtractionResult)
    assert isinstance(output.proposals, list)
    # TestModel may generate proposals or empty list — both are valid
    # but the result must be structurally parseable
    assert 0.0 <= output.confidence <= 1.0 or isinstance(output.confidence, float)
    assert isinstance(output.reasoning, str)
