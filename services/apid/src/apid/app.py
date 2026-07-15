"""Combined single-port API application for Firnline Core.

Assembles captured, queryd, indexed, and mcpd into a single FastAPI app.
"""

from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from firnline_core.logging import configure_logging

from captured.app import create_component as captured_create_component
from captured.settings import Settings as CapturedSettings
from queryd.app import create_component as queryd_create_component
from queryd.settings import Settings as QuerydSettings
from indexed.app import create_component as indexed_create_component
from indexed.settings import Settings as IndexedSettings
from mcpd.main import create_mcp_component as mcpd_create_mcp_component
from mcpd.settings import McpdSettings

from apid.settings import ApidSettings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Lifespan ordering rationale
# ---------------------------------------------------------------------------
# indexed enters first so its background poller starts populating the search
# store before queryd receives requests.  queryd enters second because it may
# call indexed over HTTP at runtime.  captured and mcpd have no ordering
# constraints and follow afterwards.  On shutdown, AsyncExitStack unwinds in
# reverse order, ensuring indexed's poll task cancellation happens after
# dependent services have stopped.
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build the combined Firnline Core API application."""

    apid_settings = ApidSettings()
    configure_logging(apid_settings.log_level)

    # ── Instantiate each component's own settings ───────────────────────
    captured_settings = CapturedSettings()  # type: ignore[call-arg]
    queryd_settings = QuerydSettings()  # type: ignore[call-arg]
    indexed_settings = IndexedSettings()
    mcpd_settings = McpdSettings()  # type: ignore[call-arg]

    # ── Build components ────────────────────────────────────────────────
    captured_component = captured_create_component(captured_settings)
    queryd_component = queryd_create_component(queryd_settings)
    indexed_component = indexed_create_component(indexed_settings)
    mcpd_asgi, mcpd_lifespan, _mcp = mcpd_create_mcp_component(mcpd_settings)

    # ── Unified lifespan ────────────────────────────────────────────────
    @asynccontextmanager
    async def unified_lifespan(app: FastAPI):
        async with contextlib.AsyncExitStack() as stack:
            # Order: indexed before queryd (queryd may call indexed at runtime)
            await stack.enter_async_context(indexed_component.lifespan(app))
            await stack.enter_async_context(queryd_component.lifespan(app))
            await stack.enter_async_context(captured_component.lifespan(app))
            await stack.enter_async_context(mcpd_lifespan(app))
            yield

    # ── FastAPI app ─────────────────────────────────────────────────────
    app = FastAPI(
        title="Firnline Core API",
        lifespan=unified_lifespan,
    )

    # ── Include routers with tags for /docs grouping ────────────────────
    app.include_router(captured_component.router, tags=["captured"])
    app.include_router(queryd_component.router, tags=["queryd"])
    app.include_router(indexed_component.router, tags=["indexed"])

    # ── Mount MCP sub-application ───────────────────────────────────────
    app.mount("/mcp", mcpd_asgi)

    # ── CORS middleware (driven by queryd settings) ─────────────────────
    if queryd_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=queryd_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── /healthz ───────────────────────────────────────────────────────
    @app.get("/healthz")
    async def healthz():
        return JSONResponse(
            content={
                "status": "ok",
                "components": {
                    "captured": "ok",
                    "queryd": "ok",
                    "indexed": "ok",
                    "mcpd": "ok",
                },
            }
        )

    return app
