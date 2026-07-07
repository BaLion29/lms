"""Pure introspection helpers for the calendar view — unit‑testable without Reflex.

These functions work on schema, class-definition, and document dicts returned by
:class:`firnline_webui.clients.TdbBrowser`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from firnline_core.tdb import short_iri

# ---------------------------------------------------------------------------
# Datetime field detection
# ---------------------------------------------------------------------------


def datetime_fields(class_def: dict) -> list[str]:
    """Return field names whose type is ``xsd:dateTime``.

    Handles both plain-string values (``"xsd:dateTime"``) and dict values
    (``{"@class": "xsd:dateTime", ...}``).
    """
    result: list[str] = []
    for key, value in class_def.items():
        if key.startswith("@"):
            continue
        if value == "xsd:dateTime":
            result.append(key)
        elif isinstance(value, dict) and value.get("@class") == "xsd:dateTime":
            result.append(key)
    return result


# ---------------------------------------------------------------------------
# Calendarable class discovery
# ---------------------------------------------------------------------------

# Keywords for role inference (case‑insensitive matching).
_START_KEYWORDS = ["start_datetime", "start", "starts_at", "begin", "begin_at", "when"]
_END_KEYWORDS = ["end_datetime", "end", "ends_at", "finish"]


def calendarable_classes(schema: list[dict]) -> list[dict]:
    """Return specs for non‑abstract, non‑subdocument Classes with ≥1 dateTime field.

    Each returned spec dict has keys:

    * ``class_id`` — the ``@id`` of the class.
    * ``datetime_fields`` — all dateTime field names.
    * ``start_field`` — inferred start field (``None`` if none).
    * ``end_field`` — inferred end field (``None`` if none).
    * ``instant_field`` — inferred instant field (``None`` if a start was found).
    * ``title_field`` — preferred display field name.
    """
    result: list[dict] = []
    for entry in schema:
        if entry.get("@type") != "Class":
            continue
        if entry.get("@abstract") or entry.get("@subdocument"):
            continue

        class_id = entry.get("@id", "")
        if not isinstance(class_id, str) or not class_id:
            continue

        dt_fields = datetime_fields(entry)
        if not dt_fields:
            continue

        dt_lower = {f.lower(): f for f in dt_fields}

        # -- Role inference ---------------------------------------------------
        start_field: str | None = None
        end_field: str | None = None

        # Start: prefer exact match, then prefix "start".
        for kw in _START_KEYWORDS:
            if kw in dt_lower:
                start_field = dt_lower[kw]
                break
        if start_field is None:
            for orig_name in dt_fields:
                if orig_name.lower().startswith("start"):
                    start_field = orig_name
                    break

        # End: prefer exact match, then prefix "end".
        for kw in _END_KEYWORDS:
            if kw in dt_lower:
                candidate = dt_lower[kw]
                if candidate != start_field:  # never double‑assign
                    end_field = candidate
                break
        if end_field is None:
            for orig_name in dt_fields:
                if orig_name.lower().startswith("end") and orig_name != start_field:
                    end_field = orig_name
                    break

        # Instant: only if no start was found.
        instant_field: str | None = None
        if start_field is None:
            instant_field = dt_fields[0]

        # -- Title field -------------------------------------------------------
        title_field: str = "@id"
        if "name" in entry:
            title_field = "name"
        elif "title" in entry:
            title_field = "title"

        result.append(
            {
                "class_id": class_id,
                "datetime_fields": dt_fields,
                "start_field": start_field if start_field else None,  # type: ignore[dict-item]
                "end_field": end_field if end_field else None,  # type: ignore[dict-item]
                "instant_field": instant_field,
                "title_field": title_field,
            }
        )

    return result


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def parse_events(docs: list[dict], spec: dict) -> list[dict]:
    """Normalise documents of one class into calendar events.

    *spec* is a dict from :func:`calendarable_classes` (possibly user‑overridden).
    Returns a list of event dicts with keys ``id``, ``class``, ``title``,
    ``start``, ``end``, ``all_day``, ``color``.
    """
    start_field: str | None = spec.get("start_field")
    end_field: str | None = spec.get("end_field")
    instant_field: str | None = spec.get("instant_field")
    title_field: str = spec.get("title_field", "@id")
    class_id: str = spec.get("class_id", "")

    events: list[dict] = []
    for doc in docs:
        start_val: str | None = None
        end_val: str | None = None

        if start_field is not None and start_field in doc:
            start_val = _extract_datetime_str(doc.get(start_field))
            if start_val is not None:
                end_val = _extract_datetime_str(doc.get(end_field) if end_field else None)
        elif instant_field is not None and instant_field in doc:
            start_val = _extract_datetime_str(doc.get(instant_field))
            if start_val is not None:
                end_val = None  # instant — no end

        if start_val is None:
            continue

        # Normalise and validate.
        try:
            _normalise_and_parse(start_val)
        except ValueError:
            continue
        if end_val:
            try:
                _normalise_and_parse(end_val)
            except ValueError:
                end_val = None

        # Title
        title_raw = doc.get(title_field)
        if title_raw is not None and title_raw != "" and str(title_raw):
            title = str(title_raw)
        else:
            iri = str(doc.get("@id", ""))
            title = short_iri(iri)

        events.append(
            {
                "id": doc.get("@id", ""),
                "class": class_id,
                "title": title,
                "start": start_val,
                "end": end_val if end_val else "",
                "all_day": False,
            }
        )
    return events


# ---------------------------------------------------------------------------
# Range filtering
# ---------------------------------------------------------------------------


def events_in_range(
    events: list[dict],
    range_start: datetime,
    range_end: datetime,
) -> list[dict]:
    """Filter *events* to those overlapping ``[range_start, range_end)``.

    An event with an empty *end* is treated as instantaneous.
    Timezone‑naive event datetimes are assumed UTC.
    """
    rs = _ensure_utc(range_start)
    re = _ensure_utc(range_end)
    result: list[dict] = []

    for ev in events:
        try:
            ev_start = _ensure_utc(_normalise_and_parse(ev["start"]))
        except (ValueError, KeyError):
            continue

        ev_end_str = ev.get("end", "")
        if ev_end_str:
            try:
                ev_end = _ensure_utc(_normalise_and_parse(ev_end_str))
            except (ValueError, TypeError):
                ev_end = ev_start
        else:
            ev_end = ev_start

        # Half‑open interval overlap
        if ev_start < re and ev_end > rs:
            result.append(ev)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_datetime_str(value: Any) -> str | None:
    """Return a datetime string from a scalar or dict value, or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        v = value.get("@value") or value.get("text") or ""
        if isinstance(v, str):
            return v
    return None


def _normalise_and_parse(dt_str: str) -> datetime:
    """Parse an ISO 8601 string, replacing trailing ``Z`` with ``+00:00``.

    Raises :class:`ValueError` on unparsable input.
    """
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _ensure_utc(dt: datetime) -> datetime:
    """Return *dt* as a UTC‑aware datetime (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
