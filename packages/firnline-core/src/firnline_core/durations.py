"""ISO-8601 duration and datetime parsing utilities.

Supported subset:

* Durations: optional leading ``-`` sign, ``P[nD][T[nH][nM][nS]]``.
  Returns ``None`` on malformed input (including bare ``P``, trailing ``T``,
  or no-component matches like ``P0DT0H0M0S`` which map to zero but are
  rejected because the base regex requires at least one digit in a group).

* Datetimes: ``datetime.fromisoformat`` with ``Z`` → ``+00:00`` replacement.
  Naive values are interpreted as UTC.  The return value is always a
  timezone-aware UTC ``datetime``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_DURATION_RE = re.compile(
    r"^(?P<sign>-?)P"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
    r"$"
)


def parse_duration(raw: str) -> timedelta | None:
    """Parse an ISO-8601 duration string into a ``timedelta``.

    Supported subset: optional leading ``-``, ``P[nD][T[nH][nM][nS]]``.
    Returns ``None`` on malformed input.
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


def parse_iso_datetime(raw: str) -> datetime:
    """Parse an ISO-8601 datetime string to a tz-aware UTC datetime.

    Naive values are treated as UTC.  Handles Z suffix, ±HH:MM offsets,
    and sub-second precision.
    """
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
