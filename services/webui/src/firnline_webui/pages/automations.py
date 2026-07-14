"""Automations page — trigger firings and action executions."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.automations import AutomationsState
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.feedback import empty_state as _empty_state, error_callout
from firnline_webui.ui.nav import shell

# ---------------------------------------------------------------------------
# Status badge helpers
# ---------------------------------------------------------------------------


_FIRING_STATUS_COLORS: dict[str, str] = {
    "pending": "amber",
    "notified": "blue",
    "acknowledged": "green",
    "snoozed": "violet",
    "expired": "gray",
}

_EXECUTION_STATUS_COLORS: dict[str, str] = {
    "pending_approval": "amber",
    "pending": "blue",
    "succeeded": "green",
    "failed": "red",
    "dead": "red",
    "skipped": "gray",
}


def _firing_status_badge(status: str) -> rx.Component:
    cs = _FIRING_STATUS_COLORS.get(status, "gray")
    return rx.badge(
        rx.hstack(
            rx.box(width="6px", height="6px", border_radius="50%", background=rx.color(cs, 9)),
            rx.text(status, size="1"),
            spacing="1",
            align="center",
        ),
        color_scheme=cs,
        variant="surface",
        size="1",
    )


def _execution_status_badge(status: str) -> rx.Component:
    cs = _EXECUTION_STATUS_COLORS.get(status, "gray")
    return rx.badge(
        rx.hstack(
            rx.box(width="6px", height="6px", border_radius="50%", background=rx.color(cs, 9)),
            rx.text(status, size="1"),
            spacing="1",
            align="center",
        ),
        color_scheme=cs,
        variant="surface",
        size="1",
    )


# ---------------------------------------------------------------------------
# Filter chips
# ---------------------------------------------------------------------------


def _filter_chip(label: str, value: str, is_active: rx.Var[bool], on_click) -> rx.Component:
    return rx.badge(
        rx.hstack(
            rx.text(label, size="1"),
            rx.cond(is_active, rx.icon(tag="check", size=12)),
            spacing="1",
        ),
        variant=rx.cond(is_active, "solid", "soft"),
        color_scheme="cyan",
        cursor="pointer",
        on_click=on_click(value),
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _firings_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Trigger"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell("Scheduled"),
                rx.table.column_header_cell("Fired At"),
                rx.table.column_header_cell("Subject"),
                rx.table.column_header_cell("Notify #"),
            ),
        ),
        rx.table.body(
            rx.foreach(
                AutomationsState.filtered_firing_rows,
                lambda row: rx.table.row(
                    rx.table.cell(rx.text(row["trigger_name"], size="2", weight="medium")),
                    rx.table.cell(_firing_status_badge(row["status"])),
                    rx.table.cell(rx.text(row["scheduled_for"], size="2")),
                    rx.table.cell(rx.text(row["fired_at"], size="2")),
                    rx.table.cell(
                        rx.cond(
                            row["subject"] != "",  # type: ignore[index]
                            rx.text(row["subject"], size="2"),  # type: ignore[index]
                            rx.text("—", size="2", color_scheme="gray"),
                        )
                    ),
                    rx.table.cell(rx.text(row["notification_count"], size="2")),  # type: ignore[index]
                    cursor="pointer",
                    _hover={"bg": rx.color("accent", 2)},
                    _odd={"background": rx.color("gray", 2)},
                    tab_index=0,
                    role="button",
                    on_click=AutomationsState.select(row["id"]),  # type: ignore[index]
                ),
            ),
        ),
        variant="surface",
        size="3",
        width="100%",
    )


def _executions_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Action"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell("Attempt"),
                rx.table.column_header_cell("Executed / Next"),
                rx.table.column_header_cell("Result"),
                rx.table.column_header_cell("Approved By"),
            ),
        ),
        rx.table.body(
            rx.foreach(
                AutomationsState.filtered_execution_rows,
                lambda row: rx.table.row(
                    rx.table.cell(rx.text(row["action_name"], size="2", weight="medium")),
                    rx.table.cell(_execution_status_badge(row["status"])),
                    rx.table.cell(rx.text(row["attempt"], size="2")),  # type: ignore[index]
                    rx.table.cell(
                        rx.cond(
                            row["executed_at"] != "",  # type: ignore[index]
                            rx.text(row["executed_at"], size="2"),  # type: ignore[index]
                            rx.text(row["next_attempt_at"], size="2"),  # type: ignore[index]
                        )
                    ),
                    rx.table.cell(
                        rx.text(
                            row["result_detail"],  # type: ignore[index]
                            size="2",
                            color_scheme="gray",
                            max_width="250px",
                            overflow="hidden",
                            text_overflow="ellipsis",
                            white_space="nowrap",
                        ),
                        title=row["result_detail"].to(str),  # type: ignore[index]
                    ),
                    rx.table.cell(
                        rx.cond(
                            row["approved_by"] != "",  # type: ignore[index]
                            rx.text(row["approved_by"], size="2"),  # type: ignore[index]
                            rx.text("—", size="2", color_scheme="gray"),
                        )
                    ),
                    cursor="pointer",
                    _hover={"bg": rx.color("accent", 2)},
                    _odd={"background": rx.color("gray", 2)},
                    tab_index=0,
                    role="button",
                    on_click=AutomationsState.select(row["id"]),  # type: ignore[index]
                ),
            ),
        ),
        variant="surface",
        size="3",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------


def _no_firings_state() -> rx.Component:
    return _empty_state("zap", "No trigger firings found.")


def _no_executions_state() -> rx.Component:
    return _empty_state("zap", "No action executions found.")


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _firings_section() -> rx.Component:
    return rx.vstack(
        # Summary badges + title
        rx.hstack(
            rx.text("Trigger Firings", size="4", weight="medium"),
            rx.spacer(),
            rx.cond(
                AutomationsState.pending_firings_count > 0,
                rx.badge(
                    rx.hstack(
                        rx.box(
                            width="6px",
                            height="6px",
                            border_radius="50%",
                            background=rx.color("amber", 9),
                        ),
                        rx.text(
                            rx.Var.create(f"{AutomationsState.pending_firings_count} pending"),
                            size="1",
                        ),
                        spacing="1",
                        align="center",
                    ),
                    color_scheme="amber",
                    variant="surface",
                    size="1",
                ),
            ),
            rx.cond(
                AutomationsState.pending_firings_count == 0,
                rx.badge(
                    "no pending",
                    color_scheme="green",
                    variant="surface",
                    size="1",
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        # Status filter chips
        rx.cond(
            AutomationsState.available_firing_statuses.length() > 0,
            rx.hstack(
                rx.text("Filter:", size="2", color_scheme="gray"),
                _filter_chip(
                    "All", "all", AutomationsState.firing_status_filter == "all", AutomationsState.set_firing_filter
                ),
                rx.foreach(
                    AutomationsState.available_firing_statuses,
                    lambda s: _filter_chip(
                        s, s, AutomationsState.firing_status_filter == s, AutomationsState.set_firing_filter
                    ),
                ),
                spacing="1",
                align="center",
                wrap="wrap",
            ),
        ),
        # Table / empty
        rx.cond(
            (~AutomationsState.loading) & (AutomationsState.error == ""),
            rx.cond(
                AutomationsState.filtered_firing_rows.length() > 0,
                _firings_table(),
                rx.cond(
                    AutomationsState.firing_rows.length() == 0,
                    _no_firings_state(),
                    rx.text("No firings match the selected filter.", size="2", color_scheme="gray"),
                ),
            ),
        ),
        spacing="2",
        width="100%",
    )


def _executions_section() -> rx.Component:
    return rx.vstack(
        # Summary badges + title
        rx.hstack(
            rx.text("Action Executions", size="4", weight="medium"),
            rx.spacer(),
            # Awaiting-approval badge — visually prominent when count > 0
            rx.cond(
                AutomationsState.pending_approval_count > 0,
                rx.badge(
                    rx.hstack(
                        rx.box(
                            width="6px",
                            height="6px",
                            border_radius="50%",
                            background=rx.color("amber", 9),
                        ),
                        rx.text(
                            rx.Var.create(f"{AutomationsState.pending_approval_count} awaiting approval"),
                            size="1",
                            weight="bold",
                        ),
                        spacing="1",
                        align="center",
                    ),
                    color_scheme="amber",
                    variant="solid",
                    size="1",
                ),
            ),
            rx.cond(
                AutomationsState.pending_approval_count == 0,
                rx.badge(
                    "no pending approval",
                    color_scheme="green",
                    variant="surface",
                    size="1",
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        # Status filter chips
        rx.cond(
            AutomationsState.available_execution_statuses.length() > 0,
            rx.hstack(
                rx.text("Filter:", size="2", color_scheme="gray"),
                _filter_chip(
                    "All",
                    "all",
                    AutomationsState.execution_status_filter == "all",
                    AutomationsState.set_execution_filter,
                ),
                rx.foreach(
                    AutomationsState.available_execution_statuses,
                    lambda s: _filter_chip(
                        s, s, AutomationsState.execution_status_filter == s, AutomationsState.set_execution_filter
                    ),
                ),
                spacing="1",
                align="center",
                wrap="wrap",
            ),
        ),
        # Table / empty
        rx.cond(
            (~AutomationsState.loading) & (AutomationsState.error == ""),
            rx.cond(
                AutomationsState.filtered_execution_rows.length() > 0,
                _executions_table(),
                rx.cond(
                    AutomationsState.execution_rows.length() == 0,
                    _no_executions_state(),
                    rx.text("No executions match the selected filter.", size="2", color_scheme="gray"),
                ),
            ),
        ),
        spacing="2",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def automations_page() -> rx.Component:
    """Automations page — trigger firings and action executions."""
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                rx.heading("Automations", size="6"),
                rx.spacer(),
                rx.cond(AutomationsState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=AutomationsState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error callout
            rx.cond(
                AutomationsState.error != "",
                error_callout(AutomationsState.error),
            ),
            # Main content
            rx.cond(
                (~AutomationsState.loading) & (AutomationsState.error == ""),
                rx.cond(
                    (AutomationsState.triggers_available | AutomationsState.actions_available),
                    rx.vstack(
                        # Firings section
                        rx.cond(
                            AutomationsState.triggers_available,
                            rx.card(
                                _firings_section(),
                                size="2",
                                width="100%",
                            ),
                        ),
                        # Executions section
                        rx.cond(
                            AutomationsState.actions_available,
                            rx.card(
                                _executions_section(),
                                size="2",
                                width="100%",
                            ),
                        ),
                        spacing="5",
                        width="100%",
                    ),
                    # Neither module installed
                    _empty_state(
                        "zap",
                        "Automations modules not installed",
                        hint="The triggers/actions modules are not present in this schema.",
                    ),
                ),
            ),
            # Detail drawer (shared)
            json_detail_drawer(
                doc_var=AutomationsState.selected_doc,
                json_var=AutomationsState.selected_json,
                iri_var=AutomationsState.selected_iri,
                on_close=AutomationsState.clear_selection,
                open_var=AutomationsState.has_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="automations",
    )
