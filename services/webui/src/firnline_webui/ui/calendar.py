"""Calendar view components — month grid, week grid, day column."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.calendar import CalendarState

_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DAY_CELL_H = "110px"


# White text on coloured event blocks — intentionally not a semantic
# colour token because gray-1 is near-black in dark mode and would be
# unreadable on the accent-9 event backgrounds from EVENT_PALETTE.
EVENT_TEXT_COLOR = "white"


# ── Shared event block ──────────────────────────────────────────────────


def _event_block(ev: rx.Var[dict]) -> rx.Component:
    """Small coloured chip for a calendar event (month view)."""
    return rx.badge(
        rx.text(
            ev["title"].to(str),
            size="1",
            max_width="100%",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        variant="solid",
        color_scheme="gray",
        size="1",
        width="100%",
        cursor="pointer",
        background=ev["color"],
        color=EVENT_TEXT_COLOR,
        on_click=CalendarState.select_event(ev["id"]),  # type: ignore[arg-type]
    )


def _positioned_block(ev: rx.Var[dict]) -> rx.Component:
    """Absolutely‑positioned event block for week/day view."""

    return rx.box(
        rx.text(
            ev["title"].to(str),
            size="1",
            font_weight="medium",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            color=EVENT_TEXT_COLOR,
            padding_x="4px",
        ),
        position="absolute",
        top=ev["top_css"],
        height=ev["height_css"],
        left="1px",
        right="1px",
        background=ev["color"],
        border_radius="4px",
        overflow="hidden",
        cursor="pointer",
        z_index="2",
        on_click=CalendarState.select_event(ev["id"]),  # type: ignore[arg-type]
    )


# ── Month grid ──────────────────────────────────────────────────────────


def month_grid() -> rx.Component:
    """Month calendar grid — 6 weeks × 7 days."""
    return rx.box(
        # Weekday header
        rx.grid(
            *[
                rx.text(label, size="1", weight="medium", color_scheme="gray", text_align="center")
                for label in _WEEKDAY_LABELS
            ],
            columns="7",
            width="100%",
            gap="1px",
            margin_bottom="4px",
        ),
        # Weeks
        rx.foreach(
            CalendarState.month_weeks,
            lambda week: rx.grid(
                rx.foreach(
                    week,
                    _day_cell,
                ),
                columns="7",
                width="100%",
                gap="1px",
            ),
        ),
        width="100%",
    )


def _day_cell(day: rx.Var[dict]) -> rx.Component:
    """A single day cell in the month grid."""
    return rx.box(
        rx.vstack(
            rx.text(
                day["day"].to(str),
                size="1",
                weight="medium",
                color=rx.cond(
                    day["is_today"],
                    "white",
                    rx.cond(day["in_month"], rx.color("gray", 11), rx.color("gray", 6)),
                ),
                background=rx.cond(
                    day["is_today"],
                    rx.color("accent", 9),
                    "transparent",
                ),
                border_radius=rx.cond(day["is_today"], "50%", "0"),
                width="22px",
                height="22px",
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            # Event chips (up to 3)
            rx.foreach(
                day["events"],
                lambda ev: _event_block(ev),
            ),
            # "+N more"
            rx.cond(
                day["more_count"] > 0,
                rx.text(
                    f"+{day['more_count']} more",
                    size="1",
                    color_scheme="gray",
                    cursor="pointer",
                ),
            ),
            spacing="1",
            align="start",
            width="100%",
            padding="4px",
        ),
        border=f"1px solid {rx.color('gray', 4)}",
        border_radius="6px",
        min_height=_DAY_CELL_H,
        background=rx.cond(day["in_month"], rx.color("gray", 1), rx.color("gray", 2)),
        width="100%",
        overflow="hidden",
    )


# ── Week grid ───────────────────────────────────────────────────────────


def week_grid() -> rx.Component:
    """Week view — 7 columns with time‑positioned events."""
    return rx.box(
        rx.grid(
            rx.foreach(
                CalendarState.week_days,
                _week_column,
            ),
            columns="7",
            width="100%",
            gap="1px",
        ),
        width="100%",
    )


def _week_column(day: rx.Var[dict]) -> rx.Component:
    """Single column in the week grid."""
    return rx.box(
        rx.vstack(
            # Day header
            rx.text(
                day["label"].to(str),
                size="1",
                weight="medium",
                text_align="center",
                color=rx.cond(day["is_today"], rx.color("accent", 9), rx.color("gray", 11)),
                background=rx.cond(day["is_today"], rx.color("accent", 3), "transparent"),
                border_radius="4px",
                padding_y="2px",
                width="100%",
            ),
            # Event container
            rx.box(
                rx.foreach(
                    day["events"],
                    lambda ev: _positioned_block(ev),
                ),
                position="relative",
                width="100%",
                height="640px",
                border=f"1px solid {rx.color('gray', 4)}",
                border_radius="4px",
                background=rx.color("gray", 1),
            ),
            spacing="1",
            width="100%",
        ),
        width="100%",
    )


# ── Day column ──────────────────────────────────────────────────────────

_HOURS = [f"{h:02d}:00" for h in range(6, 23)]


def day_column() -> rx.Component:
    """Single‑day view with hour gridlines."""
    return rx.box(
        rx.hstack(
            # Hour labels
            rx.vstack(
                *[
                    rx.text(
                        hour,
                        size="1",
                        color_scheme="gray",
                        width="48px",
                        text_align="right",
                        padding_right="8px",
                        height=f"{640 // 16}px",
                        line_height=f"{640 // 16}px",
                    )
                    for hour in _HOURS
                ],
                spacing="0",
                width="48px",
            ),
            # Event lane
            rx.box(
                # Hour grid lines
                *[
                    rx.box(
                        position="absolute",
                        top=f"{i * (100 / 16):.1f}%",
                        left="0",
                        right="0",
                        height="1px",
                        background=rx.color("gray", 4),
                        z_index="0",
                    )
                    for i in range(1, 16)
                ],
                # Events
                rx.foreach(
                    CalendarState.day_events,
                    lambda ev: _positioned_block(ev),
                ),
                position="relative",
                flex="1",
                height="640px",
                border=f"1px solid {rx.color('gray', 4)}",
                border_radius="4px",
                background=rx.color("gray", 1),
            ),
            spacing="0",
            width="100%",
        ),
        width="100%",
    )
