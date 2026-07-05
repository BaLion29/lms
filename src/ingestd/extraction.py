"""Pydantic AI extraction agent — turns freeform notes into typed proposals."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class TaskProposal(BaseModel):
    kind: Literal["task"] = "task"
    name: str
    description: str | None = None
    priority: int | None = None
    estimated_duration: int | None = None
    due_date: datetime | None = None


class EventProposal(BaseModel):
    kind: Literal["event"] = "event"
    name: str
    description: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    location_name: str | None = None


class ReminderProposal(BaseModel):
    kind: Literal["reminder"] = "reminder"
    name: str
    description: str | None = None


class PersonProposal(BaseModel):
    kind: Literal["person"] = "person"
    name: str
    email: str | None = None
    phone: str | None = None


Proposal = Annotated[
    TaskProposal | EventProposal | ReminderProposal | PersonProposal,
    Field(discriminator="kind"),
]


class ExtractionResult(BaseModel):
    proposals: list[Proposal] = Field(default_factory=list)
    reasoning: str
    confidence: float


# ---------------------------------------------------------------------------
# System prompt builder (runtime date injection)
# ---------------------------------------------------------------------------

_TIMEZONE = ZoneInfo("Europe/Zurich")


def _build_system_prompt() -> str:
    """Return the system prompt with today's date injected at call time."""
    today = datetime.now(_TIMEZONE)
    today_str = today.strftime("%A, %Y-%m-%d (%Z, UTC%z)")
    return f"""You are an extraction assistant. Your job is to read a short note or transcription \
and extract structured proposals (tasks, events, reminders, people).

Today's date: {today_str}
Timezone: Europe/Zurich.

Guidelines:
- Input may be German, French, or English. Extracted names and descriptions MUST stay in \
the input's language — do not translate.
- Relative dates ("Freitag", "next week", "morgen") must be resolved to ABSOLUTE datetimes \
using the reference datetime provided in the user prompt. The reference datetime is the \
inbox document's created_at or recorded_at.
- Do NOT invent details — omit optional fields rather than guessing. If priority, duration, \
or a date is not explicitly stated or clearly implied, leave it null/None.
- Transcriptions may contain speech-to-text errors. Normalize obvious name mistranscriptions \
cautiously, but do not alter the semantic meaning.
- When the user prompt includes known-entity context (people/locations), reuse the EXACT \
names as listed for entities the note refers to. Do not paraphrase known names.
- Return an empty proposals list when there is nothing actionable in the input."""


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def _build_user_prompt(
    text: str,
    reference_dt: datetime,
    entity_context: str,
    error_feedback: str | None,
) -> str:
    """Assemble the complete user prompt for one extraction call."""
    ref_str = reference_dt.strftime("%A, %Y-%m-%d %H:%M %Z")
    parts = [
        f"Reference datetime (the note was created/recorded at): {ref_str}",
    ]
    if entity_context.strip():
        parts.append(f"Known-entity context:\n{entity_context}")
    parts.append(f"Note text:\n---\n{text}\n---")
    if error_feedback:
        parts.append(
            "The previous attempt was rejected by the database with this error:\n"
            f"{error_feedback}\n"
            "Fix the output accordingly."
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def build_agent(model: Model) -> Agent[None, ExtractionResult]:
    """Return a configured extraction agent using *model*.

    The agent runs with temperature 0 for deterministic output and retries=2
    for built-in output validation retries.
    """
    return Agent(
        model,
        output_type=ExtractionResult,
        retries=2,
        model_settings=ModelSettings(temperature=0.0),
    )


def build_llm_model(base_url: str, api_key: str, model_name: str) -> OpenAIChatModel:
    """Create an OpenAI-compatible model pointed at *base_url* (LiteLLM gateway)."""
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name, provider=provider)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract(
    agent: Agent[None, ExtractionResult],
    text: str,
    reference_dt: datetime,
    entity_context: str,
    error_feedback: str | None = None,
) -> ExtractionResult:
    """Run extraction on *text* and return the structured result.

    Parameters
    ----------
    agent: A pre-built extraction agent (see :func:`build_agent`).
    text: The note or transcription to analyse.
    reference_dt: Inbox document's ``created_at`` / ``recorded_at``, used to
        resolve relative date expressions.
    entity_context: Compact block of known people/locations for entity linking
        hints.  May be an empty string.
    error_feedback: If set, the raw TerminusDB rejection body from a previous
        attempt.  Included verbatim in the prompt so the model can correct itself.
    """
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(text, reference_dt, entity_context, error_feedback)

    result = await agent.run(user_prompt, instructions=system_prompt)
    return result.output
