"""Calendar state — introspection-driven calendar view (framework-free)."""
from __future__ import annotations

from dataclasses import dataclass, field

from firnline_core.calendar_introspect import calendarable_classes, parse_events
from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext

# Cal event palette — plain color names usable in both TUI and web contexts
_EVENT_PALETTE = [
    "cyan",
    "orange",
    "green",
    "purple",
    "pink",
    "blue",
    "amber",
    "teal",
]


@dataclass(frozen=True)
class CalendarData:
    available_classes: tuple[dict, ...] = ()
    events: tuple[dict, ...] = ()
    error: str = ""


async def load_calendar(ctx: AppContext) -> CalendarData:
    """Fetch schema, compute calendarable classes, load events."""
    tdb = ctx.make_tdb()
    try:
        schema = await tdb.get_schema()
    except UiClientError as exc:
        await tdb.aclose()
        return CalendarData(error=f"Failed to load schema: {exc.detail}")

    specs = calendarable_classes(schema)

    # Fetch documents for all calendarable classes
    all_events: list[dict] = []
    failed: list[str] = []

    for spec in specs:
        try:
            docs = await tdb.get_documents(spec["class_id"])
            class_events = parse_events(docs, spec)
            color = _color_for_class(spec["class_id"])
            for ev in class_events:
                ev["color"] = color
            all_events.extend(class_events)
        except UiClientError as exc:
            failed.append(f"{spec['class_id']}: {exc.detail}")
            continue

    await tdb.aclose()

    error = ""
    if failed:
        error = " | ".join(failed)

    return CalendarData(
        available_classes=tuple(specs),
        events=tuple(all_events),
        error=error,
    )


def _color_for_class(class_name: str) -> str:
    """Deterministic colour pick from the palette."""
    h = sum(ord(c) for c in class_name)
    return _EVENT_PALETTE[h % len(_EVENT_PALETTE)]
