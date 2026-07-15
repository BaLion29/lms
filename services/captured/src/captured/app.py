"""FastAPI application factory for captured."""

from __future__ import annotations

import json
import secrets
import tempfile
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import structlog
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from firnline_core.conventions import BlobStore, blob_root_from_env
from firnline_core.plugins import (
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    HostPolicy,
    PluginHost,
)
from firnline_core.logging import configure_logging
from firnline_core.tdb import TdbClient

from captured.settings import Settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Plugin entry-point group
# ---------------------------------------------------------------------------

_PLUGIN_GROUP = "firnline.captured.handlers"


# ---------------------------------------------------------------------------
# Component state & component
# ---------------------------------------------------------------------------


@dataclass
class ComponentState:
    """Service-specific resources, populated by the component lifespan."""

    settings: Settings
    blob_root: Path | None = None
    blob_store: BlobStore | None = None
    tdb: TdbClient | None = None
    handlers: list[CaptureHandler] = field(default_factory=list)
    handler_names: list[str] = field(default_factory=list)
    kind_map: dict[str, CaptureHandler] = field(default_factory=dict)


@dataclass
class Component:
    """Composable FastAPI component: router + lifespan + shared state."""

    router: APIRouter
    lifespan: Callable[[Any], AbstractAsyncContextManager[None]]
    state: ComponentState


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_captured_at(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string with mandatory timezone info.

    Accepts ``Z`` as UTC suffix.  Returns ``None`` when *value* is ``None``.
    Raises ``ValueError`` on invalid or naive timestamps.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(
            "captured_at must be an ISO 8601 datetime with timezone"
        ) from None
    if dt.tzinfo is None:
        raise ValueError(
            "captured_at must be an ISO 8601 datetime with timezone"
        )
    return dt


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("captured")
    except Exception:
        return "dev"


def _probe_blob_root_writable(root: Path) -> bool:
    """Probe whether *root* is writable by creating and deleting a tempfile."""
    try:
        tmp = tempfile.NamedTemporaryFile(dir=root, delete=False)
        try:
            tmp.close()
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        return True
    except Exception:
        return False


async def _dispatch(payload: CapturePayload, state: ComponentState) -> str:
    """Resolve the handler for *payload.kind* and invoke it.

    Returns the document id returned by the handler.  Raises
    ``HTTPException`` for unknown kinds or handler errors.
    """
    kind_map = state.kind_map
    handler = kind_map.get(payload.kind)
    if handler is None:
        known = sorted(kind_map.keys())
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"no handler for kind '{payload.kind}'",
                "known_kinds": known,
                "hint": "Install a captured handler extension that supports this kind.",
            },
        )

    ctx = CaptureContext(
        tdb=state.tdb,
        blob_store=state.blob_store,
        logger=log,
    )

    try:
        return await handler.handle(payload, ctx)
    except HTTPException:
        raise
    except Exception:
        log.exception("capture handler raised", handler=handler.name, kind=payload.kind)
        raise HTTPException(status_code=500, detail="capture processing failed")


# ---------------------------------------------------------------------------
# Component factory
# ---------------------------------------------------------------------------


