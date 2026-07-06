"""First-party trigger evaluators.

Each evaluator handles one trigger ``@type`` and returns UTC fire instants
for a half-open window ``(window_start, window_end]``.

All datetime values returned from TDB are parsed as ISO-8601 strings.
Naive datetimes are treated as UTC (TDB convention).
"""

from __future__ import annotations

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

_TRIGGER_MODULE_REQ = ModuleRequirement(name="triggers", range=">=1.1.0 <2.0.0")

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
# Anchor resolver (exported for unit-testing; wired by the engine in Phase 5)
# ---------------------------------------------------------------------------

_ANCHOR_FIELDS: dict[str, str] = {
    "Event": "start_datetime",
    "Task": "due_date",
    "Activity": "start_datetime",
}


async def resolve_anchor(ctx: EvalContext, anchor_ref: str | dict[str, Any]) -> datetime | None:
    """Resolve a Remindable document/IRI to its temporal instant.

    Returns the anchor datetime (tz-aware UTC) or ``None`` when the
    anchor class is unsupported or the temporal field is missing.
    """
    if isinstance(anchor_ref, dict):
        doc = anchor_ref
    else:
        doc = await ctx.tdb.get_document(anchor_ref)

    rtype = doc.get("@type")
    if rtype not in _ANCHOR_FIELDS:
        logger.warning("anchor_unsupported", type=rtype, iri=doc.get("@id"))
        return None

    field_name = _ANCHOR_FIELDS[rtype]
    value = doc.get(field_name)
    if value is None:
        logger.warning("anchor_field_missing", type=rtype, iri=doc.get("@id"), field=field_name)
        return None

    return _parse_iso_datetime(value)


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
    """Evaluates ``CompositeTrigger`` — ``or`` combination of operand triggers.

    ``and`` / ``not`` modes are unsupported and logged with a warning.
    Cycle detection uses a ``visited`` set of trigger IRIs.
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
        mode: str = trigger.get("mode", "or")

        if mode not in ("or",):
            logger.warning("composite_mode_unsupported", mode=mode, trigger=trigger.get("@id"))
            return []

        visited: set[str] = set()
        return await self._eval_or(trigger, window_start, window_end, ctx, visited)

    async def _eval_or(
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
                # Per-branch visited copy: true cycle detection with diamond-shaped operand graph support.
                fires = await ctx.get_occurrences(op_doc, window_start, window_end, visited.copy())
            except Exception:
                logger.warning("composite_operand_eval_failed", iri=op_iri, parent=self_iri)
                continue

            all_fires.update(fires)

        return sorted(all_fires)


# ---------------------------------------------------------------------------
# Plugin singletons (registered via entry points)
# ---------------------------------------------------------------------------

oneshot_plugin: TriggerEvaluator = OneShotEvaluator()  # type: ignore[assignment]
schedule_plugin: TriggerEvaluator = ScheduleEvaluator()  # type: ignore[assignment]
relative_plugin: TriggerEvaluator = RelativeEvaluator()  # type: ignore[assignment]
composite_plugin: TriggerEvaluator = CompositeEvaluator()  # type: ignore[assignment]
