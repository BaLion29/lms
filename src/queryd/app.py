"""FastAPI application factory for queryd."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms_core.tdb import TdbClient, TdbError
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from queryd.agent import build_agent, usage_limits
from queryd.schema_briefing import (
    fetch_introspection,
    render_prompt_briefing,
    render_schema_summary,
)
from queryd.settings import Settings
from queryd.tools import QuerydDeps, ToolTraceEntry

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRIEFING = "schema unavailable at startup"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    message: str
    tool_trace: list[ToolTraceEntry] = []


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _bearer_auth(request: Request) -> None:
    """Validate the ``Authorization: Bearer <token>`` header.

    Raises ``HTTPException(401)`` on missing, malformed, or wrong token.
    """
    settings: Settings = request.app.state.settings
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
        )
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
        )
    if not secrets.compare_digest(parts[1], settings.api_token):
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
        )


# ---------------------------------------------------------------------------
# Lazy schema re-fetch helper
# ---------------------------------------------------------------------------


async def _ensure_briefing(app: FastAPI) -> None:
    """If the cached briefing is the placeholder, attempt one re-fetch.

    Uses an asyncio.Lock so concurrent requests don't stampede.
    On failure the placeholder stays in place and the agent still runs.
    """
    if app.state.briefings[1] != _PLACEHOLDER_BRIEFING:
        return

    async with app.state._briefing_lock:
        # Double-check after acquiring the lock
        if app.state.briefings[1] != _PLACEHOLDER_BRIEFING:
            return
        tdb: TdbClient = app.state.tdb
        try:
            intro = await fetch_introspection(tdb)
            app.state.briefings = (
                render_schema_summary(intro),
                render_prompt_briefing(intro),
            )
            log.info("lazy schema re-fetch succeeded")
        except Exception:
            log.warning("lazy schema re-fetch failed", exc_info=True)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI, settings: Settings, model: Model | None = None):
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        timeout=settings.request_timeout_seconds,
    )
    app.state.tdb = tdb

    # Build the agent once at startup.
    app.state.agent = build_agent(settings, model=model)

    # Introspection: try at startup, store placeholder on failure.
    try:
        intro = await fetch_introspection(tdb)
        app.state.briefings = (
            render_schema_summary(intro),
            render_prompt_briefing(intro),
        )
        log.info("schema introspection succeeded at startup")
    except Exception:
        log.warning("schema introspection failed at startup", exc_info=True)
        app.state.briefings = (_PLACEHOLDER_BRIEFING, _PLACEHOLDER_BRIEFING)

    app.state._briefing_lock = asyncio.Lock()

    try:
        yield
    finally:
        await tdb.aclose()


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("queryd")
    except Exception:
        return "dev"


def create_app(settings: Settings, model: Model | None = None) -> FastAPI:
    """Build the FastAPI application for the given *settings*.

    *model* is a **test seam**: when provided it is injected into the
    agent so unit tests can supply a ``FunctionModel`` or ``TestModel``
    without reaching a real LLM.
    """
    _configure_logging()

    @asynccontextmanager
    async def _app_lifespan(app: FastAPI):
        async with _lifespan(app, settings, model) as _:
            yield

    app = FastAPI(
        title="queryd",
        lifespan=_app_lifespan,
    )
    app.state.settings = settings

    # CORS middleware (optional)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------------
    # /healthz (no auth)
    # ------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        try:
            ok = await app.state.tdb.db_exists()
        except (TdbError, Exception):
            ok = False
        if ok:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "terminusdb": "up",
                    "version": _get_version(),
                },
            )
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "terminusdb": "down",
                "version": _get_version(),
            },
        )

    # ------------------------------------------------------------------
    # /v1/chat (auth + validation)
    # ------------------------------------------------------------------

    @app.post(
        "/v1/chat",
        response_model=ChatResponse,
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_chat(body: ChatRequest):
        if not body.messages:
            raise HTTPException(
                status_code=422,
                detail="messages must not be empty",
            )
        if body.messages[-1].role != "user":
            raise HTTPException(
                status_code=422,
                detail="last message must be from the user",
            )

        # Lazy retry schema briefing if it was unavailable at startup.
        await _ensure_briefing(app)

        # Build history from all messages except the last.
        history: list[ModelMessage] | None = None
        if len(body.messages) > 1:
            history = []
            for msg in body.messages[:-1]:
                if msg.role == "user":
                    history.append(
                        ModelRequest(parts=[UserPromptPart(content=msg.content)])
                    )
                else:
                    history.append(ModelResponse(parts=[TextPart(content=msg.content)]))

        prompt = body.messages[-1].content

        # Build fresh deps for this request.
        schema_summary, prompt_briefing = app.state.briefings
        deps = QuerydDeps(
            tdb=app.state.tdb,
            settings=app.state.settings,
            schema_summary=schema_summary,
            prompt_briefing=prompt_briefing,
            trace=[],
            tool_calls_used=0,
        )

        agent = app.state.agent
        limits = usage_limits(app.state.settings)

        try:
            async with asyncio.timeout(app.state.settings.request_timeout_seconds):
                result = await agent.run(
                    prompt,
                    deps=deps,
                    message_history=history or None,
                    usage_limits=limits,
                )
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"detail": "request timed out"},
            )
        except UsageLimitExceeded:
            log.warning("usage limit exceeded (hard backstop)")
            return JSONResponse(
                status_code=502,
                content={"detail": "model exceeded iteration budget"},
            )
        except HTTPException:
            raise
        except (
            ModelHTTPError,
            ModelAPIError,
            UnexpectedModelBehavior,
            Exception,
        ):
            log.error("llm provider error", exc_info=True)
            return JSONResponse(
                status_code=502,
                content={"detail": "llm provider error"},
            )

        return ChatResponse(
            message=result.output,
            tool_trace=deps.trace,
        )

    return app
