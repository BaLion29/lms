"""Inbox page — introspection-driven inbox view."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.inbox import InboxState
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.nav import shell


def _status_badge(status: str) -> rx.Component:
    """Color-coded status badge."""
    color_map = {
        "new": "blue",
        "processed": "green",
        "done": "green",
        "transcribed": "green",
        "failed": "red",
        "archived": "gray",
    }
    cs = color_map.get(status, "gray")
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
                rx.table.column_header_cell("Class"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell("Created"),
                rx.table.column_header_cell("Preview"),
            ),
        ),
        rx.table.body(
            rx.foreach(
                InboxState.filtered_rows,
                lambda row: rx.table.row(
                    rx.table.cell(rx.text(row["class"], size="2", weight="medium")),
                    rx.table.cell(_status_badge(row["status"])),
                    rx.table.cell(rx.text(row["created_at"], size="2")),
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
                    ),
                    cursor="pointer",
                    _hover={"bg": rx.color("accent", 2)},
                    _odd={"background": rx.color("gray", 2)},
                    on_click=InboxState.select(row["id"]),
                ),
            ),
        ),
        variant="surface",
        size="3",
        width="100%",
    )


def _empty_state() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.icon(tag="inbox", size=32, color=rx.color("gray", 7)),
            rx.text("No inbox classes found.", size="3", weight="medium"),
            rx.text(
                "Install an inbox-capable extension to see captured items here.",
                size="2",
                color_scheme="gray",
            ),
            spacing="3",
            align="center",
            padding="32px",
        ),
        size="2",
        width="100%",
    )


def inbox_page() -> rx.Component:
    """Inbox page."""
    iri_var: rx.Var = rx.Var.create(
        rx.cond(
            InboxState.selected_doc.to(bool) & (InboxState.selected_doc["@id"].to(str) != ""),  # type: ignore[index]
            InboxState.selected_doc["@id"].to(str),  # type: ignore[index]
            "",
        )
    )
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                rx.heading("Inbox", size="6"),
                rx.spacer(),
                rx.cond(InboxState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=InboxState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error
            rx.cond(
                InboxState.error != "",
                rx.callout(InboxState.error, color_scheme="red", size="1"),
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
                                _empty_state(),
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
                iri_var=iri_var,
                on_close=InboxState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="inbox",
    )
