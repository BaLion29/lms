"""FastAPI application factory for queryd."""

from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms_core.conventions import blob_root_from_env
from lms_core.tdb import TdbClient, TdbError
from lms_core.plugins import discover_plugins, select_plugins
from pydantic_ai import Tool
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
    fetch_module_list,
    render_module_briefing,
    render_prompt_briefing,
    render_schema_summary,
)
from queryd.settings import Settings
from queryd.tools import QuerydDeps, ToolTraceEntry, build_tools

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
# Lazy briefing helpers
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
            _rebuild_briefings(app, intro)
            log.info("lazy schema re-fetch succeeded")
        except Exception:
            log.warning("lazy schema re-fetch failed", exc_info=True)


def _rebuild_briefings(app: FastAPI, intro: dict) -> None:
    """Rebuild summary + prompt briefing from introspection + stored module data."""
    schema_summary = render_schema_summary(intro)
    prompt_briefing = render_prompt_briefing(intro)

    modules = getattr(app.state, "modules", [])
    active_plugins = getattr(app.state, "active_plugins", [])
    if modules or active_plugins:
        prompt_briefing += "\n\n" + render_module_briefing(
            modules, active_plugins=active_plugins
        )

    app.state.briefings = (schema_summary, prompt_briefing)


# ---------------------------------------------------------------------------
# Plugin helper
# ---------------------------------------------------------------------------

_PLUGIN_GROUP = "lms.queryd.tools"


def _collect_plugin_tools(
    plugins: list[tuple[str, object]],
    settings: Settings,
    tdb: TdbClient,
) -> tuple[list[Tool], list[str]]:
    """Call ``tools(deps)`` on each plugin, check for name collisions.

    Returns ``(all_tools, active_names)``.  Raises ``RuntimeError`` on
    name collision (against read tools or across plugins).
    """
    plugin_tools: list[Tool] = []
    active_names: list[str] = []

    # Read-tool names (baseline for collision check)
    read_tool_names = {t.name for t in build_tools(settings, plugin_tools=[])}

    for ep_name, obj in plugins:
        # Duck-typing: ToolPlugin is not @runtime_checkable
        if hasattr(obj, "tools") and hasattr(obj, "name"):
            plugin = obj
        else:
            log.warning("plugin '%s' is not a ToolPlugin", ep_name)
            continue

        active_names.append(plugin.name)
        tools: list[Tool] = plugin.tools(deps=None)

        for t in tools:
            if t.name in read_tool_names:
                raise RuntimeError(
                    f"Tool name collision: plugin '{plugin.name}' tool "
                    f"'{t.name}' conflicts with a core read tool"
                )

        # Cross-plugin collision
        existing = {t.name for t in plugin_tools}
        for t in tools:
            if t.name in existing:
                raise RuntimeError(
                    f"Tool name collision: plugin '{plugin.name}' tool "
                    f"'{t.name}' already registered by another plugin"
                )
        existing |= {t.name for t in tools}

        plugin_tools.extend(tools)

    return plugin_tools, active_names


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(
    app: FastAPI,
    settings: Settings,
    model: Model | None = None,
    *,
    plugin_tools_override: list[Tool] | None = None,
):
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        timeout=settings.request_timeout_seconds,
    )
    app.state.tdb = tdb

    # ── Plugin discovery and selection ─────────────────────────────────
    plugin_tools: list[Tool] = []
    active_plugins: list[str] = []

    if plugin_tools_override is not None:
        # Test seam: use explicitly provided write tools
        if settings.enable_writes:
            plugin_tools = list(plugin_tools_override)
            active_plugins = ["test_override"]
        else:
            log.info(
                "write-tool plugins suppressed (ENABLE_WRITES=false)",
                count=len(plugin_tools_override),
            )
    else:
        discovered = discover_plugins(_PLUGIN_GROUP)
        log.info(
            "plugins discovered",
            group=_PLUGIN_GROUP,
            count=len(discovered.active),
            failed=len(discovered.failed),
        )

        # Broken entry points are always fatal in strict mode
        if discovered.failed and settings.strict_plugins:
            failed_names = [n for n, _ in discovered.failed]
            raise RuntimeError(
                f"Strict plugin mode: failed={failed_names}"
            )

        # Run selection (requirement checking + strict enforcement)
        # whenever plugins are relevant: strict enforcement always,
        # or when writes are enabled and we need to register tools.
        if settings.strict_plugins or settings.enable_writes:
            selection = await select_plugins(
                tdb,
                discovered,
                strict=settings.strict_plugins,
                branch=settings.tdb_branch,
            )

            for name, violations in selection.skipped:
                log.warning(
                    "plugin skipped (unmet requirements)",
                    plugin=name,
                    violations=violations,
                )

            if selection.active:
                if settings.enable_writes:
                    p_tools, active_plugins = _collect_plugin_tools(
                        selection.active, settings, tdb
                    )
                    plugin_tools = p_tools
                    log.info("active write-tool plugins", plugins=active_plugins)
                else:
                    active_plugins = [
                        getattr(obj, "name", ep_name)
                        for ep_name, obj in selection.active
                    ]
                    log.info(
                        "write-tool plugins suppressed (ENABLE_WRITES=false)",
                        count=len(active_plugins),
                    )
            else:
                log.info("no active write-tool plugins")
        else:
            # Neither strict nor writes enabled — report discovered
            # plugins as the active set but skip TDB requirement check.
            if discovered.active:
                active_plugins = [
                    getattr(obj, "name", ep_name)
                    for ep_name, obj in discovered.active
                ]
            log.info(
                "write-tool plugins suppressed (ENABLE_WRITES=false)",
                count=len(discovered.active),
            )

    app.state.active_plugins = active_plugins

    # ── Build agent once ───────────────────────────────────────────────
    tools = build_tools(settings, plugin_tools=plugin_tools)
    app.state.agent = build_agent(settings, model=model, tools=tools)

    # ── Introspection ──────────────────────────────────────────────────
    try:
        intro = await fetch_introspection(tdb)
        log.info("schema introspection succeeded at startup")
    except Exception:
        log.warning("schema introspection failed at startup", exc_info=True)
        intro = None

    # ── Module registry ────────────────────────────────────────────────
    modules: list[dict] = []
    try:
        modules = await fetch_module_list(tdb, branch=settings.tdb_branch)
        log.info("module registry fetched", count=len(modules))
    except Exception:
        log.warning("module registry unavailable — skipping capability section")
    app.state.modules = modules

    # ── Build briefings ────────────────────────────────────────────────
    if intro is not None:
        _rebuild_briefings(app, intro)
    else:
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


