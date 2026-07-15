"""Calendar page — schema‑introspection‑driven calendar with Month/Week/Day views."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.calendar import CalendarState
from firnline_webui.ui.calendar import day_column, month_grid, week_grid
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import error_callout, loading_spinner
from firnline_webui.ui.nav import shell
from firnline_webui.ui.typography import page_heading


def calendar_page() -> rx.Component:
    """Calendar page entry point."""
    return shell(
        rx.vstack(
            # ── Toolbar ──────────────────────────────────────────────────
            _toolbar(),
            # ── Error ────────────────────────────────────────────────────
            rx.cond(
                CalendarState.error != "",
                error_callout(CalendarState.error),
            ),
            # ── Body ────────────────────────────────────────────────────
            rx.cond(
                CalendarState.loading,
                loading_spinner(),
                rx.match(
                    CalendarState.view_mode,
                    ("month", month_grid()),
                    ("week", week_grid()),
                    ("day", day_column()),
                    month_grid(),
                ),
            ),
            # ── Detail drawer ───────────────────────────────────────────
            json_detail_drawer(
                doc_var=CalendarState.selected_doc,
                json_var=CalendarState.selected_json,
                iri_var=iri_var(CalendarState.selected_doc),
                on_close=CalendarState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="calendar",
    )


# ── Toolbar ───────────────────────────────────────────────────────────────


def _toolbar() -> rx.Component:
    return rx.hstack(
        # Navigation
        rx.icon_button(
            rx.icon(tag="chevron_left", size=16),
            variant="ghost",
            size="1",
            on_click=CalendarState.prev,
            custom_attrs={"aria-label": "Previous period"},
        ),
        rx.icon_button(
            rx.icon(tag="calendar_days", size=16),
            variant="ghost",
            size="1",
            on_click=CalendarState.today,
            custom_attrs={"aria-label": "Go to today"},
        ),
        rx.icon_button(
            rx.icon(tag="chevron_right", size=16),
            variant="ghost",
            size="1",
            on_click=CalendarState.next,
            custom_attrs={"aria-label": "Next period"},
        ),
        # Period heading
        page_heading(CalendarState.period_label),
        rx.spacer(),
        # View mode toggle
        _view_toggle(),
        # Class filter popover
        _class_filter_popover(),
        # Refresh / spinner
        rx.cond(
            CalendarState.loading,
            rx.spinner(size="3"),
            rx.icon_button(
                rx.icon(tag="refresh_cw", size=16),
                variant="ghost",
                size="1",
                on_click=CalendarState.load,
                custom_attrs={"aria-label": "Refresh calendar"},
            ),
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _view_toggle() -> rx.Component:
    """Three‑button toggle for Month / Week / Day."""
    active = CalendarState.view_mode
    return rx.hstack(
        rx.button(
            "Month",
            size="1",
            variant=rx.cond(active == "month", "solid", "outline"),
            on_click=CalendarState.set_view("month"),
        ),
        rx.button(
            "Week",
            size="1",
            variant=rx.cond(active == "week", "solid", "outline"),
            on_click=CalendarState.set_view("week"),
        ),
        rx.button(
            "Day",
            size="1",
            variant=rx.cond(active == "day", "solid", "outline"),
            on_click=CalendarState.set_view("day"),
        ),
        spacing="0",
    )


def _class_filter_popover() -> rx.Component:
    """Popover with checkboxes to enable/disable calendarable classes."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.icon_button(
                rx.icon(tag="filter", size=16),
                variant="ghost",
                size="1",
                custom_attrs={"aria-label": "Filter classes"},
            ),
        ),
        rx.popover.content(
            rx.vstack(
                rx.text("Show classes", size="2", weight="medium"),
                rx.foreach(
                    CalendarState.available_classes,
                    lambda spec: rx.checkbox(
                        spec["class_id"].to(str),
                        checked=CalendarState.enabled_classes.contains(spec["class_id"]),  # type: ignore[arg-type]
                        on_change=CalendarState.toggle_class(spec["class_id"]),  # type: ignore[arg-type]
                        size="1",
                    ),
                ),
                spacing="1",
                width="100%",
            ),
            width="220px",
        ),
    )
