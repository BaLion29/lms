"""First-party trigger evaluators.

Each evaluator handles one trigger ``@type`` and returns UTC fire instants
for a half-open window ``(window_start, window_end]``.

All datetime values returned from TDB are parsed as ISO-8601 strings.
Naive datetimes are treated as UTC (TDB convention).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from dateutil.rrule import rrulestr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from firnline_core.plugins import EvalContext, ModuleRequirement, TriggerEvaluator

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRIGGER_MODULE_REQ = ModuleRequirement(name="triggers", range=">=0.1.0 <0.2.0")

_DURATION_RE = re.compile(
    r"^(?P<sign>-?)P"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
    r"$"
)


def _parse_iso_datetime(raw: str) -> datetime:
    """Parse an ISO-8601 datetime string to a tz-aware UTC datetime.

    Naive values are treated as UTC.
    Handles Z suffix, ±HH:MM offsets, and sub-second precision."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_duration(raw: str) -> timedelta | None:
    """Parse an ISO-8601 duration string into a ``timedelta``.

    Supported subset: optional leading ``-``, ``P[nD][T[nH][nM][nS]]``.
    Also accepts ``PT...``-only durations.  Returns ``None`` on malformed input.
    """
    m = _DURATION_RE.match(raw)
    if not m:
        return None

    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)

    # Require at least one component (reject bare "P" or trailing "T")
    if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
        return None
    if raw.rstrip().endswith("T"):
        return None

    td = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if m.group("sign") == "-":
        td = -td
    return td


# ---------------------------------------------------------------------------
# Anchor resolver (exported for unit-testing; wired by the engine)
# ---------------------------------------------------------------------------


def _class_short_name(type_or_id: str) -> str:
    """Return the final segment of a class IRI/type string.

    ``"terminusdb:///schema#Reminder"`` → ``"Reminder"``
    ``"Reminder"`` → ``"Reminder"``
    """
    s = type_or_id.rstrip("/")
    idx = max(s.rfind("/"), s.rfind("#"))
    if idx >= 0:
        return s[idx + 1:]
    return s


async def resolve_anchor(
    ctx: EvalContext,
    anchor_ref: str | dict[str, Any],
    class_anchor_fields: dict[str, str] | None = None,
) -> datetime | None:
    """Resolve an Anchored document/IRI via its class's ``@metadata.anchor_field``.

    Looks up the document's ``@type`` in *class_anchor_fields* to find
    the correct datetime field name.  Returns the anchor datetime
    (tz-aware UTC) or ``None`` when:

    * The class has no ``anchor_field`` metadata
    * The field is missing from the document
    * The value is ``None`` or malformed

    *class_anchor_fields* maps short class names to field names.
    When ``None`` (tests that don't supply it), every lookup is treated
    as "no anchor_field" → ``None``.  The engine always supplies it.
    """
    if isinstance(anchor_ref, dict):
        doc = anchor_ref
    else:
        doc = await ctx.tdb.get_document(anchor_ref)

    doc_type = doc.get("@type", "")
    short_type = _class_short_name(doc_type) if isinstance(doc_type, str) and doc_type else ""

    if class_anchor_fields is None or short_type not in class_anchor_fields:
        logger.info(
            "trigger_dormant",
            iri=doc.get("@id"),
            type=doc_type,
            reason="no anchor_field",
        )
        return None

    field = class_anchor_fields[short_type]
    value = doc.get(field)
    if value is None:
        logger.info(
            "trigger_dormant",
            iri=doc.get("@id"),
            type=doc_type,
            field=field,
            reason="anchor unset",
        )
        return None

    try:
        return _parse_iso_datetime(value)
    except (ValueError, TypeError):
        logger.debug("anchor_parse_failed", iri=doc.get("@id"), field=field, value=value)
        return None


# ---------------------------------------------------------------------------
# OneShotEvaluator
# ---------------------------------------------------------------------------


class OneShotEvaluator:
    """Evaluates ``OneShotTrigger`` — fires exactly once at ``fire_at``."""

    name: str = "oneshot"
    requires: list[ModuleRequirement] = [_TRIGGER_MODULE_REQ]
    trigger_types: tuple[str, ...] = ("OneShotTrigger",)

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        fire_at = _parse_iso_datetime(trigger["fire_at"])
        if window_start < fire_at <= window_end:
            return [fire_at]
        return []


