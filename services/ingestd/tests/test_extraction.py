"""Tests for the extraction agent — no network, offline only."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ingestd.extraction import (
    ExtractionError,
    ExtractionResult,
    _model_schema_entry,
    build_agent,
    build_extraction_context,
    extract,
    parse_extraction,
)
from firnline_ext_time_management.extract import (
    ActivityProposal,
    EventProposal,
    PersonProposal,
    RoutineProposal,
    TaskProposal,
    TimeManagementPlugin,
)
from firnline_ext_reminders.extract import ReminderProposal, ReminderExtractPlugin
from firnline_ext_address_book.extract import AddressBookLinkingPlugin

UTC = timezone.utc

# Reusable extraction context for tests that need the plugin-aware path
_PLANNING_PLUGIN = TimeManagementPlugin()
_EXTRACTION_CTX = build_extraction_context([_PLANNING_PLUGIN])

# Full ensemble context for integration tests (all three plugins)
_FULL_ENSEMBLE_CTX = build_extraction_context([
    TimeManagementPlugin(),
    ReminderExtractPlugin(),
    AddressBookLinkingPlugin(),
])

# Kind-to-model map for direct parse_extraction calls
_KIND_MAP = _EXTRACTION_CTX.kind_to_model
_FULL_KIND_MAP = _FULL_ENSEMBLE_CTX.kind_to_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(text: str) -> ModelResponse:
    """Build a FunctionModel response carrying *text* as TextPart."""
    return ModelResponse(parts=[TextPart(text)])


def _json_response(result: ExtractionResult) -> ModelResponse:
    """Build a JSON code-fenced response (mimics real LLM output)."""
    json_str = result.model_dump_json(indent=2)
    return _make_response(f"```json\n{json_str}\n```")


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
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    note_text = "Project review am Freitag um 17 Uhr"
    output = await extract(
        agent, note_text, reference_dt, "Known people: Alice",
        extraction_ctx=_EXTRACTION_CTX,
    )

    # Assert user prompt content
    assert "2026-07-05" in captured_user_content
    assert "T14:00:00Z" in captured_user_content
    assert note_text in captured_user_content
    assert "Sunday" in captured_user_content
    # Today's date and timezone are now in the user prompt
    assert "Today is" in captured_user_content
    assert "Europe/Zurich" in captured_user_content

    # Assert system prompt does NOT contain today's date (static prompt)
    assert captured_instructions is not None
    assert "Europe/Zurich" not in captured_instructions
    # Weekday anchoring instruction still in system prompt
    assert (
        "count forward to the next occurrence of the target weekday"
        in captured_instructions
    )

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
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent,
        "Standup tomorrow at 9 with Bob (bob@example.com)",
        reference_dt,
        "",
        extraction_ctx=_EXTRACTION_CTX,
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
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent,
        "Das Wetter ist schoen heute.",
        reference_dt,
        "",
        extraction_ctx=_EXTRACTION_CTX,
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
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    german_text = (
        "Ich muss noch eine Einkaufsliste für die Geburtstagsfeier am Samstag machen."
    )
    output = await extract(
        agent, german_text, reference_dt, "",
        extraction_ctx=_EXTRACTION_CTX,
    )

    # German text appears verbatim in the user prompt
    assert german_text in captured_user_content

    # Extracted name and description stay in German
    task = output.proposals[0]
    assert isinstance(task, TaskProposal)
    assert task.name == "Einkaufsliste für Geburtstagsfeier"
    assert task.description == "Milch, Eier, Mehl, Butter kaufen"


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
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    error_text = "SchemaCheckFailure: property 'due_date' must be an ISO 8601 datetime"
    output = await extract(
        agent,
        "Fix the date format.",
        reference_dt,
        "",
        error_feedback=error_text,
        extraction_ctx=_EXTRACTION_CTX,
    )

    # Error text must appear verbatim in the prompt
    assert error_text in captured_user_content
    assert "Fix the output accordingly" in captured_user_content

    assert len(output.proposals) == 1
    assert output.proposals[0].name == "Fix schema error"


# ---------------------------------------------------------------------------
# Test 6: FunctionModel smoke — structural validity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_testmodel_smoke():
    """Run the agent with a FunctionModel returning empty proposals and assert
    it produces a structurally valid ExtractionResult."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        result = ExtractionResult(
            proposals=[TaskProposal(name="Buy milk")],
            reasoning="Should buy milk.",
            confidence=0.9,
        )
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))

    output = await extract(
        agent,
        "Buy milk tomorrow.",
        reference_dt,
        "Known people: Alice / Known locations: Office",
        extraction_ctx=_EXTRACTION_CTX,
    )

    assert isinstance(output, ExtractionResult)
    assert isinstance(output.proposals, list)
    assert len(output.proposals) >= 1
    assert 0.0 <= output.confidence <= 1.0 or isinstance(output.confidence, float)
    assert isinstance(output.reasoning, str)


