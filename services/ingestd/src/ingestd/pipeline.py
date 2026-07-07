"""Extraction pipeline — processes inbox documents through LLM extraction → TDB insertion.

Generic: polls source plugins, runs extraction via the ExtractionContext (built
at startup from ExtractorPlugins), and dispatches document building per proposal
kind.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel

from ingestd.extraction import ExtractionContext, ExtractionResult, extract
from ingestd.linking import (
    EntityIndex,
    LinkingConfig,
    async_match_location,
    async_match_person,
    build_index,
)
from ingestd.settings import Settings
from firnline_core.models import (
    Contact,
    Event,
    EventStatus,
    Location,
    Person,
    Reminder,
    Task,
    TaskStatus,
    _format_datetime,
)
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

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: asyncio.Event | None = None) -> None:
        """Execute one full extraction cycle.

        1. Fetch entity context (Person + Location) and build index.
        2. Build linking context block from all extractor plugins.
        3. Gather inbox documents from each source plugin (generic poll).
        4. Pre-fetch Task/Event/Reminder lists for idempotency.
        5. Process each inbox doc sequentially, respecting *should_stop*.
        """
        branch = self.settings.tdb_branch

        # ----- Entity index -----
        people = await self.tdb.get_documents("Person", branch)
        locations = await self.tdb.get_documents("Location", branch)
        index = build_index(people, locations)

        # ----- Linking context -----
        context_block = await self._build_linking_context(index)

        # ----- Idempotency set -----
        already_derived: set[str] = set()
        for type_ in ("Task", "Event", "Reminder"):
            docs = await self.tdb.get_documents(type_, branch)
            for d in docs:
                df = d.get("derived_from")
                if df:
                    already_derived.add(short_iri(df))

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
                await self._process_one(doc, src, index, context_block, already_derived)
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
                lc = await plugin.linking_context(self.tdb, index=index, branch=self.settings.tdb_branch)
                if lc and lc.strip():
                    parts.append(lc)
            except Exception:
                logger.warning(
                    "linking_context_failed",
                    plugin=plugin.name,
                    exc_info=True,
                )

        return "\n\n".join(parts)

    def _make_create_or_link(self, index: EntityIndex) -> Any:
        """Return an async ``create_or_link`` callable for ``BuildContext``.

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

        async def _create_or_link(
            type_name: str,
            name: str,
            factory: Any,
        ) -> str | None:
            if type_name == "Person":
                iri = await async_match_person(index, name, config)
            elif type_name == "Location":
                iri = await async_match_location(index, name, config)
            else:
                iri = None

            if iri:
                return iri

            doc = factory() if callable(factory) else factory
            if doc is None:
                return None

            iris = await self.tdb.insert_documents(
                [doc],
                branch=self.settings.tdb_branch,
                message=f"ingestd: created {type_name} '{name}'",
            )
            new_iri = short_iri(iris[0])

            key = name.casefold()
            if type_name == "Person":
                index.people[key] = new_iri
                index.people_display.append((name, new_iri))
            elif type_name == "Location":
                index.locations[key] = new_iri
                index.locations_display.append((name, new_iri))

            return new_iri

        return _create_or_link

    async def _process_one(
        self,
        doc: dict[str, Any],
        src: Any,
        index: EntityIndex,
        context_block: str,
        already_derived: set[str],
    ) -> None:
        doc_iri = short_iri(doc.get("@id", ""))
        branch = self.settings.tdb_branch

        # 1. Idempotency guard
        if doc_iri in already_derived:
            logger.info("already_extracted", iri=doc_iri)
            await self._flip_status(doc, src.done_status)
            return

        # 2. Text + reference datetime from source plugin
        text = src.text(doc)
        reference_dt = src.reference_time(doc)

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

            # Build documents via plugin dispatch
            now = datetime.now(timezone.utc)

            all_docs, new_locations, pending_loc_events = await self._build_documents_via_plugins(
                result.proposals, doc_iri, index, now
            )

            if self.settings.dry_run:
                loc_docs = [loc.to_tdb() for loc in new_locations]
                logger.info(
                    "dry_run_would_insert",
                    iri=doc_iri,
                    documents=loc_docs + all_docs,
                )
                return

            try:
                # Insert new locations first
                if new_locations:
                    loc_docs = [loc.to_tdb() for loc in new_locations]
                    loc_ids = await self.tdb.insert_documents(
                        loc_docs,
                        branch=branch,
                        message=f"ingestd: extracted from {doc_iri}",
                    )
                    for loc, full_id in zip(new_locations, loc_ids):
                        short_id = short_iri(full_id)
                        index.locations[loc.name.casefold()] = short_id
                        for event_doc, loc_name in pending_loc_events:
                            if loc_name.casefold() == loc.name.casefold():
                                event_doc["location"] = short_id

                # Insert main documents
                inserted = await self.tdb.insert_documents(
                    all_docs,
                    branch=branch,
                    message=f"ingestd: extracted from {doc_iri}",
                )
                logger.info("inserted_documents", iri=doc_iri, inserted=inserted)
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
                logger.exception("failed_to_flip_status_on_retry_exhaustion", iri=doc_iri)
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

    async def _build_documents_via_plugins(
        self,
        proposals: list[Any],
        doc_iri: str,
        index: EntityIndex,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], list[Location], list[tuple[dict[str, Any], str]]]:
        """Build documents by dispatching each proposal to its owning plugin."""
        create_or_link = self._make_create_or_link(index)
        all_docs: list[dict[str, Any]] = []
        new_locations: list[Location] = []
        new_location_names: set[str] = set()
        pending_loc_events: list[tuple[dict[str, Any], str]] = []

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
                inbox_iri=doc_iri,
                now=lambda: now,
                create_or_link=create_or_link,
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
                continue

            # Track new locations for events
            if kind == "event" and hasattr(prop, "location_name") and prop.location_name:
                for d in docs:
                    if d.get("@type") == "Event" and not d.get("location"):
                        name_cf = prop.location_name.casefold()
                        if name_cf not in new_location_names:
                            new_location_names.add(name_cf)
                            new_locations.append(Location(name=prop.location_name))
                        pending_loc_events.append((d, prop.location_name))

            all_docs.extend(docs)

        return all_docs, new_locations, pending_loc_events