# ---------------------------------------------------------------------------
# ScheduleEvaluator
# ---------------------------------------------------------------------------


class ScheduleEvaluator:
    """Evaluates ``ScheduleTrigger`` — recurring instants via ``rrule``.

    DST-aware: each occurrence carries the local timezone info and is
    converted to UTC, so a ``07:00 Europe/Zurich`` daily rule fires at
    ``05:00Z`` in summer and ``06:00Z`` in winter.
    """

    name: str = "schedule"
    requires: list[ModuleRequirement] = [_TRIGGER_MODULE_REQ]
    trigger_types: tuple[str, ...] = ("ScheduleTrigger",)

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        # -- Resolve timezone ------------------------------------------------
        tz_name = trigger.get("timezone") or None
        if tz_name is not None:
            try:
                tz = ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, KeyError, TypeError):
                logger.warning("schedule_timezone_invalid", timezone=tz_name, falling_back=str(ctx.default_tz))
                tz = ctx.default_tz
        else:
            tz = ctx.default_tz

        # -- Parse dtstart in target tz -------------------------------------
        dtstart_utc = _parse_iso_datetime(trigger["dtstart"])
        local_dtstart = dtstart_utc.astimezone(tz)

        # -- Build rrule ----------------------------------------------------
        rrule_str: str = trigger["rrule"]
        try:
            rule = rrulestr(rrule_str, dtstart=local_dtstart)
        except Exception:
            logger.warning("schedule_rrule_invalid", rrule=rrule_str, trigger=trigger.get("@id"))
            return []

        # -- Expand window in local tz --------------------------------------
        local_start = window_start.astimezone(tz)
        local_end = window_end.astimezone(tz)

        try:
            candidates = rule.between(local_start, local_end, inc=True)
        except Exception:
            logger.warning("schedule_between_failed", rrule=rrule_str, trigger=trigger.get("@id"))
            return []

        # Filter out exact window_start (half-open) and convert to UTC
        results: list[datetime] = []
        for dt in candidates:
            if dt == local_start:
                continue
            results.append(dt.astimezone(timezone.utc))

        return results


# ---------------------------------------------------------------------------
# RelativeEvaluator
# ---------------------------------------------------------------------------


class RelativeEvaluator:
    """Evaluates ``RelativeTrigger`` — a duration offset relative to an anchor doc."""

    name: str = "relative"
    requires: list[ModuleRequirement] = [_TRIGGER_MODULE_REQ]
    trigger_types: tuple[str, ...] = ("RelativeTrigger",)

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        anchor_ref: str = trigger["anchor"]
        offset_raw: str = trigger["offset"]

        # Resolve anchor
        anchor_instant = await ctx.resolve_anchor(anchor_ref)
        if anchor_instant is None:
            return []

        # Parse offset
        offset = _parse_duration(offset_raw)
        if offset is None:
            logger.warning("relative_offset_invalid", offset=offset_raw, trigger=trigger.get("@id"))
            return []

        # Compute fire instant
        fire_at = anchor_instant + offset

        # Half-open interval check
        if window_start < fire_at <= window_end:
            return [fire_at]
        return []


# ---------------------------------------------------------------------------
# CompositeEvaluator
# ---------------------------------------------------------------------------


