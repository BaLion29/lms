"""Automations page UI components — tables, filter chips, section builders."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.automations import AutomationsState
from firnline_webui.ui.cards import status_badge
from firnline_webui.ui.feedback import empty_state as _empty_state
from firnline_webui.ui.theme import TABLE_ROW_STYLE


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
    return status_badge(status, _FIRING_STATUS_COLORS)


def _execution_status_badge(status: str) -> rx.Component:
    return status_badge(status, _EXECUTION_STATUS_COLORS)


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
                    **TABLE_ROW_STYLE,
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
                    **TABLE_ROW_STYLE,
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
# Section builders
# ---------------------------------------------------------------------------


def firings_section() -> rx.Component:
    """Firings card content — title bar, filter chips, table."""
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
                    _empty_state("zap", "No trigger firings found."),
                    rx.text("No firings match the selected filter.", size="2", color_scheme="gray"),
                ),
            ),
        ),
        spacing="2",
        width="100%",
    )


def executions_section() -> rx.Component:
    """Executions card content — title bar, filter chips, table."""
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
                    _empty_state("zap", "No action executions found."),
                    rx.text("No executions match the selected filter.", size="2", color_scheme="gray"),
                ),
            ),
        ),
        spacing="2",
        width="100%",
    )
