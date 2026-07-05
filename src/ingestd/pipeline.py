"""Extraction pipeline — processes inbox documents through LLM extraction → TDB insertion."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from ingestd.extraction import (
    EventProposal,
    PersonProposal,
    ReminderProposal,
    TaskProposal,
    extract,
)
from ingestd.linking import (
    EntityIndex,
    build_context_block,
    build_index,
    match_location,
    match_person,
)
from ingestd.models import (
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
from ingestd.settings import Settings
from ingestd.tdb import TdbClient, TdbError, short_iri

logger = structlog.get_logger(__name__)


def _parse_reference_datetime(dt_str: str, field_name: str, doc_iri: str) -> datetime:
    """Parse a reference datetime string, falling back to now(UTC) with a warning."""
    if not dt_str:
        logger.warning(
            "reference_datetime_missing",
            iri=doc_iri,
            field=field_name,
        )
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning(
            "reference_datetime_unparseable",
            iri=doc_iri,
            field=field_name,
            value=dt_str,
        )
        return datetime.now(timezone.utc)


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
        extract_fn: Any = None,
    ) -> None:
        self.tdb = tdb
        self.agent = agent
        self.settings = settings
        self._extract = extract_fn or extract

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: asyncio.Event | None = None) -> None:
        """Execute one full extraction cycle.

        1. Fetch entity context (Person + Location) and build index.
        2. Gather inbox documents (InboxNote status="new", InboxAudio
           status="transcribed").
        3. Pre-fetch Task/Event/Reminder lists for idempotency.
        4. Process each inbox doc sequentially, respecting *should_stop*.
        """
        branch = self.settings.tdb_branch

        # ----- Entity context -----
        people = await self.tdb.get_documents("Person", branch)
        locations = await self.tdb.get_documents("Location", branch)
        index = build_index(people, locations)
        context_block = build_context_block(index)

        # ----- Idempotency set -----
        already_derived: set[str] = set()
        for type_ in ("Task", "Event", "Reminder"):
            docs = await self.tdb.get_documents(type_, branch)
            for d in docs:
                df = d.get("derived_from")
                if df:
                    already_derived.add(short_iri(df))

        # ----- Gather work -----
        notes = await self.tdb.get_documents_by_status("InboxNote", "new", branch)
        audios = await self.tdb.get_documents_by_status(
            "InboxAudio", "transcribed", branch
        )
        all_inbox: list[dict[str, Any]] = list(notes) + list(audios)

        if not all_inbox:
            logger.info("cycle_complete", inbox_count=0)
            return

        # ----- Process sequentially -----
        for doc in all_inbox:
            if should_stop and should_stop.is_set():
                logger.info("shutdown_requested", remaining=len(all_inbox))
                break

            doc_iri = short_iri(doc.get("@id", ""))
            logger.info("processing_inbox_doc", iri=doc_iri)

            try:
                await self._process_one(doc, index, context_block, already_derived)
            except Exception:
                logger.error(
                    "unexpected_error",
                    iri=doc_iri,
                    exc_info=True,
                )
                try:
                    await self._flip_status(doc, "failed")
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

    async def _process_one(
        self,
        doc: dict[str, Any],
        index: EntityIndex,
        context_block: str,
        already_derived: set[str],
    ) -> None:
        doc_iri = short_iri(doc.get("@id", ""))
        doc_type = doc.get("@type", "")
        branch = self.settings.tdb_branch

        # 1. Idempotency guard
        if doc_iri in already_derived:
            logger.info("already_extracted", iri=doc_iri)
            await self._flip_status(doc, "processed")
            return

        # 2. Text + reference datetime
        if doc_type == "InboxNote":
            text = doc["content"]
            ref_dt_str = doc.get("created_at", "")
            ref_dt_field = "created_at"
        elif doc_type == "InboxAudio":
            text = doc["transcription"]
            ref_dt_str = doc.get("recorded_at", "")
            ref_dt_field = "recorded_at"
        else:
            raise ValueError(f"Unknown inbox type: {doc_type}")

        reference_dt = _parse_reference_datetime(ref_dt_str, ref_dt_field, doc_iri)

        # 3. Extraction retry loop
        error_feedback: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_llm_retries + 1):
            result = await self._extract(
                self.agent, text, reference_dt, context_block, error_feedback
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
                await self._flip_status(doc, "processed")
                return

            # Build documents
            now = datetime.now(timezone.utc)
            main_docs, new_locations, pending_loc_events = self._build_documents(
                result.proposals, doc_iri, index, now
            )

            if self.settings.dry_run:
                all_docs = [loc.to_tdb() for loc in new_locations] + [
                    md for md in main_docs
                ]
                logger.info(
                    "dry_run_would_insert",
                    iri=doc_iri,
                    documents=all_docs,
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
                    # Map inserted IRIs back to events
                    for loc, full_id in zip(new_locations, loc_ids):
                        short_id = short_iri(full_id)
                        index.locations[loc.name.casefold()] = short_id
                        # NOTE: On retry after a successful location insert but
                        # failed main insert, the LLM may rephrase the location
                        # name, creating a duplicate Location.  The re-check
                        # against the updated index mitigates exact-match
                        # duplicates but cannot detect semantic near-duplicates.
                        for event_doc, loc_name in pending_loc_events:
                            if loc_name.casefold() == loc.name.casefold():
                                event_doc["location"] = short_id

                # Insert main documents
                inserted = await self.tdb.insert_documents(
                    main_docs,
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
                await self._flip_status(doc, "failed")
            except Exception:
                logger.exception(
                    "failed_to_flip_status_on_retry_exhaustion", iri=doc_iri
                )
            return

        # 4. Flip status to processed
        await self._flip_status(doc, "processed")

    def _build_documents(
        self,
        proposals: list[Any],
        inbox_iri_short: str,
        index: EntityIndex,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], list[Location], list[tuple[dict[str, Any], str]]]:
        """Convert proposals to TerminusDB document dicts.

        Returns (main_docs, new_locations, pending_loc_events) where
        *pending_loc_events* maps event doc dicts to the name of a
        newly-created Location that still needs an IRI assigned.
        """
        main_docs: list[dict[str, Any]] = []
        new_locations: list[Location] = []
        pending_loc_events: list[tuple[dict[str, Any], str]] = []
        new_location_names: set[str] = set()

        for prop in proposals:
            if isinstance(prop, TaskProposal):
                main_docs.append(
                    Task(
                        name=prop.name,
                        description=prop.description,
                        priority=prop.priority,
                        estimated_duration=prop.estimated_duration,
                        due_date=prop.due_date,
                        status=TaskStatus.OPEN,
                        derived_from=inbox_iri_short,
                        created_at=now,
                        updated_at=now,
                    ).to_tdb()
                )

            elif isinstance(prop, EventProposal):
                event_doc: dict[str, Any] = Event(
                    name=prop.name,
                    description=prop.description,
                    start_datetime=prop.start_datetime,
                    end_datetime=prop.end_datetime,
                    location=None,
                    status=EventStatus.OPEN,
                    derived_from=inbox_iri_short,
                    created_at=now,
                    updated_at=now,
                ).to_tdb()

                if prop.location_name:
                    loc_match = match_location(index, prop.location_name)
                    if loc_match:
                        event_doc["location"] = loc_match
                    else:
                        # New location — track for insertion
                        name_cf = prop.location_name.casefold()
                        if name_cf not in new_location_names:
                            new_location_names.add(name_cf)
                            new_locations.append(Location(name=prop.location_name))
                        pending_loc_events.append((event_doc, prop.location_name))

                main_docs.append(event_doc)

            elif isinstance(prop, ReminderProposal):
                main_docs.append(
                    Reminder(
                        name=prop.name,
                        description=prop.description,
                        refers_to=None,
                        trigger=None,
                        derived_from=inbox_iri_short,
                        created_at=now,
                        updated_at=now,
                    ).to_tdb()
                )

            elif isinstance(prop, PersonProposal):
                match_iri = match_person(index, prop.name)
                if match_iri:
                    logger.info(
                        "person_linked",
                        name=prop.name,
                        iri=match_iri,
                    )
                    continue  # drop — person already exists

                contact = None
                if prop.email or prop.phone:
                    contact = Contact(email=prop.email, phone=prop.phone)
                main_docs.append(Person(name=prop.name, contact=contact).to_tdb())

        return main_docs, new_locations, pending_loc_events

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