class CompositeEvaluator:
    """Evaluates ``CompositeTrigger`` — ``any`` or ``all`` combination of operand triggers.

    ``any``: union of all operand occurrence instants, deduplicated and sorted.
    ``all``: coincidence — an instant qualifies when every operand has ≥1
    occurrence within ``[t, t+window]`` where *t* iterates over the first
    operand's occurrences.  ``window`` is required for ``all``; missing
    → log warning, no occurrences.  Cycle detection uses a ``visited`` set
    of trigger IRIs.
    """

    name: str = "composite"
    requires: list[ModuleRequirement] = [_TRIGGER_MODULE_REQ]
    trigger_types: tuple[str, ...] = ("CompositeTrigger",)

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        mode: str = trigger.get("mode", "any")

        if mode not in ("any", "all"):
            logger.warning("composite_mode_unsupported", mode=mode, trigger=trigger.get("@id"))
            return []

        visited: set[str] = set()
        if mode == "any":
            return await self._eval_any(trigger, window_start, window_end, ctx, visited)
        else:
            return await self._eval_all(trigger, window_start, window_end, ctx, visited)

    async def _eval_any(
        self,
        trigger: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
        visited: set[str],
    ) -> list[datetime]:
        self_iri: str | None = trigger.get("@id")
        if self_iri:
            if self_iri in visited:
                logger.warning("composite_cycle_detected", iri=self_iri, trigger=self_iri)
                return []
            visited.add(self_iri)

        operands: list[str] = trigger.get("operands", [])
        all_fires: set[datetime] = set()

        for op_iri in operands:
            if op_iri in visited:
                logger.warning("composite_cycle_detected", iri=op_iri, parent=self_iri)
                continue

            try:
                op_doc = await ctx.tdb.get_document(op_iri)
            except Exception:
                logger.warning("composite_operand_fetch_failed", iri=op_iri, parent=self_iri)
                continue

            try:
                fires = await ctx.get_occurrences(op_doc, window_start, window_end, visited.copy())
            except Exception:
                logger.warning("composite_operand_eval_failed", iri=op_iri, parent=self_iri)
                continue

            all_fires.update(fires)

        return sorted(all_fires)

    async def _eval_all(
        self,
        trigger: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
        visited: set[str],
    ) -> list[datetime]:
        """Coincidence: t qualifies if every operand has ≥1 occurrence in [t, t+window]."""
        self_iri: str | None = trigger.get("@id")
        if self_iri:
            if self_iri in visited:
                logger.warning("composite_cycle_detected", iri=self_iri, trigger=self_iri)
                return []
            visited.add(self_iri)

        window_raw: str | None = trigger.get("window")
        if window_raw is None:
            logger.warning("composite_all_missing_window", trigger=trigger.get("@id"))
            return []

        w = _parse_duration(window_raw)
        if w is None or w <= timedelta(0):
            logger.warning("composite_all_invalid_window", window=window_raw, trigger=trigger.get("@id"))
            return []

        operands: list[str] = trigger.get("operands", [])
        if len(operands) < 2:
            logger.debug("composite_all_few_operands", count=len(operands), trigger=trigger.get("@id"))
            return []

        # Fetch and evaluate every operand
        operand_occurrences: list[list[datetime]] = []
        for op_iri in operands:
            if op_iri in visited:
                logger.warning("composite_cycle_detected", iri=op_iri, parent=self_iri)
                return []
            try:
                op_doc = await ctx.tdb.get_document(op_iri)
            except Exception:
                logger.warning("composite_operand_fetch_failed", iri=op_iri, parent=self_iri)
                return []

            try:
                fires = await ctx.get_occurrences(op_doc, window_start, window_end + w, visited.copy())
            except Exception:
                logger.warning("composite_operand_eval_failed", iri=op_iri, parent=self_iri)
                return []
            operand_occurrences.append(sorted(fires))

        # Any operand empty → no coincidences
        if any(len(occs) == 0 for occs in operand_occurrences):
            return []

        # Iterate over first operand's instants; check if all others have
        # at least one occurrence within [t, t+window]
        primary = operand_occurrences[0]
        others = operand_occurrences[1:]
        result: set[datetime] = set()

        for t in primary:
            hi = t + w
            if all(any(t <= o <= hi for o in other_occs) for other_occs in others):
                # Only include if t is within the original window
                if window_start < t <= window_end:
                    result.add(t)

        return sorted(result)


# ---------------------------------------------------------------------------
# EventTriggerEvaluator
# ---------------------------------------------------------------------------


def _make_event_key(commit_id: str, candidate_iri: str) -> str:
    """Build a short, stable occurrence key from a commit ID and candidate IRI.

    Uses a truncated commit ID prefix and a truncated SHA-256 hash of the
    candidate IRI to avoid percent-encoding issues in Lexical keys while
    preserving determinism.
    """
    iri_hash = hashlib.sha256(candidate_iri.encode()).hexdigest()[:12]
    return f"{commit_id[:12]}-{iri_hash}"


