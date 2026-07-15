"""History page — commit log browsing."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.history import HistoryState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner
from firnline_webui.ui.nav import shell, page_header


# ── Pagination bar ────────────────────────────────────────────────────


def _pagination_bar() -> rx.Component:
    return rx.hstack(
        rx.text(
            f"Page {HistoryState.page_index + 1} of {HistoryState.total_pages} "
            f"({HistoryState.total_count} total)",
            size="2",
            color_scheme="gray",
        ),
        rx.spacer(),
        rx.hstack(
            rx.icon_button(
                rx.icon(tag="chevron_left", size=16),
                variant="ghost",
                size="1",
                on_click=HistoryState.prev_page,
                disabled=HistoryState.page_index <= 0,
                custom_attrs={"aria-label": "Previous page"},
            ),
            rx.icon_button(
                rx.icon(tag="chevron_right", size=16),
                variant="ghost",
                size="1",
                on_click=HistoryState.next_page,
                disabled=HistoryState.page_index + 1 >= HistoryState.total_pages,
                custom_attrs={"aria-label": "Next page"},
            ),
            spacing="1",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


# ── Commit table ──────────────────────────────────────────────────────


def _commit_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Commit"),
                rx.table.column_header_cell("Message"),
                rx.table.column_header_cell("Author"),
                rx.table.column_header_cell("When"),
            ),
        ),
        rx.table.body(
            rx.foreach(
                HistoryState.paged_rows,
                lambda row: rx.table.row(
                    rx.table.cell(
                        rx.text(
                            row["short_id"].to(str),  # type: ignore[index]
                            size="1",
                            font_family="mono",
                            color_scheme="gray",
                        ),
                    ),
                    rx.table.cell(
                        rx.text(
                            row["message"].to(str),  # type: ignore[index]
                            size="2",
                            max_width="400px",
                            overflow="hidden",
                            text_overflow="ellipsis",
                            white_space="nowrap",
                        ),
                        title=row["message"].to(str),  # type: ignore[index]
                    ),
                    rx.table.cell(
                        rx.text(
                            row["author"].to(str),  # type: ignore[index]
                            size="2",
                            color_scheme="gray",
                        ),
                    ),
                    rx.table.cell(
                        rx.text(
                            row["timestamp_fmt"].to(str),  # type: ignore[index]
                            size="2",
                            color_scheme="gray",
                        ),
                    ),
                    cursor="pointer",
                    _hover={"bg": rx.color("accent", 2)},
                    _odd={"background": rx.color("gray", 2)},
                    tab_index=0,
                    role="button",
                    on_click=HistoryState.select_commit(row["id"]),  # type: ignore[index]
                ),
            ),
        ),
        variant="surface",
        size="2",
        width="100%",
    )


# ── Commit detail dialog ──────────────────────────────────────────────


def _commit_detail_dialog() -> rx.Component:
    """Dialog showing commit metadata and changed document lists."""
    is_open: rx.Var = rx.Var.create(
        (HistoryState.selected_commit_id != "")
        & (HistoryState.selected_commit.to(bool))
    )
    return rx.dialog.root(
        rx.dialog.content(
            # Title
            rx.dialog.title(
                rx.hstack(
                    rx.box(
                        rx.icon(tag="git_commit", size=14, color=rx.color("accent", 11)),
                        background=rx.color("accent", 3),
                        border_radius="6px",
                        width="26px",
                        height="26px",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    ),
                    rx.text("Commit Detail", size="4"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.icon_button(
                            rx.icon(tag="x", size=16),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            on_click=HistoryState.close_commit_detail,
                            custom_attrs={"aria-label": "Close commit detail"},
                        ),
                    ),
                    align="center",
                ),
            ),
            # Commit metadata
            rx.cond(
                HistoryState.selected_commit.to(bool),
                rx.vstack(
                    # Commit ID
                    rx.hstack(
                        rx.text("ID", size="1", color_scheme="gray", weight="medium"),
                        rx.text(
                            HistoryState.selected_commit["id"].to(str),  # type: ignore[index]
                            size="1",
                            font_family="mono",
                            word_break="break-all",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    # Author
                    rx.hstack(
                        rx.text("Author", size="1", color_scheme="gray", weight="medium"),
                        rx.text(
                            HistoryState.selected_commit["author"].to(str),  # type: ignore[index]
                            size="2",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    # Timestamp
                    rx.hstack(
                        rx.text("When", size="1", color_scheme="gray", weight="medium"),
                        rx.text(
                            HistoryState.selected_commit["timestamp_fmt"].to(str),  # type: ignore[index]
                            size="2",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    # Message
                    rx.hstack(
                        rx.text("Message", size="1", color_scheme="gray", weight="medium"),
                        rx.text(
                            HistoryState.selected_commit["message"].to(str),  # type: ignore[index]
                            size="2",
                        ),
                        spacing="2",
                        align="start",
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                    margin_bottom="16px",
                ),
            ),
            rx.divider(),
            # Changes loading
            rx.cond(
                HistoryState.changes_loading,
                rx.center(rx.spinner(size="3"), padding="24px", width="100%"),
            ),
            # Changes error
            rx.cond(
                (HistoryState.changes_error != "") & (~HistoryState.changes_loading),
                error_callout(HistoryState.changes_error),
            ),
            # Changes sections
            rx.cond(
                (~HistoryState.changes_loading) & (HistoryState.changes_error == ""),
                rx.vstack(
                    # Inserted
                    _change_section(
                        "Inserted",
                        "green",
                        "plus_circle",
                        HistoryState.inserted,
                    ),
                    # Updated
                    _change_section(
                        "Updated",
                        "blue",
                        "edit",
                        HistoryState.updated,
                    ),
                    # Deleted
                    _change_section(
                        "Deleted",
                        "red",
                        "trash_2",
                        HistoryState.deleted,
                    ),
                    spacing="4",
                    width="100%",
                    margin_top="12px",
                ),
            ),
            # Footer
            rx.hstack(
                rx.spacer(),
                rx.dialog.close(
                    rx.button(
                        "Close",
                        variant="outline",
                        size="1",
                        on_click=HistoryState.close_commit_detail,
                    ),
                ),
                width="100%",
                justify="end",
                spacing="2",
                padding_top="12px",
            ),
            max_width="720px",
            max_height="85vh",
            overflow_y="auto",
        ),
        open=is_open,
        on_open_change=HistoryState.close_commit_detail,
    )


def _change_section(
    label: str,
    color_scheme: str,
    icon_tag: str,
    ids_var: rx.Var[list[str]],
) -> rx.Component:
    """Render a section for inserted/updated/deleted document ids."""
    return rx.vstack(
        rx.hstack(
            rx.icon(tag=icon_tag, size=14, color=rx.color(color_scheme, 9)),
            rx.text(label, size="2", weight="medium"),
            chip(
                ids_var.length().to_string(),  # type: ignore[attr-defined]
                color_scheme=color_scheme,
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        rx.cond(
            ids_var.length() > 0,  # type: ignore[attr-defined]
            rx.vstack(
                rx.foreach(
                    ids_var,
                    lambda doc_id: rx.hstack(
                        rx.text(
                            doc_id.to(str),
                            size="1",
                            font_family="mono",
                            word_break="break-all",
                            color=rx.color("accent", 11),
                        ),
                        cursor="pointer",
                        _hover={"opacity": 0.7},
                        on_click=HistoryState.open_document(doc_id),
                    ),
                ),
                spacing="1",
                width="100%",
            ),
            rx.text(
                "No " + label.lower() + " documents.",
                size="1",
                color_scheme="gray",
            ),
        ),
        spacing="2",
        width="100%",
    )


# ── Page ──────────────────────────────────────────────────────────────


def history_page() -> rx.Component:
    """Commit history page."""
    iri_var: rx.Var = rx.Var.create(
        rx.cond(
            HistoryState.selected_doc.to(bool)
            & (HistoryState.selected_doc["@id"].to(str) != ""),  # type: ignore[index]
            HistoryState.selected_doc["@id"].to(str),  # type: ignore[index]
            "",
        )
    )
    return shell(
        rx.vstack(
            # Header
            rx.hstack(
                rx.heading("History", size="6"),
                rx.spacer(),
                rx.cond(HistoryState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=HistoryState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error
            rx.cond(
                HistoryState.error != "",
                error_callout(HistoryState.error),
            ),
            # Content
            rx.cond(
                HistoryState.loading,
                loading_spinner(),
                rx.cond(
                    HistoryState.error != "",
                    rx.text(""),
                    rx.cond(
                        HistoryState.rows.length() > 0,
                        rx.card(
                            _commit_table(),
                            rx.divider(),
                            rx.cond(
                                HistoryState.total_count > 0,
                                _pagination_bar(),
                            ),
                            size="2",
                            width="100%",
                        ),
                        empty_state(
                            "git_commit",
                            "No commits found.",
                            "Commit history will appear here once changes are made.",
                        ),
                    ),
                ),
            ),
            # Commit detail dialog
            _commit_detail_dialog(),
            # Document detail drawer
            json_detail_drawer(
                doc_var=HistoryState.selected_doc,
                json_var=HistoryState.selected_json,
                iri_var=iri_var,
                on_close=HistoryState.clear_document,
            ),
            spacing="5",
            width="100%",
        ),
        active="history",
    )