def create_component(settings: Settings | None = None) -> Component:
    """Build a composable :class:`Component` for the captured service.

    The returned ``Component`` can be embedded into any FastAPI app via
    ``app.include_router(component.router)`` and
    ``FastAPI(lifespan=component.lifespan, ...)``.
    """
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]

    blob_root = blob_root_from_env()
    blob_store = BlobStore(blob_root) if blob_root else None

    state = ComponentState(
        settings=settings,
        blob_root=blob_root,
        blob_store=blob_store,
    )

    # ── Auth dependency (closes over state.settings) ─────────────────────
    def _bearer_auth(request: Request) -> None:
        """Validate ``Authorization: Bearer <token>`` header."""
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
        if not secrets.compare_digest(parts[1], state.settings.api_token):
            raise HTTPException(
                status_code=401,
                detail="unauthorized",
            )

    # ── APIRouter with /v1 routes ────────────────────────────────────────
    router = APIRouter()

    @router.post("/v1/capture/note", dependencies=[Depends(_bearer_auth)])
    async def v1_capture_note(request: Request):
        # Reject non-text/plain content types
        content_type = request.headers.get("content-type", "")
        if not content_type:
            raise HTTPException(
                status_code=415,
                detail="Content-Type header is required; expected text/plain",
            )
        # Split on ";" to handle charset parameter
        media_type = content_type.split(";")[0].strip().lower()
        if media_type != "text/plain":
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported media type '{media_type}'; expected text/plain",
            )

        body_bytes = await request.body()
        if not body_bytes:
            raise HTTPException(
                status_code=422,
                detail="note text must not be empty",
            )
        try:
            text = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=422,
                detail="request body must be valid UTF-8 text",
            )

        # Parse captured_at from X-Captured-At header
        captured_at: datetime | None = None
        captured_at_raw = request.headers.get("X-Captured-At")
        if captured_at_raw:
            try:
                captured_at = _parse_captured_at(captured_at_raw)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

        payload = CapturePayload(
            kind="note",
            text=text,
            captured_at=captured_at,
        )
        doc_id = await _dispatch(payload, state)
        return JSONResponse(
            status_code=201,
            content={"id": doc_id, "kind": "note"},
        )

    @router.post("/v1/capture/file", dependencies=[Depends(_bearer_auth)])
    async def v1_capture_file(
        file: UploadFile = File(...),
        kind: str = Form(default="file"),
        metadata: str = Form(default="{}"),
        captured_at: str | None = Form(default=None),
    ):
        blob_store_local: BlobStore | None = state.blob_store
        if blob_store_local is None:
            raise HTTPException(
                status_code=503,
                detail="blob storage not configured (FIRNLINE_BLOB_ROOT is unset)",
            )

        # Parse metadata JSON
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422,
                detail="metadata must be valid JSON",
            )
        if not isinstance(meta, dict):
            raise HTTPException(
                status_code=422,
                detail="metadata must be a JSON object",
            )

        # Parse captured_at (ISO datetime, optional)
        captured_at_dt: datetime | None = None
        if captured_at:
            try:
                captured_at_dt = _parse_captured_at(captured_at)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

        # Read file bytes (with size cap)
        data = await file.read()
        max_bytes = state.settings.max_upload_bytes
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds maximum size of {max_bytes} bytes",
            )

        # Store blob — BlobStore derives ext/mime from suggested_name
        blob_ref = blob_store_local.put(data, suggested_name=file.filename)

        payload = CapturePayload(
            kind=kind,
            blob_sha256=blob_ref.sha256,
            filename=file.filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            metadata=meta,
            captured_at=captured_at_dt,
        )
        doc_id = await _dispatch(payload, state)
        return JSONResponse(
            status_code=201,
            content={
                "id": doc_id,
                "kind": kind,
                "sha256": blob_ref.sha256,
                "size": blob_ref.size,
            },
        )

    # ── Lifespan (closes over state, settings, blob_root, blob_store) ────
    @asynccontextmanager
    async def lifespan(app: Any):
        tdb = TdbClient(
            base_url=settings.tdb_url,
            org=settings.tdb_org,
            db=settings.tdb_db,
            user=settings.tdb_user,
            password=settings.tdb_password,
            author="service:captured",
        )
        state.tdb = tdb

        # Mirror onto app.state for backward compatibility (healthz, existing tests)
        if hasattr(app, "state"):
            app.state.settings = settings
            app.state.tdb = tdb
            app.state.blob_root = blob_root
            app.state.blob_store = blob_store

        try:
            # ── Plugin startup via PluginHost ────────────────────────────
            policy = HostPolicy(
                broken_entry_point_fatal=True,
                tdb_unavailable_fatal=False,
                strict=settings.strict_plugins,
            )
            host = PluginHost(
                group=_PLUGIN_GROUP,
                protocol=CaptureHandler,
                tdb=tdb,
                branch=settings.tdb_branch,
                policy=policy,
                logger=log,
            )
            result = await host.start(
                collision_key=lambda h: list(h.kinds),
            )

            # ── Build kind → handler map ─────────────────────────────────
            handlers: list[CaptureHandler] = []
            handler_names: list[str] = []
            kind_map: dict[str, CaptureHandler] = {}

            for _ep_name, obj in result.active:
                if not isinstance(obj, CaptureHandler):
                    log.warning(
                        "plugin does not satisfy CaptureHandler protocol",
                        name=getattr(obj, "name", _ep_name),
                    )
                    continue

                handler = obj
                handlers.append(handler)
                handler_names.append(handler.name)

                for kind_name in handler.kinds:
                    kind_map[kind_name] = handler  # collisions already caught by host

            state.handlers = handlers
            state.handler_names = handler_names
            state.kind_map = kind_map

            # Mirror
            if hasattr(app, "state"):
                app.state.handlers = handlers
                app.state.handler_names = handler_names
                app.state.kind_map = kind_map

            if handlers:
                log.info(
                    "active capture handlers",
                    handlers=handler_names,
                    kinds=list(kind_map.keys()),
                )
            else:
                log.warning("no capture handlers registered — all captures will 404")

            yield
        finally:
            await tdb.aclose()

    return Component(router=router, lifespan=lifespan, state=state)


# ---------------------------------------------------------------------------
# App factory (standalone)
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the standalone FastAPI application for the given *settings*."""
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]

    configure_logging(settings.log_level)

    component = create_component(settings)

    app = FastAPI(
        title="captured",
        lifespan=component.lifespan,
    )
    app.include_router(component.router)

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

        # Live fetch module versions
        module_versions: dict[str, str] = {}
        try:
            module_docs = await app.state.tdb.get_documents(
                "SchemaModule", branch=app.state.settings.tdb_branch
            )
            for doc in module_docs:
                name = doc.get("name")
                ver = doc.get("version")
                if name and ver:
                    module_versions[name] = ver
        except Exception:
            log.warning("healthz: module registry fetch failed")

        handler_names: list[str] = app.state.handler_names

        # Blob root writability
        blob_root_local: Path | None = app.state.blob_root
        blob_root_writable: bool | None = None
        if blob_root_local is not None:
            blob_root_writable = _probe_blob_root_writable(blob_root_local)

        status = "ok" if tdb_ok else "degraded"
        status_code = 200 if tdb_ok else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": status,
                "terminusdb": "up" if tdb_ok else "down",
                "version": _get_version(),
                "modules": module_versions,
                "handlers": handler_names,
                "blob_root_writable": blob_root_writable,
            },
        )

    return app