# ---------------------------------------------------------------------------
# Test 7: parse_extraction with code fence
# ---------------------------------------------------------------------------


def test_parse_extraction_code_fence():
    """parse_extraction handles ```json ... ``` code fences."""
    raw = """Here is the result:
```json
{
  "proposals": [{"kind": "task", "name": "Do it"}],
  "reasoning": "Simple task.",
  "confidence": 0.95
}
```
Done."""
    result = parse_extraction(raw, kind_to_model=_KIND_MAP)
    assert len(result.proposals) == 1
    assert result.proposals[0].name == "Do it"
    assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# Test 8: parse_extraction plain JSON
# ---------------------------------------------------------------------------


def test_parse_extraction_plain_json():
    """parse_extraction handles plain JSON without code fences."""
    raw = '{"proposals":[],"reasoning":"Nothing.","confidence":1.0}'
    result = parse_extraction(raw, kind_to_model=_KIND_MAP)
    assert result.proposals == []
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# Test 9: parse_extraction embedded JSON
# ---------------------------------------------------------------------------


def test_parse_extraction_embedded_json():
    """parse_extraction finds JSON embedded in extraneous text."""
    raw = 'I found this: {"proposals":[{"kind":"task","name":"X"}],"reasoning":"ok","confidence":0.8} end'
    result = parse_extraction(raw, kind_to_model=_KIND_MAP)
    assert len(result.proposals) == 1
    assert result.proposals[0].name == "X"


# ---------------------------------------------------------------------------
# Test 10: extract handles empty proposals response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_empty_response_returns_empty_result():
    """When the LLM returns empty proposals, extract returns empty ExtractionResult."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    result = ExtractionResult(
        proposals=[],
        reasoning="Nothing to do.",
        confidence=0.99,
    )

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent, "whatever", reference_dt, "",
        extraction_ctx=_EXTRACTION_CTX,
    )

    assert output.proposals == []
    assert output.confidence == 0.99


# ---------------------------------------------------------------------------
# Test 11 — Parse retries on bad JSON, eventually succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_retry_succeeds():
    """First call returns bad JSON; second call returns valid JSON → succeeds."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
    calls = [0]

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        calls[0] += 1
        if calls[0] == 1:
            return _make_response("not json at all, just garbage")
        result = ExtractionResult(
            proposals=[TaskProposal(name="Finally good")],
            reasoning="Retried and succeeded.",
            confidence=0.85,
        )
        return _json_response(result)

    agent = build_agent(FunctionModel(model_func))
    output = await extract(
        agent, "Some note", reference_dt, "",
        extraction_ctx=_EXTRACTION_CTX,
    )

    assert calls[0] == 2
    assert len(output.proposals) == 1
    assert output.proposals[0].name == "Finally good"


# ---------------------------------------------------------------------------
# Test 12 — Parse retries exhausted → ExtractionError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_retry_exhausted_raises_extraction_error():
    """All attempts return bad JSON → ExtractionError raised."""
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        return _make_response("garbage every time")

    agent = build_agent(FunctionModel(model_func))

    with pytest.raises(ExtractionError, match="Parse failure"):
        await extract(
            agent, "Some note", reference_dt, "",
            extraction_ctx=_EXTRACTION_CTX,
        )


# ---------------------------------------------------------------------------
# Test 13 — Empty response retried → ExtractionError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_response_retried_raises_extraction_error():
    """LLM returns empty text every time → ExtractionError after retries.

    Note: FunctionModel can raise UnexpectedModelBehavior for truly empty
    responses before we reach the empty-text check.  We use whitespace-only
    strings to exercise the explicit empty-check path instead.
    """
    reference_dt = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    async def model_func(messages: list, agent_info: AgentInfo) -> ModelResponse:
        return _make_response("   ")

    agent = build_agent(FunctionModel(model_func))

    with pytest.raises(ExtractionError, match="empty response"):
        await extract(
            agent, "Some note", reference_dt, "",
            extraction_ctx=_EXTRACTION_CTX,
        )


