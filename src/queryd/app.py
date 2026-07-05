"""FastAPI application factory for queryd."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms_core.tdb import TdbClient, TdbError

from queryd.settings import Settings


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ToolTraceEntry(BaseModel):
    tool: str
    input: dict[str, object]
    output_summary: str


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
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        timeout=settings.request_timeout_seconds,
    )
    app.state.tdb = tdb
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


def create_app(settings: Settings) -> FastAPI:
    """Build the FastAPI application for the given *settings*."""
    _configure_logging()

    app = FastAPI(
        title="queryd",
        lifespan=_lifespan,
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
    # /v1/chat (auth + validation, stub)
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
        raise HTTPException(status_code=501, detail="not implemented")

    return app
