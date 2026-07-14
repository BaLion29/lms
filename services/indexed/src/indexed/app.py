"""FastAPI application for indexed — hybrid search API."""

from __future__ import annotations

import asyncio
import pathlib
import secrets
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from firnline_core.plugins import (
    HostPolicy,
    IndexerPlugin,
    PluginHost,
)
from firnline_core.tdb import TdbClient

from indexed.embed import embed_texts
from indexed.poller import Poller
from indexed.settings import Settings
from indexed.store import Store

log = structlog.get_logger()

_INDEXER_GROUP = "firnline.indexed.indexers"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FindEntityRequest(BaseModel):
    text: str = Field(min_length=1)
    classes: list[str] | None = None
    branch: str = "main"
    k: int = Field(default=5, ge=1, le=50)


class FindEntityCandidate(BaseModel):
    iri: str
    class_name: str = Field(alias="class")
    name: str
    aliases: list[str] = []
    score: float
    commit_id: str


class FindEntityResponse(BaseModel):
    candidates: list[FindEntityCandidate]
    commit_id: str


class FindClassRequest(BaseModel):
    text: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)


class FindClassCandidate(BaseModel):
    class_name: str = Field(alias="class")
    description: str
    score: float


class FindClassResponse(BaseModel):
    candidates: list[FindClassCandidate]


class FindFieldRequest(BaseModel):
    text: str = Field(min_length=1)
    class_name: str | None = Field(default=None, alias="class")
    k: int = Field(default=5, ge=1, le=50)


class FindFieldCandidate(BaseModel):
    class_name: str = Field(alias="class")
    field: str
    type: str
    description: str
    score: float


class FindFieldResponse(BaseModel):
    candidates: list[FindFieldCandidate]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _bearer_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    token = settings.api_token
    if not token:
        return
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="unauthorized")
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="unauthorized")
    if not secrets.compare_digest(parts[1], token):
        raise HTTPException(status_code=401, detail="unauthorized")


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


async def _discover_indexer_plugins(
    tdb: TdbClient,
    branch: str,
    strict: bool = False,
) -> list[IndexerPlugin]:
    host = PluginHost(
        group=_INDEXER_GROUP,
        protocol=IndexerPlugin,
        tdb=tdb,
        branch=branch,
        policy=HostPolicy(
            broken_entry_point_fatal=strict,
            zero_active_fatal=False,
            strict=strict,
        ),
        logger=log,
    )
    result = await host.start(collision_key=lambda p: p.indexed_classes())
    return [obj for _, obj in result.active]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


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


