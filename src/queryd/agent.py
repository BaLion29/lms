"""Agent for the queryd service — pydantic-ai Agent with tools and
iteration cap."""

from __future__ import annotations

from datetime import datetime

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits
from zoneinfo import ZoneInfo

from queryd.settings import Settings
from queryd.tools import QuerydDeps, build_tools

# ---------------------------------------------------------------------------
# Static system prompt (behavioural rules)
# ---------------------------------------------------------------------------

_STATIC_SYSTEM_PROMPT = """
You are a helpful assistant with access to a TerminusDB knowledge graph.
Follow these rules:

- Answer in the user's language (German, French or English).
- Never show raw IRIs — always resolve references to human-readable names,
  issuing extra queries if needed.
- When listing tasks or events, order by due/start ascending and keep
  answers compact.
- If a query returns nothing, say so plainly — never invent data.
- For relative dates ("morgen", "Freitag", "diese Woche") compute concrete
  ISO date ranges from today's date before querying.
- If the user asks for a change and no write tool is available, state that
  write mode is disabled — do not pretend.
- NEVER claim a write succeeded unless a write tool returned ok=true with an IRI.
- Use the today() tool if unsure about the date.
- Call get_schema_details when a GraphQL query fails and self-correct.
""".strip()


# ---------------------------------------------------------------------------
# Usage limits (hard backstop)
# ---------------------------------------------------------------------------


def usage_limits(settings: Settings) -> UsageLimits:
    """Return a UsageLimits with ``request_limit`` as a hard backstop.

    ``request_limit`` counts model round-trips (LLM → tools → LLM …).
    We set it to ``max_tool_iterations + 3`` so the agent has a few extra
    turns to produce a final answer after exhausting its tool budget.
    """
    return UsageLimits(request_limit=settings.max_tool_iterations + 3)


# ---------------------------------------------------------------------------
# Agent builder
# ---------------------------------------------------------------------------


def build_agent(
    settings: Settings, model: Model | None = None
) -> Agent[QuerydDeps, str]:
    """Build a pydantic-ai Agent for the queryd service.

    * Model: OpenAI-compatible via OpenAIChatModel (or *model* if provided).
    * Temperature 0 for deterministic answers.
    * Tools from ``build_tools(settings)``, gated by ``enable_writes``.
    * Static system prompt + per-request dynamic briefing.

    *model* is a **test seam**: supply a ``FunctionModel`` / ``TestModel``
    to bypass real LLM calls in unit tests.
    """
    if model is None:
        model = OpenAIChatModel(
            settings.llm_model,
            provider=OpenAIProvider(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
            ),
            settings=ModelSettings(temperature=0),
        )

    agent = Agent[QuerydDeps, str](
        model,
        output_type=str,
        retries=1,
        deps_type=QuerydDeps,
        tools=build_tools(settings),
        instructions=_STATIC_SYSTEM_PROMPT,
    )

    # Per-request dynamic system prompt injection
    @agent.system_prompt
    async def _dynamic_briefing(ctx):
        """Inject current date in Europe/Zurich + schema briefing."""
        zurich = ZoneInfo("Europe/Zurich")
        now = datetime.now(zurich)
        iso = now.isoformat(timespec="seconds")
        weekday = now.strftime("%A")
        week = now.isocalendar().week
        date_line = f"Current date: {iso} ({weekday}, ISO week {week}, Europe/Zurich)."

        # Build the short briefing from schema_summary (which is the full
        # introspection JSON stored as dict in production, or a mock in tests).
        # For the dynamic prompt we use ctx.deps.prompt_briefing.
        briefing = ctx.deps.prompt_briefing

        return f"{date_line}\n\n{briefing}"

    return agent