# ---------------------------------------------------------------------------
# Test 14 — parse_extraction with fallback list parsing
# ---------------------------------------------------------------------------


def test_parse_extraction_flat_list_fallback():
    """parse_extraction wraps a bare JSON array into ExtractionResult."""
    raw = '[{"kind":"task","name":"X"},{"kind":"reminder","name":"Y"}]'
    result = parse_extraction(raw, kind_to_model=_FULL_KIND_MAP)
    assert len(result.proposals) == 2
    assert result.proposals[0].kind == "task"
    assert result.proposals[0].name == "X"
    assert result.proposals[1].kind == "reminder"
    assert result.proposals[1].name == "Y"
    assert result.confidence == 0.7


# ---------------------------------------------------------------------------
# Test 15 — Integration: composed prompt from all three plugins covers all 4 kinds
# ---------------------------------------------------------------------------


def test_composed_prompt_covers_all_six_kinds():
    """The system prompt built by the kernel contains two ```json fences:
    one instructional example in the core rules prose, and one actual
    schema fence with a union schema covering all proposal kinds."""
    prompt = _FULL_ENSEMBLE_CTX.system_prompt
    # Core rules present
    assert "extraction assistant" in prompt.lower()
    assert "do not translate" in prompt.lower()
    # No duplicate today/zone injection in system prompt
    assert "Today is" not in prompt
    assert "Europe/Zurich" not in prompt
    # Two ```json fences: one in prose example, one actual schema fence
    assert prompt.count("```json") == 2
    # The schema fence uses ```json\\n (not ```json space as in the prose example)
    assert "```json\n" in prompt
    assert "\n```" in prompt
<<<<<<< HEAD
    # Union schema lists base kinds (time_management: 5 + reminders: 1 + address_book: 3)
=======
    # Union schema lists all nine kinds (time_management: 8 + reminders: 1)
>>>>>>> main
    assert '"kind": "task"' in prompt
    assert '"kind": "event"' in prompt
    assert '"kind": "routine"' in prompt
    assert '"kind": "activity"' in prompt
    assert '"kind": "project"' in prompt
    assert '"kind": "area"' in prompt
    assert '"kind": "goal"' in prompt
    assert '"kind": "reminder"' in prompt
    assert '"kind": "ab_person"' in prompt
    assert '"kind": "ab_location"' in prompt
    assert '"kind": "ab_organization"' in prompt
    # Plugin fields
    assert "estimated_duration" in prompt
    assert "location_name" in prompt
    assert "email" in prompt
    # Generic JSON fields
    assert "proposals" in prompt
    assert "reasoning" in prompt
    assert "confidence" in prompt

<<<<<<< HEAD
    # Kind map has all kinds from all three plugins
    expected = {"task", "event", "person", "routine", "activity", "project", "area", "goal",
                "reminder", "ab_person", "ab_location", "ab_organization"}
    assert set(_FULL_KIND_MAP.keys()) == expected
=======
    # Kind map has all nine kinds (time_management: 8 + reminders: 1)
    assert set(_FULL_KIND_MAP.keys()) == {
        "task", "event", "person", "routine", "activity",
        "project", "area", "goal", "reminder",
    }
>>>>>>> main


def test_mixed_batch_parse_all_six_kinds():
    """A JSON batch with all six kinds is correctly dispatched to the right models."""
    raw = """{
  "proposals": [
    {"kind": "task", "name": "Buy milk"},
    {"kind": "event", "name": "Meeting", "location_name": "Office"},
    {"kind": "person", "name": "Bob Smith", "email": "bob@example.com"},
    {"kind": "routine", "name": "Morning routine", "steps": [{"name": "Stretch", "step_type": "activity"}]},
    {"kind": "activity", "name": "Yoga session"},
    {"kind": "reminder", "name": "Call doctor"}
  ],
  "reasoning": "test",
  "confidence": 0.95
}"""
    result = parse_extraction(raw, kind_to_model=_FULL_KIND_MAP)
    assert len(result.proposals) == 6
    assert isinstance(result.proposals[0], TaskProposal)
    assert isinstance(result.proposals[1], EventProposal)
    assert isinstance(result.proposals[2], PersonProposal)
    assert isinstance(result.proposals[3], RoutineProposal)
    assert isinstance(result.proposals[4], ActivityProposal)
    assert isinstance(result.proposals[5], ReminderProposal)
    assert result.proposals[0].name == "Buy milk"
    assert result.proposals[1].name == "Meeting"
    assert result.proposals[2].name == "Bob Smith"
    assert result.proposals[3].name == "Morning routine"
    assert result.proposals[4].name == "Yoga session"
    assert result.proposals[5].name == "Call doctor"


