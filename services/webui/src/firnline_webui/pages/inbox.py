"""Inbox page — introspection-driven inbox view."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.inbox import InboxState
from firnline_webui.ui.cards import status_badge
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout
from firnline_webui.ui.nav import shell
from firnline_webui.ui.theme import TABLE_ROW_STYLE
from firnline_webui.ui.typography import page_heading

_INBOX_STATUS_COLORS: dict[str, str] = {
    "new": "blue",
    "processed": "green",
    "done": "green",
    "transcribed": "green",
    "failed": "red",
    "archived": "gray",
}


def _filter_chip(label: str, value: str, is_active: rx.Var[bool]) -> rx.Component:
    return rx.badge(
        rx.hstack(
            rx.text(label, size="1"),
            rx.cond(is_active, rx.icon(tag="check", size=12)),
            spacing="1",
        ),
        variant=rx.cond(is_active, "solid", "soft"),
        color_scheme="cyan",
        cursor="pointer",
        on_click=InboxState.set_status_filter(value),
    )


def _inbox_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Type"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell("Captured"),
                rx.table.column_header_cell("Preview"),
            ),
        ),
        rx.table.body(
            rx.foreach(
                InboxState.filtered_rows,
                lambda row: rx.table.row(
                    rx.table.cell(rx.text(row["content_type"], size="2", color_scheme="gray")),
                    rx.table.cell(status_badge(row["status"], _INBOX_STATUS_COLORS)),
                    rx.table.cell(rx.text(row["captured_at"], size="2")),
                    rx.table.cell(
                        rx.text(
                            row["preview"],
                            size="2",
                            color_scheme="gray",
                            max_width="400px",
                            overflow="hidden",
                            text_overflow="ellipsis",
                            white_space="nowrap",
                        ),
                        title=row["preview"].to(str),
                    ),
                    cursor="pointer",
                    **TABLE_ROW_STYLE,
                    tab_index=0,
                    role="button",
                    on_click=InboxState.select(row["id"]),
                ),
            ),
        ),
        variant="surface",
        size="3",
        width="100%",
    )


def inbox_page() -> rx.Component:
    """Inbox page."""
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                page_heading("Inbox"),
                rx.spacer(),
                rx.cond(InboxState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=InboxState.load,
                    size="2",
                    variant="soft",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error
            rx.cond(
                InboxState.error != "",
                error_callout(InboxState.error),
            ),
            # Status filter chips + table in a card
            rx.card(
                rx.vstack(
                    rx.cond(
                        InboxState.available_statuses.length() > 0,
                        rx.hstack(
                            rx.text("Filter:", size="2", color_scheme="gray"),
                            _filter_chip("All", "all", InboxState.status_filter == "all"),
                            rx.foreach(
                                InboxState.available_statuses,
                                lambda s: _filter_chip(s, s, InboxState.status_filter == s),
                            ),
                            spacing="1",
                            align="center",
                            wrap="wrap",
                        ),
                    ),
                    # Table / empty
                    rx.cond(
                        (~InboxState.loading) & (InboxState.error == ""),
                        rx.cond(
                            InboxState.filtered_rows.length() > 0,
                            _inbox_table(),
                            rx.cond(
                                InboxState.rows.length() == 0,
                                empty_state(
                                    "inbox",
                                    "No captured items found.",
                                    hint="Captured items from the capture pipeline appear here.",
                                    show_card=True,
                                ),
                                rx.text("No items match the selected filter.", size="2", color_scheme="gray"),
                            ),
                        ),
                    ),
                    spacing="4",
                    width="100%",
                ),
                size="2",
                width="100%",
            ),
            # Detail drawer (portal, placed at the end of content)
            json_detail_drawer(
                doc_var=InboxState.selected_doc,
                json_var=InboxState.selected_json,
                iri_var=iri_var(InboxState.selected_doc),
                on_close=InboxState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="inbox",
    )
