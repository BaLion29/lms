"""Calendar state — schema‑introspection‑driven calendar with Month/Week/Day views."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import TypedDict

import reflex as rx

from firnline_webui.calendar_introspect import (
    calendarable_classes,
    events_in_range,
    parse_events,
)
from firnline_webui.clients import WebuiClientError, make_tdb_browser
from firnline_webui.state.base import BaseState


# Typed shapes that Reflex can use to resolve nested Var types in rx.foreach.
class _CalEvent(TypedDict):
    id: str
    title: str
    color: str


class _CalPositionedEvent(TypedDict):
    id: str
    title: str
    color: str
    top_css: str
    height_css: str


class _CalMonthDay(TypedDict):
    date: str
    day: int
    in_month: bool
    is_today: bool
    events: list[_CalEvent]
    more_count: int


class _CalWeekDay(TypedDict):
    date: str
    label: str
    is_today: bool
    events: list[_CalPositionedEvent]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVENT_PALETTE = [
    "var(--cyan-9)",
    "var(--orange-9)",
    "var(--green-9)",
    "var(--purple-9)",
    "var(--pink-9)",
    "var(--blue-9)",
    "var(--amber-9)",
    "var(--teal-9)",
]

_VIEW_HOUR_MIN = 6 * 60  # 06:00 in minutes
_VIEW_HOUR_MAX = 22 * 60  # 22:00 in minutes
_VIEW_RANGE = _VIEW_HOUR_MAX - _VIEW_HOUR_MIN  # 960 minutes
_MIN_HEIGHT_PCT = 3.0


def _color_for_class(class_name: str) -> str:
    """Deterministic colour pick from the palette."""
    h = sum(ord(c) for c in class_name)
    return _EVENT_PALETTE[h % len(_EVENT_PALETTE)]


def _iso_date(some_date: date) -> str:
    return some_date.isoformat()


def _parse_date(iso: str) -> date:
    return date.fromisoformat(iso)


def _parse_dt(iso: str) -> datetime:
    """Parse ISO string, replacing trailing Z."""
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _position_event(ev: dict) -> dict[str, str]:
    """Return *ev* augmented with ``top_css`` and ``height_css`` strings."""
    try:
        s = _parse_dt(ev["start"])
    except (ValueError, KeyError):
        return {**ev, "top_css": "0%", "height_css": f"{_MIN_HEIGHT_PCT}%"}

    start_mins = s.hour * 60 + s.minute
    end_str = ev.get("end", "")
    if end_str:
        try:
            e = _parse_dt(end_str)
            end_mins = e.hour * 60 + e.minute
        except (ValueError, TypeError):
            end_mins = start_mins
    else:
        end_mins = start_mins  # instantaneous

    # Clamp to view window
    display_start = max(_VIEW_HOUR_MIN, start_mins)
    display_end = min(_VIEW_HOUR_MAX, max(display_start, end_mins))

    if display_start >= _VIEW_HOUR_MAX:
        return {**ev, "top_css": "100%", "height_css": "0%"}

    top_pct = (display_start - _VIEW_HOUR_MIN) / _VIEW_RANGE * 100
    height_pct = max(_MIN_HEIGHT_PCT, (display_end - display_start) / _VIEW_RANGE * 100)

    return {
        **ev,
        "top_css": f"{top_pct:.1f}%",
        "height_css": f"{height_pct:.1f}%",
    }


def _events_for_date(events: list[dict], day: date) -> list[dict]:
    """Filter events overlapping *day* (colour already assigned during load)."""
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    filtered = events_in_range(events, day_start, day_end)
    # Read-only: colour is assigned during load; never mutate shared state dicts.
    return filtered


# ---------------------------------------------------------------------------
# CalendarState
# ---------------------------------------------------------------------------


class CalendarState(BaseState):
    """State for the /calendar page."""

    view_mode: str = "month"
    cursor_date: str = ""  # ISO date; defaults to today on first load

    available_classes: list[dict] = []
    enabled_classes: list[str] = []
    events: list[dict] = []

    loading: bool = False
    error: str = ""

    # Detail drawer
    selected_doc: dict | None = None
    selected_json: str = ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cursor(self) -> date:
        """Parse *cursor_date* or return today."""
        if self.cursor_date:
            try:
                return _parse_date(self.cursor_date)
            except ValueError:
                pass
        return date.today()

    def _enabled_specs(self) -> list[dict]:
        return [s for s in self.available_classes if s["class_id"] in self.enabled_classes]

    # ------------------------------------------------------------------
    # Computed vars
    # ------------------------------------------------------------------

    @rx.var
    def period_label(self) -> str:
        cursor = self._cursor()
        mode = self.view_mode

        if mode == "month":
            return cursor.strftime("%B %Y")
        elif mode == "week":
            monday = cursor - timedelta(days=cursor.weekday())
            sunday = monday + timedelta(days=6)
            if monday.month == sunday.month:
                return f"{monday.strftime('%b %-d')} – {sunday.strftime('%b %-d, %Y')}"  # type: ignore[str-bytes-safe]
            elif monday.year == sunday.year:
                return f"{monday.strftime('%b %-d')} – {sunday.strftime('%b %-d, %Y')}"  # type: ignore[str-bytes-safe]
            else:
                return f"{monday.strftime('%b %-d, %Y')} – {sunday.strftime('%b %-d, %Y')}"  # type: ignore[str-bytes-safe]
        else:  # day
            return cursor.strftime("%A, %b %-d %Y")

    @rx.var
    def month_weeks(self) -> list[list[_CalMonthDay]]:
        cursor = self._cursor()
        today = date.today()
        events = self.events

        first = date(cursor.year, cursor.month, 1)
        days_since_monday = first.weekday()
        week_start = first - timedelta(days=days_since_monday)

        weeks: list[list[_CalMonthDay]] = []
        for w in range(6):
            week: list[_CalMonthDay] = []
            for d in range(7):
                day = week_start + timedelta(days=w * 7 + d)
                day_events = _events_for_date(events, day)
                more = max(0, len(day_events) - 3)
                cell: _CalMonthDay = {
                    "date": _iso_date(day),
                    "day": day.day,
                    "in_month": day.month == cursor.month,
                    "is_today": day == today,
                    "events": day_events[:3],
                    "more_count": more,
                }
                week.append(cell)
            weeks.append(week)
        return weeks

    @rx.var
    def week_days(self) -> list[_CalWeekDay]:
        cursor = self._cursor()
        today = date.today()
        events = self.events

        monday = cursor - timedelta(days=cursor.weekday())
        result: list[_CalWeekDay] = []
        for i in range(7):
            day = monday + timedelta(days=i)
            day_events = _events_for_date(events, day)
            positioned = [_position_event(ev) for ev in day_events]
            result.append(
                {
                    "date": _iso_date(day),
                    "label": day.strftime("%a %-d"),
                    "is_today": day == today,
                    "events": positioned,
                }
            )
        return result

    @rx.var
    def day_events(self) -> list[_CalPositionedEvent]:
        cursor = self._cursor()
        day_events = _events_for_date(self.events, cursor)
        return [_position_event(ev) for ev in day_events]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @rx.event
    async def load(self):
        """Fetch schema, compute calendarable classes, load events."""
        self.loading = True
        self.error = ""
        yield

        # Default cursor to today
        if not self.cursor_date:
            self.cursor_date = _iso_date(date.today())

        tdb = make_tdb_browser()
        try:
            schema = await tdb.get_schema()
        except WebuiClientError as exc:
            self.error = f"Failed to load schema: {exc.detail}"
            self.loading = False
            await tdb.aclose()
            yield
            return

        # Calendarable classes
        specs = calendarable_classes(schema)
        self.available_classes = specs

        # Default: enable all
        if not self.enabled_classes:
            self.enabled_classes = [s["class_id"] for s in specs]

        # Fetch documents for enabled classes
        all_events: list[dict] = []
        failed_classes: list[str] = []
        for spec in specs:
            if spec["class_id"] not in self.enabled_classes:
                continue
            try:
                docs = await tdb.get_documents(spec["class_id"])
                class_events = parse_events(docs, spec)
                for ev in class_events:
                    ev["color"] = _color_for_class(spec["class_id"])
                all_events.extend(class_events)
            except WebuiClientError as exc:
                failed_classes.append(f"{spec['class_id']}: {exc.detail}")
                continue
        if failed_classes:
            self.error = " | ".join(failed_classes)

        await tdb.aclose()
        self.events = all_events
        self.loading = False
        yield

    @rx.event
    def set_view(self, mode: str):
        self.view_mode = mode
        yield

    @rx.event
    def prev(self):
        cursor = self._cursor()
        mode = self.view_mode
        if mode == "month":
            # First of current month, then first of previous month
            first = date(cursor.year, cursor.month, 1)
            prev_month = first - timedelta(days=1)
            self.cursor_date = _iso_date(date(prev_month.year, prev_month.month, 1))
        elif mode == "week":
            monday = cursor - timedelta(days=cursor.weekday())
            self.cursor_date = _iso_date(monday - timedelta(days=7))
        else:
            self.cursor_date = _iso_date(cursor - timedelta(days=1))
        yield

    @rx.event
    def next(self):
        cursor = self._cursor()
        mode = self.view_mode
        if mode == "month":
            first = date(cursor.year, cursor.month, 1)
            next_month = first + timedelta(days=32)
            self.cursor_date = _iso_date(date(next_month.year, next_month.month, 1))
        elif mode == "week":
            monday = cursor - timedelta(days=cursor.weekday())
            self.cursor_date = _iso_date(monday + timedelta(days=7))
        else:
            self.cursor_date = _iso_date(cursor + timedelta(days=1))
        yield

    @rx.event
    def today(self):
        self.cursor_date = _iso_date(date.today())
        yield

    @rx.event
    def toggle_class(self, class_id: str):
        if class_id in self.enabled_classes:
            self.enabled_classes = [c for c in self.enabled_classes if c != class_id]
        else:
            self.enabled_classes = self.enabled_classes + [class_id]
        return CalendarState.load

    @rx.event
    async def select_event(self, doc_id: str):
        """Fetch a single document and open the detail drawer."""
        if not doc_id:
            return
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(doc_id)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def clear_selection(self):
        self.selected_doc = None
        self.selected_json = ""
        yield