# ---------------------------------------------------------------------------
# Test 16 — recursive schema rendering for nested BaseModel fields
# ---------------------------------------------------------------------------


def test_model_schema_entry_recurses_into_nested_models():
    """_model_schema_entry recurses into nested Pydantic models so that
    fields inside ``list[BaseModel]`` are visible to the LLM."""
    entry = _model_schema_entry(RoutineProposal)

    assert entry["kind"] == "routine"
    assert "name" in entry
    assert "required_context" in entry
    assert "steps" in entry

    # steps must be a list containing a dict with nested field info
    steps = entry["steps"]
    assert isinstance(steps, list)
    assert len(steps) == 1
    step_schema = steps[0]
    assert isinstance(step_schema, dict)

    # All RoutineStepSpec fields must be visible
    assert "name" in step_schema
    assert "cadence_days" in step_schema
    assert "step_type" in step_schema
    assert "description" in step_schema
    assert "priority" in step_schema
    assert "estimated_duration" in step_schema

    # step_type is a Literal — rendered as human-readable alternatives
    assert "'activity'" in step_schema["step_type"]
    assert "'task'" in step_schema["step_type"]


# ---------------------------------------------------------------------------
# Test 17 — cycle detection / max-depth for self-referencing models
# ---------------------------------------------------------------------------


class _TreeNode(BaseModel):
    """Simple self-referencing model to exercise cycle detection."""
    name: str
    children: list["_TreeNode"] | None = None


def test_self_referencing_model_renders_cyclic_marker():
    """A self-referencing model must produce a __cyclic__ marker and not
    recurse infinitely."""
    entry = _model_schema_entry(_TreeNode)
    assert entry["name"] == "str"
    children = entry["children"]
    assert isinstance(children, list)
    assert len(children) == 1
    child_schema = children[0]
    assert isinstance(child_schema, dict)
    # The nested children field inside children is list[_TreeNode] | None,
    # so it renders as a one-element list whose item is the cyclic marker
    # dict (with __optional__ because the outer union includes None).
    nested_children = child_schema.get("children")
    assert isinstance(nested_children, list)
    assert len(nested_children) == 1
    assert nested_children[0] == {"__cyclic__": "_TreeNode", "__optional__": True}


def test_five_level_deep_nesting_hits_max_depth():
    """Deeply nested non-cyclic models hit the _MAX_DEPTH guard without
    crashing or exhausting stack."""

    class _L5(BaseModel):
        name: str = "l5"

    class _L4(BaseModel):
        l5: _L5

    class _L3(BaseModel):
        l4: _L4

    class _L2(BaseModel):
        l3: _L3

    class _L1(BaseModel):
        l2: _L2

    class _L0(BaseModel):
        l1: _L1

    entry = _model_schema_entry(_L0)
    # _L0.l1 → _L1.l2 → _L2.l3 → _L3.l4 → _L4.l5 → _L5.name
    # depth goes: 1, 2, 3, 4, 5 — at depth 5 _render_field_value for
    # _L5 should still process since d=5 ≤ MAX_DEPTH=5, and _L5's
    # field 'name' at d=6 hits the guard.
    l1 = entry["l1"]
    assert isinstance(l1, dict)
    l2 = l1["l2"]
    assert isinstance(l2, dict)
    l3 = l2["l3"]
    assert isinstance(l3, dict)
    l4 = l3["l4"]
    assert isinstance(l4, dict)
    l5 = l4["l5"]
    assert isinstance(l5, dict)
    # name at depth 6 should be rendered normally (str → "str")
    assert l5["name"] == "str"