def create_app(settings: Settings) -> FastAPI:
    _configure_logging()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        tdb = TdbClient(
            base_url=settings.tdb_url,
            org=settings.tdb_org,
            db=settings.tdb_db,
            user=settings.tdb_user,
            password=settings.tdb_password,
            author="service:indexed",
        )
        store = Store(settings.data_dir + "/index.db")
        store.open()
        app.state.started_at = time.monotonic()
        app.state.tdb = tdb
        app.state.store = store

        branch = settings.tdb_branch

        try:
            indexer_plugins = await _discover_indexer_plugins(tdb, branch, strict=settings.strict_plugins)
        except (RuntimeError, ValueError):
            log.exception("indexer_plugin_discovery_failed")
            raise

        log.info(
            "indexer_startup_complete",
            plugin_count=len(indexer_plugins),
            plugin_names=[p.name for p in indexer_plugins],
            indexed_classes=[cls for p in indexer_plugins for cls in p.indexed_classes()],
        )

        poller = Poller(tdb, store, settings, indexer_plugins)
        app.state.poller = poller

        stop_event = asyncio.Event()

        async def _poll_loop() -> None:
            liveness_path = pathlib.Path(settings.liveness_file)
            while not stop_event.is_set():
                try:
                    ok = await poller.sync_once()
                    if ok and not settings.dry_run:
                        try:
                            liveness_path.touch(exist_ok=True)
                        except OSError:
                            pass
                except Exception:
                    log.exception("poller_cycle_failed")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass

        poll_task = asyncio.create_task(_poll_loop())

        try:
            yield
        finally:
            stop_event.set()
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            store.close()
            await tdb.aclose()

    app = FastAPI(title="indexed", lifespan=_lifespan)
    app.state.settings = settings

    # ------------------------------------------------------------------
    # /healthz
    # ------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        liveness_path = pathlib.Path(settings.liveness_file)
        alive = False
        try:
            if liveness_path.exists():
                mtime = liveness_path.stat().st_mtime
                alive = (time.time() - mtime) < 300
        except OSError:
            pass

        # Startup grace: treat poller as alive before the first poll cycle
        # has had a chance to run (2 * poll_interval_seconds).
        if not alive:
            started_at = getattr(app.state, "started_at", None)
            if started_at is None or (time.monotonic() - started_at) < (settings.poll_interval_seconds * 2):
                alive = True

        tdb_ok = False
        try:
            tdb_ok = await app.state.tdb.db_exists()
        except Exception:
            pass

        store = app.state.store
        store_ok = False
        try:
            store.get_last_commit(settings.tdb_branch)
            store_ok = True
        except Exception:
            pass

        status = "ok" if (alive and tdb_ok) else "degraded"
        status_code = 200 if (alive and tdb_ok) else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": status,
                "terminusdb": "up" if tdb_ok else "down",
                "store": "ok" if store_ok else "error",
                "poller": "alive" if alive else "stale",
            },
        )

    # ------------------------------------------------------------------
    # /v1/find_entity
    # ------------------------------------------------------------------

    @app.post("/v1/find_entity", dependencies=[Depends(_bearer_auth)])
    async def find_entity(body: FindEntityRequest):
        store: Store = app.state.store
        settings_obj: Settings = app.state.settings

        branch = body.branch or settings_obj.tdb_branch

        query_vector: list[float] = []
        if body.text.strip():
            try:
                embeddings = await embed_texts(
                    base_url=settings_obj.llm_base_url,
                    api_key=settings_obj.llm_api_key,
                    model=settings_obj.embedding_model,
                    texts=[body.text],
                    batch_size=1,
                )
                query_vector = embeddings[0]
            except Exception:
                log.warning("embedding_failed_entity_search", exc_info=True)

        candidates = store.search_entities(
            body.text,
            query_vector,
            classes=body.classes,
            branch=branch,
            k=body.k,
            min_confidence=settings_obj.min_confidence,
        )

        commit_id = store.get_last_commit(branch)

        return FindEntityResponse(
            candidates=[
                FindEntityCandidate(
                    iri=c.iri,
                    class_name=c.class_name,
                    name=c.name,
                    aliases=c.aliases,
                    score=c.score,
                    commit_id=c.commit_id,
                )
                for c in candidates
            ],
            commit_id=commit_id,
        )

    # ------------------------------------------------------------------
    # /v1/find_class
    # ------------------------------------------------------------------

    @app.post("/v1/find_class", dependencies=[Depends(_bearer_auth)])
    async def find_class(body: FindClassRequest):
        store: Store = app.state.store
        settings_obj: Settings = app.state.settings

        query_vector: list[float] = []
        if body.text.strip():
            try:
                embeddings = await embed_texts(
                    base_url=settings_obj.llm_base_url,
                    api_key=settings_obj.llm_api_key,
                    model=settings_obj.embedding_model,
                    texts=[body.text],
                    batch_size=1,
                )
                query_vector = embeddings[0]
            except Exception:
                log.warning("embedding_failed_class_search", exc_info=True)

        candidates = store.search_schema(
            body.text,
            query_vector,
            kind="class",
            k=body.k,
            min_confidence=settings_obj.min_confidence,
        )

        return FindClassResponse(
            candidates=[
                FindClassCandidate(
                    class_name=c.class_name,
                    description=c.docstring,
                    score=c.score,
                )
                for c in candidates
            ],
        )

    # ------------------------------------------------------------------
    # /v1/find_field
    # ------------------------------------------------------------------

    @app.post("/v1/find_field", dependencies=[Depends(_bearer_auth)])
    async def find_field(body: FindFieldRequest):
        store: Store = app.state.store
        settings_obj: Settings = app.state.settings

        query_vector: list[float] = []
        if body.text.strip():
            try:
                embeddings = await embed_texts(
                    base_url=settings_obj.llm_base_url,
                    api_key=settings_obj.llm_api_key,
                    model=settings_obj.embedding_model,
                    texts=[body.text],
                    batch_size=1,
                )
                query_vector = embeddings[0]
            except Exception:
                log.warning("embedding_failed_field_search", exc_info=True)

        candidates = store.search_schema(
            body.text,
            query_vector,
            kind="field",
            class_name=body.class_name,
            k=body.k,
            min_confidence=settings_obj.min_confidence,
        )

        return FindFieldResponse(
            candidates=[
                FindFieldCandidate(
                    class_name=c.class_name,
                    field=c.field,
                    type=c.type_hint,
                    description=c.docstring,
                    score=c.score,
                )
                for c in candidates
            ],
        )

    return app
