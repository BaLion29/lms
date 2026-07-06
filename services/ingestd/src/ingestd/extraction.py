"""Pydantic AI extraction agent — turns freeform notes into typed proposals.

Uses text-based JSON extraction (not tool calls) for broad model compatibility.

Design:
- Proposal models are provided by ExtractorPlugin plugins.
- ``build_extraction_context`` collects their models, checks for ``kind``
  collisions, and produces a unified system prompt + per-kind parse dispatch.
- ``extract`` and ``parse_extraction`` require an ``ExtractionContext``.
- The system prompt is static (built once at startup); today's date and
  timezone are injected into the per-call user input.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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


class ExtractionResult(BaseModel):
    """A single extraction call result.

    *proposals* accepts ``list[Any]`` so that the same class works with
    dynamically-built proposal unions.  Callers should access individual
    items via the typed model they dispatch to.
    """

    proposals: list[Any] = Field(default_factory=list)
    reasoning: str
    confidence: float


class ExtractionError(Exception):
    """Raised when extraction fails after all retries.

    Wraps the underlying cause so callers can inspect it while treating the
    whole extraction attempt as a single failure.
    """


# ---------------------------------------------------------------------------
# ExtractionContext — built once at startup from ExtractorPlugins
# ---------------------------------------------------------------------------


@dataclass
class ExtractionContext:
    """Pre-built extraction configuration from plugin list.

    Built once at startup.  Fields:
    * ``system_prompt`` — the system prompt (core rules + plugin snippets)
    * ``kind_to_model`` — ``{"task": TaskProposal, "event": EventProposal, …}``
    * ``kind_to_plugin`` — ``{"task": <PlanningPeoplePlugin>, …}``
    """

    system_prompt: str
    kind_to_model: dict[str, type[BaseModel]] = field(default_factory=dict)
    kind_to_plugin: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

_TIMEZONE = ZoneInfo("Europe/Zurich")

_CORE_RULES = """You are an extraction assistant. Your job is to read a short note or transcription \
and extract structured proposals.

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
this exact schema:"""


def _build_system_prompt_from_plugins(
    plugins: list[Any],
) -> str:
    """Build system prompt: core rules + each plugin's ``prompt_snippet()``.

    The prompt is static — today's date is NOT included here; it is injected
    into the per-call user prompt instead.
    """
    parts = [_CORE_RULES]
    for plugin in plugins:
        parts.append(plugin.prompt_snippet())
    return "".join(parts)


def build_extraction_context(
    plugins: list[Any],
) -> ExtractionContext:
    """Build an ``ExtractionContext`` from a list of ``ExtractorPlugin`` instances.

    Raises ``ValueError`` when two plugins declare the same ``kind`` discriminant.
    """
    kind_to_model: dict[str, type[BaseModel]] = {}
    kind_to_plugin: dict[str, Any] = {}
    errors: list[str] = []

    for plugin in plugins:
        for model_cls in plugin.proposal_models():
            if not hasattr(model_cls, "model_fields"):
                errors.append(
                    f"plugin '{plugin.name}' returned non-pydantic model: {model_cls}"
                )
                continue
            kind_field = model_cls.model_fields.get("kind")
            if kind_field is None or kind_field.default is None:
                errors.append(
                    f"plugin '{plugin.name}' model {model_cls.__name__} "
                    "missing 'kind' field with default"
                )
                continue
            kind = kind_field.default
            if kind in kind_to_model:
                raise ValueError(
                    f"Kind collision: '{kind}' declared by both "
                    f"'{kind_to_plugin[kind].name}' and '{plugin.name}'"
                )
            kind_to_model[kind] = model_cls
            kind_to_plugin[kind] = plugin

    if errors:
        raise ValueError(
            f"Plugin model errors ({len(errors)}): " + "; ".join(errors)
        )

    system_prompt = _build_system_prompt_from_plugins(plugins)

    return ExtractionContext(
        system_prompt=system_prompt,
        kind_to_model=kind_to_model,
        kind_to_plugin=kind_to_plugin,
    )


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
    today = datetime.now(_TIMEZONE)
    today_str = today.strftime("%A, %Y-%m-%d (%Z)")
    ref_str = reference_dt.strftime("%A, %Y-%m-%dT%H:%M:%SZ")
    parts = [
        f"Today is {today_str}",
        "Timezone: Europe/Zurich.",
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


def parse_extraction(
    raw_text: str,
    kind_to_model: dict[str, type[BaseModel]],
) -> ExtractionResult:
    """Parse JSON from an LLM text response into an ``ExtractionResult``.

    Each item in ``"proposals"`` is dispatched by its ``"kind"`` field to
    the matching model.  Unknown kinds are collected as errors and the item
    is skipped; individual validation failures are also collected — other
    proposals in the same batch are still returned.

    Handles code fences and other formatting quirks.
    """
    json_str = _extract_json_from_text(raw_text)

    data = json.loads(json_str)  # let JSONDecodeError propagate

    if isinstance(data, list):
        # Bare array → wrap
        proposals_data = data
        reasoning = "extracted from list response"
        confidence = 0.7
    elif isinstance(data, dict):
        proposals_data = data.get("proposals", [])
        reasoning = data.get("reasoning", "")
        confidence = data.get("confidence", 0.5)
    else:
        raise ValueError(f"Unexpected JSON type: {type(data)}")

    proposals: list[Any] = []
    parse_errors: list[str] = []

    for item in proposals_data:
        if not isinstance(item, dict):
            parse_errors.append(f"non-dict proposal item: {item}")
            continue
        kind = item.get("kind")
        if kind is None:
            parse_errors.append(f"proposal item missing 'kind': {item}")
            continue
        model_cls = kind_to_model.get(kind)
        if model_cls is None:
            parse_errors.append(f"unknown kind '{kind}' — no plugin handles it")
            continue
        try:
            proposals.append(model_cls.model_validate(item))
        except ValidationError as e:
            parse_errors.append(f"kind '{kind}' validation error: {e}")

    if parse_errors:
        logger.warning(
            "extraction_parse_errors",
            count=len(parse_errors),
            errors=parse_errors,
        )

    return ExtractionResult(
        proposals=proposals,
        reasoning=reasoning,
        confidence=float(confidence),
    )


async def extract(
    agent: Agent[None, str],
    text: str,
    reference_dt: datetime,
    entity_context: str,
    error_feedback: str | None = None,
    max_parse_retries: int = 2,
    *,
    extraction_ctx: ExtractionContext,
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
    extraction_ctx: Pre-built ``ExtractionContext`` (required).

    Raises
    ------
    ExtractionError
        When the LLM response cannot be parsed after all retries, or the model
        produces no usable text at all.
    """
    system_prompt = extraction_ctx.system_prompt
    kind_to_model = extraction_ctx.kind_to_model

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
            parsed = parse_extraction(raw_text, kind_to_model=kind_to_model)
            logger.debug("extraction_raw_response", raw=raw_text[:500])
            return parsed
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
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
