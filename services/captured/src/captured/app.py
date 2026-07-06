"""FastAPI application factory for captured."""

from __future__ import annotations

import json
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms_core.conventions import BlobStore, blob_root_from_env
from lms_core.plugins import (
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    discover_plugins,
    select_plugins,
)
from lms_core.tdb import TdbClient

from captured.settings import Settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Plugin entry-point group
# ---------------------------------------------------------------------------

_PLUGIN_GROUP = "lms.captured.handlers"

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class NoteRequest(BaseModel):
    text: str
    kind: str = "note"
    metadata: dict[str, Any] = {}


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
async def _lifespan(app: FastAPI, settings: Settings):
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
    )
    app.state.tdb = tdb

    try:
        # ── Plugin discovery and selection ─────────────────────────────────
        discovered = discover_plugins(_PLUGIN_GROUP)
        log.info(
            "plugins discovered",
            group=_PLUGIN_GROUP,
            count=len(discovered.active),
            failed=len(discovered.failed),
        )

        # Broken entry points are fatal
        if discovered.failed:
            for name, err in discovered.failed:
                log.error("plugin failed to load", plugin=name, error=err)
            raise RuntimeError(
                f"Plugin discovery failures in group '{_PLUGIN_GROUP}': "
                + ", ".join(n for n, _ in discovered.failed)
            )

        # ── Plugin selection (graceful degradation on TerminusDB errors) ──
        selection: object
        try:
            selection = await select_plugins(
                tdb,
                discovered,
                strict=False,
                branch=settings.tdb_branch,
            )
        except Exception:
            log.warning(
                "plugin selection failed — TerminusDB unreachable; "
                "starting with no capture handlers",
                exc_info=True,
            )
            selection = None

        # ── Build kind → handler map ───────────────────────────────────────
        handlers: list[CaptureHandler] = []
        handler_names: list[str] = []
        kind_map: dict[str, CaptureHandler] = {}

        if selection is not None:
            for name, violations in selection.skipped:
                log.warning(
                    "handler plugin skipped (unmet requirements)",
                    plugin=name,
                    violations=violations,
                )

            for _ep_name, obj in selection.active:
                if not isinstance(obj, CaptureHandler):
                    log.warning("plugin does not satisfy CaptureHandler protocol", name=getattr(obj, "name", _ep_name))
                    continue

                handler = obj
                handlers.append(handler)
                handler_names.append(handler.name)

                for kind in handler.kinds:
                    if kind in kind_map:
                        existing = kind_map[kind]
                        raise RuntimeError(
                            f"Kind collision: '{kind}' claimed by both "
                            f"'{handler.name}' and '{existing.name}'"
                        )
                    kind_map[kind] = handler

        app.state.handlers = handlers
        app.state.handler_names = handler_names
        app.state.kind_map = kind_map

        if handlers:
            log.info("active capture handlers", handlers=handler_names, kinds=list(kind_map.keys()))
        else:
            log.warning("no capture handlers registered — all captures will 404")

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

def _dispatch(payload: CapturePayload, app: FastAPI) -> str:
    """Resolve the handler for *payload.kind* and invoke it.
    Returns the document id returned by the handler.  Raises
    ``HTTPException`` for unknown kinds or handler errors.
    """
    kind_map: dict[str, CaptureHandler] = app.state.kind_map
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

    blob_store = app.state.blob_store if hasattr(app.state, "blob_store") else None
    ctx = CaptureContext(
        tdb=app.state.tdb,
        blob_store=blob_store,
        logger=log,
    )

    try:
        return handler.handle(payload, ctx)
    except Exception:
        log.exception("capture handler raised", handler=handler.name, kind=payload.kind)
        raise HTTPException(status_code=500, detail="capture processing failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application for the given *settings*."""
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]

    _configure_logging()

    @asynccontextmanager
    async def _app_lifespan(app: FastAPI):
        async with _lifespan(app, settings) as _:
            yield

    app = FastAPI(
        title="captured",
        lifespan=_app_lifespan,
    )
    app.state.settings = settings

    # Blob store (optional)
    blob_root = blob_root_from_env()
    app.state.blob_root = blob_root
    app.state.blob_store = BlobStore(blob_root) if blob_root else None

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
        blob_root: Path | None = app.state.blob_root
        blob_root_writable: bool | None = None
        if blob_root is not None:
            blob_root_writable = _probe_blob_root_writable(blob_root)

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

    # ------------------------------------------------------------------
    # POST /v1/capture/note (auth)
    # ------------------------------------------------------------------

    @app.post("/v1/capture/note", dependencies=[Depends(_bearer_auth)])
    async def v1_capture_note(body: NoteRequest):
        payload = CapturePayload(
            kind=body.kind,
            text=body.text,
            metadata=body.metadata,
        )
        doc_id = _dispatch(payload, app)
        return JSONResponse(
            status_code=201,
            content={"id": doc_id, "kind": body.kind},
        )

    # ------------------------------------------------------------------
    # POST /v1/capture/file (auth, multipart)
    # ------------------------------------------------------------------

    @app.post("/v1/capture/file", dependencies=[Depends(_bearer_auth)])
    async def v1_capture_file(
        file: UploadFile = File(...),
        kind: str = Form(default="file"),
        metadata: str = Form(default="{}"),
    ):
        blob_store: BlobStore | None = app.state.blob_store
        if blob_store is None:
            raise HTTPException(
                status_code=503,
                detail="blob storage not configured (LMS_BLOB_ROOT is unset)",
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

        # Read file bytes (with size cap)
        data = await file.read()
        max_bytes = app.state.settings.max_upload_bytes
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds maximum size of {max_bytes} bytes",
            )

        filename = file.filename

        # Derive extension from filename; fall back to extensionless on unsafe
        suffix = Path(filename).suffix if filename else ""
        ext = suffix if suffix and len(suffix) > 1 else ""

        # Store blob (with fallback on unsafe extension)
        try:
            blob_ref = blob_store.put(data, ext=ext)
        except ValueError:
            blob_ref = blob_store.put(data, ext="")

        payload = CapturePayload(
            kind=kind,
            blob_sha256=blob_ref.sha256,
            filename=filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            metadata=meta,
        )
        doc_id = _dispatch(payload, app)
        return JSONResponse(
            status_code=201,
            content={"id": doc_id, "kind": kind, "sha256": blob_ref.sha256},
        )

    return app
