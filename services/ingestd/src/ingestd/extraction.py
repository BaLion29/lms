"""Pydantic AI extraction agent — turns freeform notes into typed proposals.

Uses text-based JSON extraction (not tool calls) for broad model compatibility.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal

import structlog
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from zoneinfo import ZoneInfo

logger = structlog.get_logger(__name__)

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


class ExtractionError(Exception):
    """Raised when extraction fails after all retries.

    Wraps the underlying cause so callers can inspect it while treating the
    whole extraction attempt as a single failure.
    """


# ---------------------------------------------------------------------------
# System prompt builder (runtime date injection)
# ---------------------------------------------------------------------------

_TIMEZONE = ZoneInfo("Europe/Zurich")

_JSON_SCHEMA = """{
  "proposals": [
    {
      "kind": "task",
      "name": "<string>",
      "description": "<string or null>",
      "priority": <integer 1-5 or null>,
      "estimated_duration": <minutes or null>,
      "due_date": "<ISO 8601 datetime or null>"
    },
    {
      "kind": "event",
      "name": "<string>",
      "description": "<string or null>",
      "start_datetime": "<ISO 8601 datetime or null>",
      "end_datetime": "<ISO 8601 datetime or null>",
      "location_name": "<string or null>"
    },
    {
      "kind": "reminder",
      "name": "<string>",
      "description": "<string or null>"
    },
    {
      "kind": "person",
      "name": "<string>",
      "email": "<string or null>",
      "phone": "<string or null>"
    }
  ],
  "reasoning": "<string: brief explanation of the extraction>",
  "confidence": <float 0.0 to 1.0>
}"""


def _build_system_prompt() -> str:
    """Return the system prompt with today's date injected at call time."""
    today = datetime.now(_TIMEZONE)
    today_str = today.strftime("%A, %Y-%m-%d (%Z)")
    return f"""You are an extraction assistant. Your job is to read a short note or transcription \
and extract structured proposals (tasks, events, reminders, people).

Today is {today_str}
Timezone: Europe/Zurich.

Guidelines:
- Input may be German, French, or English. Extracted names and descriptions MUST stay in \
the input's language — do not translate.
- Relative dates ("Freitag", "next week", "morgen") must be resolved to ABSOLUTE datetimes \
using the reference datetime provided in the user prompt. The reference datetime is the \
inbox document's created_at or recorded_at.
- When resolving weekday names (e.g. "Freitag", "Monday"), first determine the weekday \
of the reference datetime, then count forward to the next occurrence of the target \
weekday (the reference date itself counts as day 0). Do not count backward.
  For example: reference = Sunday 2026-07-05, target = "Friday" → 2026-07-10
  (Sunday=0, Monday=1, Tuesday=2, Wednesday=3, Thursday=4, Friday=5 → +5 days).
  reference = Tuesday, target = "Monday" → the following Monday (+6 days), not yesterday.
- Do NOT invent details — omit optional fields rather than guessing. If priority, duration, \
or a date is not explicitly stated or clearly implied, leave it null/None.
- Transcriptions may contain speech-to-text errors. Normalize obvious name mistranscriptions \
cautiously, but do not alter the semantic meaning.
- When the user prompt includes known-entity context (people/locations), reuse the EXACT \
names as listed for entities the note refers to. Do not paraphrase known names.
- Return an empty proposals list when there is nothing actionable in the input.

Return ONLY valid JSON in a markdown code block (```json ... ```). The JSON must follow \
this exact schema:

```json
{_JSON_SCHEMA}
```"""


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
    ref_str = reference_dt.strftime("%A, %Y-%m-%dT%H:%M:%SZ")
    parts = [
        f"The note was created on {ref_str}",
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
# JSON extraction from LLM text response
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _extract_json_from_text(text: str) -> str:
    """Extract a JSON string from an LLM text response.

    Handles markdown code fences (``````json ... ```````), plain JSON, and
    responses where JSON is embedded in explanatory text.
    """
    # Try code fence first
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()

    # Try to find a JSON object or array directly
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return text

    # Last resort: try to find { ... } or [ ... ] pair
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        return text[start : end + 1]

    return text


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def build_agent(model: Model) -> Agent[None, str]:
    """Return a configured extraction agent using *model*.

    The agent returns plain text (JSON code block) — the caller is responsible
    for parsing the response into ``ExtractionResult`` via ``parse_extraction``.

    Runs with temperature 0 for deterministic output.
    """
    return Agent(
        model,
        output_type=str,
        model_settings=ModelSettings(temperature=0.0, timeout=120),
    )


def build_llm_model(base_url: str, api_key: str, model_name: str) -> OpenAIChatModel:
    """Create an OpenAI-compatible model pointed at *base_url* (LiteLLM gateway)."""
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name, provider=provider)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_extraction(raw_text: str) -> ExtractionResult:
    """Parse JSON from an LLM text response into an ``ExtractionResult``.

    Handles code fences and other formatting quirks.
    """
    json_str = _extract_json_from_text(raw_text)
    try:
        return ExtractionResult.model_validate_json(json_str)
    except ValidationError:
        # Try parsing as a plain list of proposals wrapped manually
        # Some models might return just the proposals array
        try:
            proposals_data = json.loads(json_str)
            if isinstance(proposals_data, list):
                return ExtractionResult.model_validate(
                    {
                        "proposals": proposals_data,
                        "reasoning": "extracted from list response",
                        "confidence": 0.7,
                    }
                )
        except (json.JSONDecodeError, ValidationError):
            pass
        raise


async def extract(
    agent: Agent[None, str],
    text: str,
    reference_dt: datetime,
    entity_context: str,
    error_feedback: str | None = None,
    max_parse_retries: int = 2,
) -> ExtractionResult:
    """Run extraction on *text* and return the structured result.

    Retries the LLM call up to *max_parse_retries* times on parse failures
    (invalid JSON / schema mismatch) before giving up.

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
    max_parse_retries: Maximum number of LLM retries when the output cannot be
        parsed as valid ``ExtractionResult`` JSON (default 2).

    Raises
    ------
    ExtractionError
        When the LLM response cannot be parsed after all retries, or the model
        produces no usable text at all.
    """
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(text, reference_dt, entity_context, error_feedback)

    last_error: Exception | None = None

    for attempt in range(max_parse_retries + 1):
        try:
            result = await agent.run(user_prompt, instructions=system_prompt)
        except UnexpectedModelBehavior as e:
            raise ExtractionError("LLM did not produce a parsable response") from e

        raw_text: str = result.output

        if not raw_text or not raw_text.strip():
            logger.warning("extraction_empty_response", attempt=attempt)
            if attempt < max_parse_retries:
                continue
            raise ExtractionError("LLM returned empty response after all retries")

        try:
            parsed = parse_extraction(raw_text)
            logger.debug("extraction_raw_response", raw=raw_text[:500])
            return parsed
        except ValidationError as e:
            last_error = e
            logger.warning(
                "extraction_parse_failure",
                attempt=attempt,
                error=str(e),
            )
            if attempt < max_parse_retries:
                user_prompt = _build_user_prompt(
                    text,
                    reference_dt,
                    entity_context,
                    f"JSON parsing error: {e}. "
                    "Please return valid JSON matching the expected schema.",
                )
                continue
            raise ExtractionError(
                f"Parse failure after {max_parse_retries + 1} attempts"
            ) from last_error

    raise ExtractionError("Extraction failed after all retries")
