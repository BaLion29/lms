"""FastAPI application factory for queryd."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import tempfile
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from firnline_core.conventions import blob_root_from_env, parse_agent
from firnline_core.plugins import HostPolicy, PluginHost, ToolPlugin, ToolSpecPlugin
from firnline_core.repository import Repository
from firnline_core.tdb import TdbClient, TdbConflictError, TdbError
from firnline_core.toolspec import ToolContext, ToolSpec
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

from queryd import operations
from queryd.schema_briefing import (
    fetch_introspection,
    fetch_module_list,
    fetch_schema_meta_or_none,
    render_schema_summary,
)
from queryd.settings import Settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PLUGIN_GROUP = "firnline.queryd.tools"

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] | None = None


class FindEntityRequest(BaseModel):
    text: str
    classes: list[str] | None = None
    k: int = 5


class FindClassRequest(BaseModel):
    text: str
    k: int = 5


class FindFieldRequest(BaseModel):
    text: str
    class_name: str | None = None
    k: int = 5


class SchemaSummaryResponse(BaseModel):
    summary: str


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
# IRI validation
# ---------------------------------------------------------------------------


def _validate_doc_iri(iri: str) -> None:
    """Raise ``HTTPException(422)`` if *iri* is not a valid document IRI.

    Rejects path-traversal attacks (``..``), backslashes, leading ``/``,
    and unexpected URL schemes.  Only bare ``Class/id`` and
    ``terminusdb:///data/...`` forms are permitted.
    """
    if not iri:
        raise HTTPException(status_code=422, detail="IRI must not be empty")
    if iri.startswith("/"):
        raise HTTPException(
            status_code=422, detail=f"IRI must not start with '/': {iri}"
        )
    if ".." in iri:
        raise HTTPException(
            status_code=422, detail=f"IRI contains '..' path traversal: {iri}"
        )
    if "\\" in iri:
        raise HTTPException(
            status_code=422, detail=f"IRI contains backslashes: {iri}"
        )
    if "://" in iri and not iri.startswith("terminusdb:///data/"):
        raise HTTPException(
            status_code=422, detail=f"IRI has unexpected scheme: {iri}"
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(
    app: FastAPI,
    settings: Settings,
    *,
    tool_specs_override: dict[str, ToolSpec] | None = None,
):
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        timeout=settings.request_timeout_seconds,
        author="service:queryd",
    )
    app.state.tdb = tdb
    app.state.tool_specs: dict[str, ToolSpec] = {}

    # ── Introspection ──────────────────────────────────────────────────
    schema_summary: str | None = None
    try:
        intro = await fetch_introspection(tdb)
        schema_summary = render_schema_summary(intro)
        log.info("schema introspection succeeded at startup")
    except Exception:
        log.warning("schema introspection failed at startup", exc_info=True)

    schema_summary_cached = schema_summary
    app.state.schema_summary = schema_summary_cached

    # ── Schema @documentation annotations ──────────────────────────────
    schema_docs: dict[str, str] | None = None
    try:
        schema_docs = await fetch_schema_meta_or_none(tdb, branch=settings.tdb_branch)
    except Exception:
        log.warning("schema meta fetch failed", exc_info=True)
    app.state.schema_docs = schema_docs

    # ── Module registry ────────────────────────────────────────────────
    modules: list[dict] = []
    try:
        modules = await fetch_module_list(tdb, branch=settings.tdb_branch)
        log.info("module registry fetched", count=len(modules))
    except Exception:
        log.warning("module registry unavailable — skipping capability section")
    app.state.modules = modules

    # ── Plugin discovery and selection (PluginHost) ────────────────────
    host = PluginHost(
        group=_PLUGIN_GROUP,
        protocol=ToolSpecPlugin,
        tdb=tdb,
        branch=settings.tdb_branch,
        policy=HostPolicy(
            broken_entry_point_fatal=settings.strict_plugins,
            zero_active_fatal=False,
            strict=settings.strict_plugins,
            tdb_unavailable_fatal=False,  # graceful degradation
        ),
        logger=log,
    )

    try:
        result = await host.start(
            registry=modules,
        )
    except RuntimeError:
        raise

    # ── Report active plugins (regardless of enable_writes) ────────────
    active_plugins: list[str] = [
        getattr(obj, "name", ep_name)
        for ep_name, obj in result.active
    ]
    log.info("active plugins", plugins=active_plugins)
    app.state.active_plugins = active_plugins

    # ── Collect ToolSpecs for REST exposure ──
    tool_specs_dict: dict[str, ToolSpec]
    if tool_specs_override is not None:
        tool_specs_dict = (
            dict(tool_specs_override) if settings.enable_writes else {}
        )
    elif settings.enable_writes:
        tool_specs_dict = {}
        for ep_name, obj in result.active:
            if isinstance(obj, ToolSpecPlugin):
                for spec in obj.tool_specs():
                    if spec.name in tool_specs_dict:
                        raise RuntimeError(
                            f"ToolSpec name collision: plugin "
                            f"'{getattr(obj, 'name', ep_name)}' tool "
                            f"'{spec.name}' conflicts with another plugin"
                        )
                    tool_specs_dict[spec.name] = spec
    else:
        tool_specs_dict = {}
    app.state.tool_specs = tool_specs_dict

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
    *,
    tool_specs: dict[str, ToolSpec] | None = None,
) -> FastAPI:
    """Build the FastAPI application for the given *settings*.

    *tool_specs* is a **test seam**: when provided, these ``ToolSpec``
    objects are used for the ``/v1/tools`` REST endpoints instead of
    collecting them from discovered plugins.  When ``None`` (default,
    production), ToolSpecs are collected from plugins that implement
    ``ToolSpecPlugin``.
    """
    _configure_logging()

    @asynccontextmanager
    async def _app_lifespan(app: FastAPI):
        async with _lifespan(
            app, settings,
            tool_specs_override=tool_specs,
        ) as _:
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
        tool_specs_dict: dict[str, object] = getattr(app.state, "tool_specs", {})
        write_tools: list[str] = sorted(tool_specs_dict.keys())

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
                "write_tools": write_tools,
                "blob_root_writable": blob_root_writable,
            },
        )

    # ------------------------------------------------------------------
    # /v1/schema (auth)
    # ------------------------------------------------------------------

    @app.get(
        "/v1/schema",
        response_model=SchemaSummaryResponse,
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_schema():
        """Return the rendered schema summary."""
        schema_summary: str | None = app.state.schema_summary
        if schema_summary is None:
            summary = await operations.get_schema_summary(app.state.tdb)
        else:
            summary = schema_summary
        return SchemaSummaryResponse(summary=summary)

    @app.get(
        "/v1/schema/introspection",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_schema_introspection():
        """Return raw GraphQL introspection JSON."""
        data = await operations.get_introspection(app.state.tdb)
        return JSONResponse(content=data)

    # ------------------------------------------------------------------
    # /v1/modules (auth)
    # ------------------------------------------------------------------

    @app.get(
        "/v1/modules",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_modules():
        """Return the SchemaModule registry docs."""
        modules = await operations.list_modules(
            app.state.tdb,
            branch=app.state.settings.tdb_branch,
        )
        return JSONResponse(content=modules)

    # ------------------------------------------------------------------
    # POST /v1/documents/{class_name} (auth)
    # ------------------------------------------------------------------
    # Registered BEFORE the GET route below so that the narrower
    # {class_name} converter wins over {iri:path} for single-segment
    # paths; otherwise the greedy :path converter shadows POST requests.

    @app.post(
        "/v1/documents/{class_name}",
        status_code=201,
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_document_post(request: Request, class_name: str):
        """Create a new document of *class_name*."""
        settings: Settings = app.state.settings

        # Gate: writes must be enabled
        if not settings.enable_writes:
            raise HTTPException(status_code=403, detail="Writes are disabled")

        # Validate class_name
        if not re.fullmatch(r"^[A-Za-z][A-Za-z0-9_]*$", class_name):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid class name: {class_name!r}",
            )

        # Parse body
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422,
                detail="Request body must be valid JSON",
            )

        if not isinstance(body, dict):
            raise HTTPException(
                status_code=422,
                detail="Request body must be a JSON object",
            )

        if "@type" in body:
            raise HTTPException(
                status_code=422,
                detail="@type must not be present in body; class comes from the URL",
            )

        if "@id" in body:
            raise HTTPException(
                status_code=422,
                detail="@id must not be present in body; server-assigned",
            )

        # Agent identity
        agent = request.headers.get("X-Firnline-Agent", "service:queryd")
        try:
            _ = parse_agent(agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Build and create document
        doc = dict(body)
        doc["@type"] = class_name

        repo = Repository(app.state.tdb)
        try:
            iri = await repo.create(
                doc,
                agent=agent,
                method="direct",
                branch=settings.tdb_branch,
            )
        except TdbConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except TdbError as exc:
            if exc.status == 400:
                raise HTTPException(status_code=422, detail=exc.body)
            raise HTTPException(status_code=502, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return JSONResponse(status_code=201, content={"iri": iri})

    # ------------------------------------------------------------------
    # GET /v1/documents/{iri:path} (auth)
    # ------------------------------------------------------------------

    @app.get(
        "/v1/documents/{iri:path}",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_document_get(iri: str):
        """Fetch a single document by IRI."""
        _validate_doc_iri(iri)
        try:
            doc = await operations.get_document(app.state.tdb, iri)
        except TdbError as exc:
            if exc.status == 404:
                raise HTTPException(status_code=404, detail=f"Document not found: {iri}")
            raise HTTPException(status_code=502, detail=str(exc))
        return JSONResponse(content=doc)

    # ------------------------------------------------------------------
    # /v1/graphql (auth)
    # ------------------------------------------------------------------

    @app.post(
        "/v1/graphql",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_graphql(body: GraphQLRequest):
        """Execute a read-only GraphQL query."""
        try:
            result = await operations.run_graphql(
                app.state.tdb,
                body.query,
                body.variables,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except TdbError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return JSONResponse(content=result)

    # ------------------------------------------------------------------
    # /v1/find/entity (auth)
    # ------------------------------------------------------------------

    @app.post(
        "/v1/find/entity",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_find_entity(body: FindEntityRequest):
        """Search for known entities."""
        s: Settings = app.state.settings
        if not s.indexed_enabled:
            raise HTTPException(
                status_code=503,
                detail="indexed search is disabled (QUERYD_INDEXED_ENABLED=false)",
            )
        try:
            candidates = await operations.find_entity(
                indexed_url=s.indexed_url,
                indexed_token=s.indexed_token,
                indexed_timeout=s.indexed_timeout_seconds,
                text=body.text,
                classes=body.classes,
                branch=s.tdb_branch,
                k=body.k,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return JSONResponse(content={"candidates": candidates})

    # ------------------------------------------------------------------
    # /v1/find/class (auth)
    # ------------------------------------------------------------------

    @app.post(
        "/v1/find/class",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_find_class(body: FindClassRequest):
        """Search for schema classes."""
        s: Settings = app.state.settings
        if not s.indexed_enabled:
            raise HTTPException(
                status_code=503,
                detail="indexed search is disabled (QUERYD_INDEXED_ENABLED=false)",
            )
        try:
            candidates = await operations.find_class(
                indexed_url=s.indexed_url,
                indexed_token=s.indexed_token,
                indexed_timeout=s.indexed_timeout_seconds,
                text=body.text,
                k=body.k,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return JSONResponse(content={"candidates": candidates})

    # ------------------------------------------------------------------
    # /v1/find/field (auth)
    # ------------------------------------------------------------------

    @app.post(
        "/v1/find/field",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_find_field(body: FindFieldRequest):
        """Search for class fields."""
        s: Settings = app.state.settings
        if not s.indexed_enabled:
            raise HTTPException(
                status_code=503,
                detail="indexed search is disabled (QUERYD_INDEXED_ENABLED=false)",
            )
        try:
            candidates = await operations.find_field(
                indexed_url=s.indexed_url,
                indexed_token=s.indexed_token,
                indexed_timeout=s.indexed_timeout_seconds,
                text=body.text,
                class_name=body.class_name,
                k=body.k,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return JSONResponse(content={"candidates": candidates})

    # ------------------------------------------------------------------
    # /v1/tools (auth) — list available write tools
    # ------------------------------------------------------------------

    @app.get(
        "/v1/tools",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_tools():
        specs: dict[str, object] = app.state.tool_specs
        tools_list = sorted(
            [
                {
                    "name": name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for name, spec in specs.items()
            ],
            key=lambda t: t["name"],
        )
        return JSONResponse(content={"tools": tools_list})

    # ------------------------------------------------------------------
    # /v1/tools/{name} (auth) — invoke a specific write tool
    # ------------------------------------------------------------------

    @app.post(
        "/v1/tools/{name}",
        dependencies=[Depends(_bearer_auth)],
    )
    async def v1_tools_call(name: str, request: Request):
        specs: dict[str, object] = app.state.tool_specs
        spec: ToolSpec | None = specs.get(name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown tool: {name}")

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="invalid JSON body")

        try:
            args = spec.args_model(**body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(),
            )

        ctx = ToolContext(tdb=app.state.tdb, branch=app.state.settings.tdb_branch)

        try:
            async with asyncio.timeout(app.state.settings.request_timeout_seconds):
                result = await spec.handler(args, ctx)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"detail": "request timed out"},
            )
        except Exception:
            log.error("tool handler error", tool=name, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={"detail": "tool execution failed"},
            )

        return JSONResponse(content=result)

    return app
