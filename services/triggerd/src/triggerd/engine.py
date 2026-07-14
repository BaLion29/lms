"""Trigger evaluation engine — evaluates Trigger documents and materializes TriggerFiring records."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from firnline_core.base import _format_datetime
from firnline_core.conventions import agent_id
from firnline_core.plugins import EvalContext
from firnline_core.tdb import StaleCommitError, TdbError, short_iri
from triggerd.evaluators import _parse_iso_datetime, resolve_anchor

logger = structlog.get_logger(__name__)

_UTC = timezone.utc


class Engine:
    """Deterministic trigger evaluation engine.

    Each cycle:
    1. Determines the evaluation window (now - lookback → now).
    2. Enumerates concrete (non-abstract) Trigger subclasses via schema scan.
    3. Fetches Trigger documents, filters by enabled/validity.
    4. Dispatches each trigger to its evaluator plugin.
    5. Resolves a ``subject`` (the Reminder/Routine that references each trigger).
    6. Materializes ``TriggerFiring`` records (idempotent via lexical key).
    """

    def __init__(
        self,
        repo: Any,
        settings: Any,
        evaluators: list[object],
        *,
        now: Any = None,
        logger: Any = None,
    ) -> None:
        self.repo = repo
        self.tdb = repo.tdb
        self.settings = settings
        self.evaluators = evaluators
        self.log = logger or structlog.get_logger(__name__)
        self._now = now if now is not None else self._utc_now

        # trigger_type → evaluator dispatch map
        self._dispatch: dict[str, object] = {}
        for ev in evaluators:
            for ttype in ev.trigger_types:
                self._dispatch[ttype] = ev

        # Per-branch last-seen commit for change-feed polling (persisted)
        self._last_commit: dict[str, str | None] = self._load_state()

        # Per-cycle state
        self._ctx: EvalContext | None = None
        self._raw_schema: list[dict] | None = None  # reused by concrete-types + triggerable-subclasses

        # One-shot warning flag for GraphQL abstract-Triggerable query failure
        self._triggerable_query_warned: bool = False

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # Peristent state (last-seen commit per branch)
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, str | None]:
        """Load persisted ``_last_commit`` map from the state file.

        Tolerates missing / corrupt files → empty dict.
        """
        path = getattr(self.settings, "state_file", "/tmp/triggerd-state.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {k: (v if v is None else str(v)) for k, v in data.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.log.warning("state_file_load_failed", path=path, exc_info=True)
        return {}

    def _save_state(self) -> None:
        """Persist ``_last_commit`` to the state file."""
        path = getattr(self.settings, "state_file", "/tmp/triggerd-state.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_commit, f)
        except OSError:
            self.log.warning("state_file_save_failed", path=path, exc_info=True)

    # ------------------------------------------------------------------
    # EvalContext construction (once per cycle)
    # ------------------------------------------------------------------

    async def _build_ctx(self, branch: str) -> EvalContext:
        """Build an :class:`EvalContext` wired with late-binding closures.

        Closures are defined first so they exist before *ctx* construction.
        The ``_resolve_anchor`` closure references *ctx* which is bound on
        the next line (the name is resolved at call time, not definition time).

        Also polls the change feed via ``changes_since`` for EventTrigger
        evaluators.
        """
        tz = ZoneInfo(self.settings.default_timezone)

        # ── Change feed ──────────────────────────────────────────────
        last_commit = self._last_commit.get(branch)
        try:
            changes, new_head = await self.tdb.changes_since(last_commit, branch)
        except StaleCommitError as exc:
            self.log.warning(
                "cursor_stale_rebaselined",
                branch=branch,
                stale_commit=exc.commit_id,
            )
            changes, new_head = await self.tdb.changes_since(None, branch)
        self._last_commit[branch] = new_head

        # ── Build class → anchor_field map from schema ───────────────
        anchor_map: dict[str, str] = {}
        try:
            raw_schema = await self.tdb.get_schema(branch)
        except Exception:
            raw_schema = []
        self._raw_schema = raw_schema
        for entry in raw_schema:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("@id", "")
            if not isinstance(cid, str) or not cid:
                continue
            meta = entry.get("@metadata")
            if not isinstance(meta, dict):
                continue
            af = meta.get("anchor_field")
            if isinstance(af, str) and af:
                # Store by short name (last segment after / or #)
                short = cid.rstrip("/")
                idx = max(short.rfind("/"), short.rfind("#"))
                short = short[idx + 1:] if idx >= 0 else short
                anchor_map[short] = af

        # Closures defined first so they exist before ctx construction.
        async def _resolve_anchor(anchor_ref: str | dict[str, Any]) -> datetime | None:
            return await resolve_anchor(ctx, anchor_ref, anchor_map)  # noqa: F821 — ctx bound below

        async def _get_occurrences(
            trigger_dict: dict[str, Any],
            window_start: datetime,
            window_end: datetime,
            visited: set[str],
        ) -> list[datetime]:
            return await self._dispatch_occurrences(trigger_dict, window_start, window_end, visited)

        ctx = EvalContext(
            tdb=self.tdb,
            default_tz=tz,
            now=self._now,
            resolve_anchor=_resolve_anchor,
            get_occurrences=_get_occurrences,
            changes=changes,
        )
        # Cache for testability — tests can inspect or pre-set this
        ctx.class_anchor_fields = anchor_map  # type: ignore[attr-defined]
        return ctx

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, should_stop: Any = None) -> None:
        """Run one full evaluation cycle (see class docstring)."""
        if should_stop is not None and getattr(should_stop, "is_set", lambda: False)():
            return

        branch = self.settings.tdb_branch
        self._ctx = await self._build_ctx(branch)

        window_end = self._now()
        window_start = window_end - timedelta(seconds=self.settings.lookback_seconds)

        # ── Enumerate concrete trigger classes ──────────────────────────
        # Full-scan polling via get_documents is acceptable at personal scale;
        # same known ceiling as get_documents_by_status.
        concrete_types = await self._get_concrete_trigger_types(branch)

        # ── Fetch and evaluate ──────────────────────────────────────────
        all_trigger_docs: list[dict[str, Any]] = []
        for cls_name in concrete_types:
            try:
                docs = await self.tdb.get_documents(cls_name, branch=branch)
            except Exception:
                self.log.warning("trigger_fetch_failed", class_name=cls_name, exc_info=True)
                continue
            all_trigger_docs.extend(docs)

        triggers_scanned = len(all_trigger_docs)

        skipped_by_type: dict[str, int] = {}
        logged_unsupported: set[str] = set()
        firings_to_write: list[dict[str, Any]] = []
        dispatched_count = 0
        evaluated_count = 0
        errors_count = 0

        for doc in all_trigger_docs:
            ttype = doc.get("@type")
            if not ttype:
                continue

            evaluator = self._dispatch.get(ttype)
            if evaluator is None:
                skipped_by_type[ttype] = skipped_by_type.get(ttype, 0) + 1
                if ttype not in logged_unsupported:
                    logged_unsupported.add(ttype)
                    self.log.warning("trigger_type_unsupported", type=ttype)
                continue

            # Active filter
            if not self._is_trigger_active(doc, window_end):
                continue

            dispatched_count += 1

            # Evaluate
            try:
                instants = await evaluator.occurrences(
                    doc,
                    window_start=window_start,
                    window_end=window_end,
                    ctx=self._ctx,
                )
            except Exception:
                self.log.warning("evaluator_error", trigger=doc.get("@id"), exc_info=True)
                errors_count += 1
                continue

            evaluated_count += 1

            for instant in instants:
                firings_to_write.append({"trigger_doc": doc, "scheduled_instant": instant})

        # ── Resolve subjects (per trigger IRI) ─────────────────────────
        # Collect unique trigger IRIs that have at least one firing
        trigger_iris: set[str] = set()
        for entry in firings_to_write:
            trigger_iris.add(entry["trigger_doc"]["@id"])

        # Resolve subject per trigger IRI (cache per cycle)
        subjects: dict[str, str | None] = {}
        for iri in trigger_iris:
            subjects[iri] = await self._resolve_subject(iri, branch)

        # ── Build and insert firings ────────────────────────────────────
        firings_written = 0
        duplicates_suppressed = 0
        subjects_resolved = 0

        # Group by trigger @id for batch insert
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in firings_to_write:
            trigger_iri = entry["trigger_doc"]["@id"]
            trigger_type = entry["trigger_doc"].get("@type", "")
            scheduled = entry["scheduled_instant"]

            # For event triggers, use commit-stable keys from the evaluator,
            # keyed by trigger @id so multiple EventTriggers in the same
            # cycle do not interfere with each other.
            evaluator = self._dispatch.get(trigger_type)
            event_keys: dict | None = getattr(evaluator, "_event_keys", None)
            if event_keys is not None:
                # Pop one key per firing (FIFO per instant bucket) for this trigger
                bucket = event_keys.get(trigger_iri, {}).get(scheduled, [])
                occurrence_key = bucket.pop(0) if bucket else _format_datetime(scheduled)
            else:
                occurrence_key = _format_datetime(scheduled)

            subject = subjects.get(trigger_iri)
            if subject is not None:
                subjects_resolved += 1

            now_val = self._now()
            firing_doc: dict[str, Any] = {
                "@type": "TriggerFiring",
                "trigger": trigger_iri,
                "occurrence_key": occurrence_key,
                "scheduled_for": _format_datetime(scheduled),
                "fired_at": _format_datetime(window_end),
                "status": "pending",
            }
            if subject is not None:
                firing_doc["subject"] = subject
            grouped.setdefault(trigger_iri, []).append(firing_doc)

        for trigger_iri, firings in grouped.items():
            short = short_iri(trigger_iri)
            n = len(firings)
            _agent = agent_id("service", "triggerd")

            for fdoc in firings:
                key = fdoc["occurrence_key"]
                if self.settings.dry_run:
                    self.log.info("firing_dry_run", trigger=trigger_iri, occurrence_key=key)
                    continue

                try:
                    await self.repo.create(
                        fdoc,
                        agent=_agent,
                        method="evaluation",
                        branch=branch,
                    )
                except TdbError as exc:
                    if "DocumentIdAlreadyExists" in str(exc.body):
                        duplicates_suppressed += 1
                        self.log.debug(
                            "firing_duplicate",
                            trigger=trigger_iri,
                            occurrence_key=key,
                            status=exc.status,
                        )
                    else:
                        self.log.warning(
                            "firing_insert_failed",
                            trigger=trigger_iri,
                            occurrence_key=key,
                            status=exc.status,
                            body=str(exc.body)[:500],
                        )
                except Exception:
                    self.log.warning(
                        "firing_insert_failed",
                        trigger=trigger_iri,
                        occurrence_key=key,
                        exc_info=True,
                    )
                else:
                    firings_written += 1

        # ── Cycle summary ──────────────────────────────────────────────
        self.log.info(
            "cycle_complete",
            triggers_scanned=triggers_scanned,
            triggers_dispatched=dispatched_count,
            evaluated=evaluated_count,
            skipped_by_type=skipped_by_type,
            firings_written=firings_written,
            duplicates_suppressed=duplicates_suppressed,
            subjects_resolved=subjects_resolved,
            errors=errors_count,
        )

        # Persist last-seen commits so restarts don't re-baseline.
        self._save_state()

    # ------------------------------------------------------------------
    # Dispatch for CompositeTrigger operand recursion
    # ------------------------------------------------------------------

    async def _dispatch_occurrences(
        self,
        trigger_dict: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
        visited: set[str],
    ) -> list[datetime]:
        """Dispatch a trigger dict through the evaluator map.

        Used by :class:`CompositeEvaluator` via ``ctx.get_occurrences``.
        Operands also pass through the ``_is_active`` filter — a disabled
        or out-of-validity operand yields zero occurrences.
        """
        ttype = trigger_dict.get("@type")
        evaluator = self._dispatch.get(ttype)
        if evaluator is None:
            return []

        if not self._is_trigger_active(trigger_dict, window_end):
            return []

        try:
            assert self._ctx is not None
            return await evaluator.occurrences(
                trigger_dict,
                window_start=window_start,
                window_end=window_end,
                ctx=self._ctx,
            )
        except Exception:
            self.log.warning(
                "evaluator_error",
                trigger=trigger_dict.get("@id"),
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # Schema scan — concrete Trigger subclasses
    # ------------------------------------------------------------------

    async def _get_concrete_trigger_types(self, branch: str) -> set[str]:
        """Return the set of concrete (non-abstract) Trigger subclass names.

        Uses the schema fetched by ``_build_ctx`` (one round-trip per cycle).
        Falls back to a direct ``get_schema`` call when called outside a cycle
        (e.g. from tests).
        """
        raw_schema = self._raw_schema
        if raw_schema is None:
            try:
                raw_schema = await self.tdb.get_schema(branch)
            except Exception:
                self.log.warning("schema_fetch_failed", branch=branch, exc_info=True)
                return set()

        # Build lookup: class @id → definition dict
        classes: dict[str, dict[str, Any]] = {}
        for entry in raw_schema:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("@id")
            if isinstance(cid, str) and entry.get("@type") == "Class":
                classes[cid] = entry

        def inherits_from_trigger(cls_id: str, chain: set[str] | None = None) -> bool:
            if chain is None:
                chain = set()
            if cls_id in chain:
                return False
            chain.add(cls_id)
            if cls_id == "Trigger":
                return True
            cls_def = classes.get(cls_id)
            if cls_def is None:
                return False
            inherits = cls_def.get("@inherits")
            if isinstance(inherits, str):
                return inherits_from_trigger(inherits, chain)
            if isinstance(inherits, list):
                return any(inherits_from_trigger(p, chain) for p in inherits)
            return False

        concrete: set[str] = set()
        for cid, cls_def in classes.items():
            if cls_def.get("@abstract"):
                continue
            if inherits_from_trigger(cid):
                concrete.add(cid)

        return concrete

    # ------------------------------------------------------------------
    # Active filter
    # ------------------------------------------------------------------

    @staticmethod
    def _is_trigger_active(trigger_doc: dict[str, Any], window_end: datetime) -> bool:
        """Return True if the trigger is enabled and within its validity window."""
        if trigger_doc.get("enabled") is False:
            return False

        valid_from_raw = trigger_doc.get("valid_from")
        if valid_from_raw is not None:
            valid_from = _parse_iso_datetime(valid_from_raw)
            if valid_from > window_end:
                return False

        valid_until_raw = trigger_doc.get("valid_until")
        if valid_until_raw is not None:
            valid_until = _parse_iso_datetime(valid_until_raw)
            if valid_until < window_end:
                return False

        return True

    # ------------------------------------------------------------------
    # Subject resolution
    # ------------------------------------------------------------------

    async def _resolve_subject(self, trigger_iri: str, branch: str) -> str | None:
        """Find the single Triggerable that references *trigger_iri*.

        First tries a GraphQL query over the abstract ``Triggerable`` marker.
        On error, falls back to querying each concrete Triggerable subclass
        individually (derived from the live schema).

        Exactly-one → its ``_id``; zero/many → None (logged).
        """
        query = "query($iri: String) { Triggerable(filter: { trigger: { eq: $iri } }) { _id } }"
        try:
            result = await self.tdb.graphql(query, variables={"iri": trigger_iri}, branch=branch)
        except TdbError as exc:
            return await self._resolve_subject_fallback(trigger_iri, branch, exc)
        except Exception:
            self.log.debug("subject_query_failed", trigger=trigger_iri, exc_info=True)
            return None

        items = result.get("Triggerable", [])
        return self._deduce_subject(items, trigger_iri)

    async def _resolve_subject_fallback(
        self, trigger_iri: str, branch: str, original_exc: TdbError
    ) -> str | None:
        """Fallback: query each concrete Triggerable subclass individually."""
        if not self._triggerable_query_warned:
            self._triggerable_query_warned = True
            self.log.warning(
                "triggerable_abstract_query_failed",
                body=str(original_exc.body)[:300],
                hint="Falling back to per-subclass queries",
            )

        subclass_names = await self._get_triggerable_subclasses(branch)
        if not subclass_names:
            self.log.debug("subject_fallback_no_subclasses", trigger=trigger_iri)
            return None

        all_items: list[dict[str, Any]] = []
        for cls_name in subclass_names:
            query = f"query($iri: String) {{ {cls_name}(filter: {{ trigger: {{ eq: $iri }} }}) {{ _id }} }}"
            try:
                result = await self.tdb.graphql(query, variables={"iri": trigger_iri}, branch=branch)
            except (TdbError, Exception):
                self.log.debug(
                    "subject_fallback_subclass_failed",
                    trigger=trigger_iri,
                    subclass=cls_name,
                )
                continue
            items = result.get(cls_name, [])
            all_items.extend(items)

        return self._deduce_subject(all_items, trigger_iri)

    @staticmethod
    def _deduce_subject(items: list[dict[str, Any]], trigger_iri: str) -> str | None:
        """Apply exactly-one rule across a list of result dicts."""
        referrer_ids: list[str] = [item["_id"] for item in items if isinstance(item.get("_id"), str)]

        if len(referrer_ids) == 1:
            return referrer_ids[0]
        if len(referrer_ids) > 1:
            logger.warning(
                "subject_ambiguous",
                trigger=trigger_iri,
                count=len(referrer_ids),
            )
            return None
        return None

    async def _get_triggerable_subclasses(self, branch: str) -> list[str]:
        """Return concrete (non-abstract) Triggerable subclass names from schema.

        Uses the schema fetched by ``_build_ctx`` (one round-trip per cycle).
        Falls back to a direct ``get_schema`` call when called outside a cycle.
        """
        raw_schema = self._raw_schema
        if raw_schema is None:
            try:
                raw_schema = await self.tdb.get_schema(branch)
            except Exception:
                self.log.debug("triggerable_schema_fetch_failed", branch=branch)
                return []

        classes: dict[str, dict[str, Any]] = {}
        for entry in raw_schema:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("@id")
            if isinstance(cid, str) and entry.get("@type") == "Class":
                classes[cid] = entry

        def inherits_from_triggerable(cls_id: str, chain: set[str] | None = None) -> bool:
            if chain is None:
                chain = set()
            if cls_id in chain:
                return False
            chain.add(cls_id)
            if cls_id == "Triggerable":
                return True
            cls_def = classes.get(cls_id)
            if cls_def is None:
                return False
            inherits = cls_def.get("@inherits")
            if isinstance(inherits, str):
                return inherits_from_triggerable(inherits, chain)
            if isinstance(inherits, list):
                return any(inherits_from_triggerable(p, chain) for p in inherits)
            return False

        concrete: list[str] = []
        for cid, cls_def in classes.items():
            if cls_def.get("@abstract"):
                continue
            if inherits_from_triggerable(cid):
                concrete.append(cid)

        return concrete
