"""History page — commit log browsing."""

from __future__ import annotations

import reflex as rx

from firnline_webui.pages.history_components import commit_detail_dialog, commit_table
from firnline_webui.state.history import HistoryState
from firnline_webui.ui.controls import pagination_bar
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner
from firnline_webui.ui.nav import shell
from firnline_webui.ui.typography import page_heading


def history_page() -> rx.Component:
    """Commit history page."""
    return shell(
        rx.vstack(
            # Header
            rx.hstack(
                page_heading("History"),
                rx.spacer(),
                rx.cond(HistoryState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=HistoryState.load,
                    size="2",
                    variant="soft",
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
                            commit_table(),
                            rx.divider(),
                            rx.cond(
                                HistoryState.total_count > 0,
                                pagination_bar(
                                    page=HistoryState.page_index,
                                    total_pages=HistoryState.total_pages,
                                    total_count=HistoryState.total_count,
                                    on_prev=HistoryState.prev_page,
                                    on_next=HistoryState.next_page,
                                ),
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
            commit_detail_dialog(),
            # Document detail drawer
            json_detail_drawer(
                doc_var=HistoryState.selected_doc,
                json_var=HistoryState.selected_json,
                iri_var=iri_var(HistoryState.selected_doc),
                on_close=HistoryState.clear_document,
            ),
            spacing="5",
            width="100%",
        ),
        active="history",
    )