def create_app(
    settings: Settings,
    model: Model | None = None,
    *,
    plugin_tools: list[Tool] | None = None,
) -> FastAPI:
    """Build the FastAPI application for the given *settings*.

    *model* is a **test seam**: when provided it is injected into the
    agent so unit tests can supply a ``FunctionModel`` or ``TestModel``
    without reaching a real LLM.

    *plugin_tools* is a **test seam**: when provided, these ``Tool``
    objects are used as write-tool plugins instead of discovering them
    via entry points.  When ``None`` (default, production),
    ``discover_plugins("lms.queryd.tools")`` is used.
    """
    _configure_logging()

    @asynccontextmanager
    async def _app_lifespan(app: FastAPI):
        async with _lifespan(app, settings, model, plugin_tools_override=plugin_tools) as _:
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
        tdb_ok: bool
        try:
            tdb_ok = await app.state.tdb.db_exists()
        except Exception:
            tdb_ok = False

        # Live fetch module versions (graceful degradation)
        module_versions: dict[str, str] = {}
        try:
            module_docs = await fetch_module_list(
                app.state.tdb,
                branch=app.state.settings.tdb_branch,
            )
            for doc in module_docs:
                name = doc.get("name")
                mod_version = doc.get("version")
                if name and mod_version:
                    module_versions[name] = mod_version
        except Exception:
            log.warning("healthz: module registry fetch failed")

        # ── Blob root writable probe ──────────────────────────────────────
        blob_root_writable: bool | None = None
        blob_root = blob_root_from_env()
        if blob_root is not None:
            try:
                blob_root.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=str(blob_root), delete=True) as f:
                    f.write(b"probe")
                blob_root_writable = True
            except OSError:
                blob_root_writable = False

        active_plugins: list[str] = getattr(app.state, "active_plugins", [])

        status = "ok" if tdb_ok else "degraded"
        status_code = 200 if tdb_ok else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": status,
                "terminusdb": "up" if tdb_ok else "down",
                "version": _get_version(),
                "modules": module_versions,
                "plugins": active_plugins,
                "blob_root_writable": blob_root_writable,
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