class EventTriggerEvaluator:
    """Evaluates ``EventTrigger`` — fires on change-feed events.

    Consumes ``ctx.changes`` (:class:`~firnline_core.tdb.ChangeEvent` list).
    For each change event, candidate IRIs depend on the trigger's ``event`` kind:

    * ``created`` — candidates from ``inserted`` IRIs
    * ``updated`` — candidates from ``updated`` IRIs
    * ``status_changed`` — candidates from ``updated`` IRIs, additionally
      filtered by ``field`` / ``to_value`` (best-effort: only post-update
      state is visible; fetches the current doc and checks equality).

    Subject matching: if ``trigger.subject`` is set → IRI equality;
    elif ``trigger.subject_class`` is set → prefix match ``f"{subject_class}/"``
    (this is a heuristic for class-name-based filtering).

    Occurrence timestamp: ``ChangeEvent.timestamp`` (fallback ``window_end``).
    Stores ``_event_keys`` — ``dict[str, dict[datetime, list[str]]]`` keyed
    by trigger ``@id`` then by scheduled instant, holding commit-stable
    occurrence keys (consumed by the engine).
    """

    name: str = "event"
    requires: list[ModuleRequirement] = [_TRIGGER_MODULE_REQ]
    trigger_types: tuple[str, ...] = ("EventTrigger",)

    def __init__(self) -> None:
        # trigger @id → { instant → list of commit-stable occurrence keys }
        self._event_keys: dict[str, dict[datetime, list[str]]] = {}

    async def occurrences(
        self,
        trigger: dict[str, Any],
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]:
        trigger_id: str = trigger.get("@id", "")
        # Clear only this trigger's keys (not all), so multiple EventTriggers
        # in the same cycle each get their own independent key map.
        self._event_keys[trigger_id] = {}

        event_kind: str = trigger.get("event", "created")
        # Map enum to change-event field
        if event_kind == "created":
            candidate_source = "inserted"
        elif event_kind in ("updated", "status_changed"):
            candidate_source = "updated"
        else:
            logger.debug("event_kind_unsupported", kind=event_kind, trigger=trigger_id)
            return []

        # For status_changed with field/to_value: fetch current doc
        field_filter: str | None = trigger.get("field") if event_kind == "status_changed" else None
        to_value: str | None = trigger.get("to_value") if event_kind == "status_changed" else None

        results: list[datetime] = []
        # Local alias for the per-trigger bucket to avoid repeated lookup
        key_bucket = self._event_keys[trigger_id]

        for change in ctx.changes:
            candidates: list[str] = getattr(change, candidate_source, [])

            for iri in candidates:
                if not self._matches_subject(iri, trigger.get("subject"), trigger.get("subject_class")):
                    continue

                if field_filter is not None:
                    try:
                        doc = await ctx.tdb.get_document(iri)
                    except Exception:
                        logger.debug("event_doc_fetch_failed", iri=iri, trigger=trigger_id)
                        continue
                    if doc.get(field_filter) != to_value:
                        continue

                ts = change.timestamp
                instant: datetime
                if ts is not None:
                    instant = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    instant = window_end

                # Build commit-stable occurrence key: short commit_id + hashed IRI
                key = _make_event_key(change.commit_id, iri)
                key_bucket.setdefault(instant, []).append(key)
                results.append(instant)

        return sorted(results)

    @staticmethod
    def _matches_subject(iri: str, subject: str | None, subject_class: str | None) -> bool:
        if subject is not None:
            return iri == subject
        if subject_class is not None:
            return iri.startswith(f"{subject_class}/")
        return True


# ---------------------------------------------------------------------------
# Plugin singletons (registered via entry points)
# ---------------------------------------------------------------------------

oneshot_plugin: TriggerEvaluator = OneShotEvaluator()  # type: ignore[assignment]
schedule_plugin: TriggerEvaluator = ScheduleEvaluator()  # type: ignore[assignment]
relative_plugin: TriggerEvaluator = RelativeEvaluator()  # type: ignore[assignment]
composite_plugin: TriggerEvaluator = CompositeEvaluator()  # type: ignore[assignment]
event_plugin: TriggerEvaluator = EventTriggerEvaluator()  # type: ignore[assignment]
