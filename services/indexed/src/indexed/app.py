"""FastAPI application for indexed — hybrid search API."""

from __future__ import annotations

import asyncio
import pathlib
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from firnline_core.logging import configure_logging
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
    model_config = ConfigDict(populate_by_name=True)
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
    model_config = ConfigDict(populate_by_name=True)
    class_name: str = Field(alias="class")
    description: str
    score: float


class FindClassResponse(BaseModel):
    candidates: list[FindClassCandidate]


class FindFieldRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    text: str = Field(min_length=1)
    class_name: str | None = Field(default=None, alias="class")
    k: int = Field(default=5, ge=1, le=50)


class FindFieldCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    class_name: str = Field(alias="class")
    field: str
    type: str
    description: str
    score: float


class FindFieldResponse(BaseModel):
    candidates: list[FindFieldCandidate]


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
# Component state
# ---------------------------------------------------------------------------


@dataclass
class ComponentState:
    """Service-specific resources populated by the component lifespan.

    All fields are ``None`` until the lifespan runs.  Tests and embedding
    hosts can inspect this dataclass directly after the lifespan has
    executed.
    """

    settings: Settings | None = None
    tdb: TdbClient | None = None
    store: Store | None = None
    poller: Poller | None = None
    started_at: float | None = None


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """Composable component that can be embedded in a combined FastAPI app."""

    router: APIRouter
    lifespan: Callable[[Any], AbstractAsyncContextManager[None]]
    state: ComponentState


# ---------------------------------------------------------------------------
# Component factory
# ---------------------------------------------------------------------------


def create_component(settings: Settings | None = None) -> Component:
    """Build a composable ``Component`` with routes, lifespan, and shared state.

    Parameters
    ----------
    settings:
        Application settings.  When *None*, a default ``Settings()`` is
        created from environment variables (``INDEXED_`` prefix).

    Returns
    -------
    Component
        Ready-to-embed component whose router carries ``/v1`` endpoints
        and whose lifespan manages service resources.
    """
    if settings is None:
        settings = Settings()

    state = ComponentState(settings=settings)
    router = APIRouter()

    # ------------------------------------------------------------------
    # Auth (closes over *state*)
    # ------------------------------------------------------------------

    async def _bearer_auth(request: Request) -> None:
        token = state.settings.api_token  # type: ignore[union-attr]
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

    # ------------------------------------------------------------------
    # /v1/find_entity
    # ------------------------------------------------------------------

    @router.post("/v1/find_entity", dependencies=[Depends(_bearer_auth)])
    async def find_entity(body: FindEntityRequest):
        store_obj: Store = state.store  # type: ignore[assignment]
        settings_obj: Settings = state.settings  # type: ignore[assignment]

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

        candidates = store_obj.search_entities(
            body.text,
            query_vector,
            classes=body.classes,
            branch=branch,
            k=body.k,
            min_confidence=settings_obj.min_confidence,
        )

        commit_id = store_obj.get_last_commit(branch)

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

    @router.post("/v1/find_class", dependencies=[Depends(_bearer_auth)])
    async def find_class(body: FindClassRequest):
        store_obj: Store = state.store  # type: ignore[assignment]
        settings_obj: Settings = state.settings  # type: ignore[assignment]

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

        candidates = store_obj.search_schema(
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

    @router.post("/v1/find_field", dependencies=[Depends(_bearer_auth)])
    async def find_field(body: FindFieldRequest):
        store_obj: Store = state.store  # type: ignore[assignment]
        settings_obj: Settings = state.settings  # type: ignore[assignment]

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

        candidates = store_obj.search_schema(
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

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
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
        started = time.monotonic()

        # Populate component state
        state.tdb = tdb
        state.store = store
        state.started_at = started

        # Backward compat: mirror onto app.state for code that still
        # reads from there (e.g. existing tests or middleware).
        if hasattr(app, "state"):
            app.state.tdb = tdb
            app.state.store = store
            app.state.settings = settings
            app.state.started_at = started

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
        state.poller = poller
        if hasattr(app, "state"):
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

    return Component(router=router, lifespan=lifespan, state=state)


# ---------------------------------------------------------------------------
# Standalone FastAPI application
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a standalone FastAPI app (behaviour unchanged).

    Delegates to :func:`create_component` and adds a ``/healthz`` probe.
    """
    if settings is None:
        settings = Settings()
    configure_logging(settings.log_level)

    component = create_component(settings)

    app = FastAPI(title="indexed", lifespan=component.lifespan)
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
            started_at = component.state.started_at
            if started_at is None or (time.monotonic() - started_at) < (settings.poll_interval_seconds * 2):
                alive = True

        tdb_ok = False
        try:
            if component.state.tdb:
                tdb_ok = await component.state.tdb.db_exists()
        except Exception:
            pass

        store_obj = component.state.store
        store_ok = False
        try:
            if store_obj:
                store_obj.get_last_commit(settings.tdb_branch)
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

    app.include_router(component.router)
    return app
