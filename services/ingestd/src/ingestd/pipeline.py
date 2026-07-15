"""Extraction pipeline — processes inbox documents through LLM extraction → TDB insertion.

Generic: polls source plugins, runs extraction via the ExtractionContext (built
at startup from ExtractorPlugins), and dispatches document building per proposal
kind.  One insert_documents commit per inbox item.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from ingestd.extraction import ExtractionContext, extract
from ingestd.linking import (
    EntityIndex,
    LinkingConfig,
    async_match,
    build_index_from_classes,
    match,
)
from ingestd.settings import Settings
from firnline_core.models import _format_datetime
from firnline_core.plugins import BuildContext
from firnline_core.tdb import TdbClient, TdbError, short_iri

logger = structlog.get_logger(__name__)


class Pipeline:
    """Main extraction pipeline: fetch inbox docs, run extraction, insert results.

    Extraction can be injected via *extract_fn* (defaults to
    ``ingestd.extraction.extract``) for testability.
    """

    def __init__(
        self,
        tdb: TdbClient,
        agent: Any,
        settings: Settings,
        *,
        source_plugins: list[Any],
        extraction_ctx: ExtractionContext,
        extract_fn: Any = None,
    ) -> None:
        self.tdb = tdb
        self.agent = agent
        self.settings = settings
        self._extract = extract_fn or extract
        self._source_plugins = source_plugins
        self._extraction_ctx = extraction_ctx

        # Extract unique extractor plugins from context (for linking_context)
        seen: set[int] = set()
        self._extractor_plugins: list[Any] = []
        for plugin in extraction_ctx.plugins:
            pid = id(plugin)
            if pid not in seen:
                seen.add(pid)
                self._extractor_plugins.append(plugin)

        # Compute linkable classes from union of produces across active extractors
        self._linkable_classes: list[str] = sorted(
            {
                cls_name
                for p in self._extractor_plugins
                for cls_name in getattr(p, "produces", [])
            }
        )

        # Per-cycle idempotency state — reset at the top of each run_cycle call
        self._idempotency_graphql_ok: bool = True
        self._idempotency_fallback_cache: set[str] | None = None
        self._idempotency_path_logged: bool = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: asyncio.Event | None = None) -> None:
        """Execute one full extraction cycle.

        1. Build generic EntityIndex from all ``produces`` classes.
        2. Build linking context block from all extractor plugins.
        3. Gather inbox documents from each source plugin (generic poll).
        4. Process each inbox doc sequentially, respecting *should_stop*.
           Idempotency is checked per-item via GraphQL point lookup,
           with a cached class-scan fallback on failure.
        """
        branch = self.settings.tdb_branch

        # Reset per-cycle idempotency state
        self._idempotency_graphql_ok = True
        self._idempotency_fallback_cache = None
        self._idempotency_path_logged = False

        # ----- Entity index -----
        index = await build_index_from_classes(
            self.tdb, self._linkable_classes, branch
        )

        # ----- Linking context -----
        context_block = await self._build_linking_context(index)

        # ----- Gather work from source plugins -----
        all_inbox: list[tuple[dict[str, Any], Any]] = []
        for src in self._source_plugins:
            try:
                docs = await self.tdb.get_documents_by_status(
                    src.document_type,
                    src.ready_status,
                    branch,
                )
                for doc in docs:
                    all_inbox.append((doc, src))
            except Exception:
                logger.exception(
                    "source_poll_failed",
                    source=src.name,
                )

        if not all_inbox:
            logger.info("cycle_complete", inbox_count=0)
            return

        # ----- Process sequentially -----
        for doc, src in all_inbox:
            if should_stop and should_stop.is_set():
                logger.info("shutdown_requested", remaining=len(all_inbox))
                break

            doc_iri = short_iri(doc.get("@id", ""))
            logger.info("processing_inbox_doc", iri=doc_iri, source=src.name)

            try:
                await self._process_one(doc, src, index, context_block)
            except Exception:
                logger.error(
                    "unexpected_error",
                    iri=doc_iri,
                    exc_info=True,
                )
                try:
                    await self._flip_status(doc, src.failed_status)
                except Exception:
                    logger.error(
                        "failed_to_flip_status",
                        iri=doc_iri,
                        exc_info=True,
                    )

        logger.info("cycle_complete", inbox_count=len(all_inbox))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _build_linking_context(self, index: EntityIndex) -> str:
        """Build linking context from each extractor plugin's contribution."""
        parts: list[str] = []

        for plugin in self._extractor_plugins:
            try:
                lc = await plugin.linking_context(
                    self.tdb, index=index, branch=self.settings.tdb_branch
                )
                if lc and lc.strip():
                    parts.append(lc)
            except Exception:
                logger.warning(
                    "linking_context_failed",
                    plugin=plugin.name,
                    exc_info=True,
                )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def _check_idempotency(self, doc_iri: str, branch: str) -> bool:
        """Return ``True`` if *doc_iri* was already derived from.

        Primary path: per-item GraphQL point lookup using a filtered
        ``Entity`` query on ``derived_from``.

        Fallback: single class-scan per cycle, cached after first TdbError
        on the GraphQL path.  Logs which path was used once per cycle at
        INFO, and each fallback-triggering failure at WARNING.
        """
        if self._idempotency_graphql_ok:
            try:
                query = (
                    "query($src: String) {"
                    "  Entity(filter: { derived_from: { eq: $src } }) {"
                    "    _id"
                    "  }"
                    "}"
                )
                data = await self.tdb.graphql(
                    query, variables={"src": doc_iri}, branch=branch
                )
                entities = data.get("Entity", [])

                # When TerminusDB returns ``"Entity": null`` (abstract-class
                # query unsupported or empty), ``data.get`` yields None, which
                # would bypass the isinstance-list check below and cause
                # reprocessing every cycle.  Treat null as "unknown" →
                # fall through to the class-scan fallback path.
                if entities is None:
                    if not self._idempotency_path_logged:
                        logger.warning(
                            "idempotency_graphql_null_entity",
                            iri=doc_iri,
                            fallback="class_scan",
                        )
                    self._idempotency_graphql_ok = False
                    self._idempotency_fallback_cache = (
                        await self._build_fallback_idempotency_set(branch)
                    )
                    logger.info("idempotency_path", method="class_scan_fallback")
                    self._idempotency_path_logged = True
                    # Re-check via fallback
                    return doc_iri in (self._idempotency_fallback_cache or set())

                if not self._idempotency_path_logged:
                    logger.info("idempotency_path", method="graphql_point_lookup")
                    self._idempotency_path_logged = True

                return isinstance(entities, list) and len(entities) > 0

            except TdbError as e:
                logger.warning(
                    "idempotency_graphql_failed",
                    iri=doc_iri,
                    fallback="class_scan",
                    error=e.body,
                    status=e.status,
                )
                self._idempotency_graphql_ok = False
                self._idempotency_fallback_cache = (
                    await self._build_fallback_idempotency_set(branch)
                )
                logger.info("idempotency_path", method="class_scan_fallback")
                self._idempotency_path_logged = True

        # Use fallback cache
        return doc_iri in (self._idempotency_fallback_cache or set())

    async def _build_fallback_idempotency_set(self, branch: str) -> set[str]:
        """Fallback: scan all ``produces`` classes, read ``derived_from``."""
        result: set[str] = set()
        for cls_name in self._linkable_classes:
            try:
                docs = await self.tdb.get_documents(cls_name, branch)
            except TdbError:
                continue
            for d in docs:
                derived = d.get("derived_from") or []
                for ref in derived:
                    if ref:
                        result.add(short_iri(ref))
        return result

    # ------------------------------------------------------------------
    # Ensure entity (per-item batch callback)
    # ------------------------------------------------------------------

    def _make_ensure_entity(
        self,
        index: EntityIndex,
        batch: list[dict[str, Any]],
    ) -> Any:
        """Return an async ``ensure_entity`` callable for ``BuildContext``.

        When ``INGESTD_INDEXED_ENABLED`` is true, entity linking consults
        the indexed service on exact-match miss before creating a new entity.
        """
        config = LinkingConfig(
            enabled=self.settings.indexed_enabled,
            url=self.settings.indexed_url,
            token=self.settings.indexed_token,
            min_confidence=self.settings.indexed_min_confidence,
            timeout_seconds=self.settings.indexed_timeout_seconds,
            branch=self.settings.tdb_branch,
        )

        index_ref = index

        async def _ensure_entity(
            type_name: str,
            name: str,
            factory: Any,
        ) -> str | None:
            # 1. Exact index lookup
            iri = match(index_ref, type_name, name)
            if iri:
                return iri

            # 2. Indexed fallback
            if config.enabled and config.url:
                try:
                    iri = await async_match(index_ref, type_name, name, config)
                    if iri:
                        return iri
                except Exception:
                    logger.warning(
                        "ensure_entity_indexed_failed",
                        type_name=type_name,
                        name=name,
                        exc_info=True,
                    )

            # 3. Create via factory
            doc = factory() if callable(factory) else factory
            if doc is None:
                return None

            if "@id" not in doc:
                doc["@id"] = f"{type_name}/{uuid4().hex}"
            batch.append(doc)
            index_ref.register(type_name, name, doc["@id"])
            return doc["@id"]

        return _ensure_entity

    # ------------------------------------------------------------------
    # Process one inbox item
    # ------------------------------------------------------------------

    async def _process_one(
        self,
        doc: dict[str, Any],
        src: Any,
        index: EntityIndex,
        context_block: str,
    ) -> None:
        doc_iri = short_iri(doc.get("@id", ""))
        branch = self.settings.tdb_branch

        # 1. Idempotency guard — per-item GraphQL point lookup with fallback
        if await self._check_idempotency(doc_iri, branch):
            logger.info("already_extracted", iri=doc_iri)
            await self._flip_status(doc, src.done_status)
            return

        # 2. Text + reference datetime from source plugin
        text = src.text(doc)
        reference_dt = src.reference_time(doc)

        # Guard: skip items with empty text (e.g. audio captures not yet transcribed)
        if not text or not text.strip():
            logger.info("empty_text_skipped", iri=doc_iri)
            return

        # 3. Extraction retry loop
        error_feedback: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_llm_retries + 1):
            result = await self._extract(
                self.agent,
                text,
                reference_dt,
                context_block,
                error_feedback,
                extraction_ctx=self._extraction_ctx,
            )

            logger.info(
                "extraction_result",
                iri=doc_iri,
                attempt=attempt,
                reasoning=result.reasoning,
                confidence=result.confidence,
                proposal_count=len(result.proposals),
            )

            if not result.proposals:
                logger.info("nothing_actionable", iri=doc_iri)
                await self._flip_status(doc, src.done_status)
                return

            # Build documents via plugin dispatch — one batch per item
            now = datetime.now(timezone.utc)

            batch, success = await self._build_and_dispatch(
                result.proposals, doc_iri, index, now
            )

            if self.settings.dry_run:
                logger.info(
                    "dry_run_would_insert",
                    iri=doc_iri,
                    documents=batch,
                )
                return

            if not success:
                error_feedback = "One or more build_documents calls failed"
                last_error = RuntimeError(error_feedback)
                logger.warning(
                    "build_documents_failed_some",
                    iri=doc_iri,
                    attempt=attempt,
                )
                continue

            try:
                if batch:
                    inserted = await self.tdb.insert_documents(
                        batch,
                        branch=branch,
                        message=f"ingestd: extracted from {doc_iri}",
                    )
                    logger.info("inserted_documents", iri=doc_iri, count=len(inserted))
                else:
                    logger.info("no_documents_to_insert", iri=doc_iri)
                break  # success → exit retry loop

            except TdbError as e:
                error_feedback = e.body
                last_error = e
                logger.warning(
                    "tdb_insert_error",
                    iri=doc_iri,
                    attempt=attempt,
                    error=error_feedback,
                )
        else:
            # Max retries exhausted
            logger.error(
                "max_retries_exhausted",
                iri=doc_iri,
                last_error=str(last_error) if last_error else "unknown",
            )
            try:
                await self._flip_status(doc, src.failed_status)
            except Exception:
                logger.exception(
                    "failed_to_flip_status_on_retry_exhaustion", iri=doc_iri
                )
            return

        # 4. Flip status to done
        await self._flip_status(doc, src.done_status)

    async def _flip_status(self, doc: dict[str, Any], status: str) -> None:
        """Update *doc* status in-place and persist via replace_document."""
        if self.settings.dry_run:
            logger.info(
                "dry_run_skip_flip",
                iri=short_iri(doc.get("@id", "")),
                status=status,
            )
            return

        now = datetime.now(timezone.utc)
        doc["status"] = status
        doc["updated_at"] = _format_datetime(now)

        await self.tdb.replace_document(
            doc,
            branch=self.settings.tdb_branch,
            message=f"ingestd: status -> {status}",
        )

    # ------------------------------------------------------------------
    # Document building — plugin-aware path
    # ------------------------------------------------------------------

    async def _build_and_dispatch(
        self,
        proposals: list[Any],
        doc_iri: str,
        index: EntityIndex,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Build documents by dispatching each proposal to its owning plugin.

        Returns ``(batch_docs, success)`` — *success* is ``False`` when
        any plugin's ``build_documents`` raises (partial-build detection).
        """
        batch: list[dict[str, Any]] = []
        ensure_entity = self._make_ensure_entity(index, batch)
        success = True

        for prop in proposals:
            kind = getattr(prop, "kind", None)
            if kind is None:
                logger.warning("proposal_missing_kind", iri=doc_iri)
                continue

            plugin = self._extraction_ctx.kind_to_plugin.get(kind)
            if plugin is None:
                logger.warning(
                    "no_plugin_for_kind",
                    kind=kind,
                    iri=doc_iri,
                )
                continue

            ctx = BuildContext(
                tdb=self.tdb,
                captured_iri=doc_iri,
                now=lambda: now,
                ensure_entity=ensure_entity,
                branch=self.settings.tdb_branch,
            )
            try:
                docs = await plugin.build_documents(prop, ctx)
            except Exception:
                logger.error(
                    "build_documents_failed",
                    kind=kind,
                    iri=doc_iri,
                    exc_info=True,
                )
                success = False
                continue

            batch.extend(docs)

        return batch, success
