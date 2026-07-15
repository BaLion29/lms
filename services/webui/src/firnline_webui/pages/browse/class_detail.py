"""/browse/[class_name] class detail page with sortable paginated table."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.browse import BrowseClassState
from firnline_webui.ui.controls import page_size_select, pagination_bar, search_input, sortable_header_cell
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner
from firnline_webui.ui.nav import shell


def _class_table() -> rx.Component:
    return rx.vstack(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("@id"),
                    rx.foreach(
                        BrowseClassState.display_fields,
                        lambda f: sortable_header_cell(
                            label=f.to(str),
                            field=f.to(str),
                            sort_field=BrowseClassState.sort_field,
                            sort_dir=BrowseClassState.sort_dir,
                            on_sort=BrowseClassState.set_sort,
                        ),
                    ),
                ),
            ),
            rx.table.body(
                rx.foreach(
                    BrowseClassState.paged_rows,
                    lambda row: rx.table.row(
                        rx.table.cell(
                            rx.text(
                                row["@id"].to(str),  # type: ignore[index]
                                size="1",
                                color_scheme="gray",
                                font_family="mono",
                            ),
                        ),
                        rx.foreach(
                            BrowseClassState.display_fields,
                            lambda field: rx.table.cell(
                                rx.text(
                                    row[field].to(str),  # type: ignore[index]
                                    size="2",
                                    max_width="250px",
                                    overflow="hidden",
                                    text_overflow="ellipsis",
                                    white_space="nowrap",
                                ),
                                title=row[field].to(str),  # type: ignore[index]
                            ),
                        ),
                        cursor="pointer",
                        _hover={"bg": rx.color("accent", 2)},
                        _odd={"background": rx.color("gray", 2)},
                        tab_index=0,
                        role="button",
                        on_click=BrowseClassState.select(row["@id"]),  # type: ignore[index]
                    ),
                ),
            ),
            variant="surface",
            size="2",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def browse_class_page() -> rx.Component:
    """Class detail page for /browse/[class_name]."""
    iri_var: rx.Var = rx.Var.create(
        rx.cond(
            BrowseClassState.selected_doc.to(bool) & (BrowseClassState.selected_doc["@id"].to(str) != ""),  # type: ignore[index]
            BrowseClassState.selected_doc["@id"].to(str),  # type: ignore[index]
            "",
        )
    )
    return shell(
        rx.vstack(
            # Header
            rx.hstack(
                rx.hstack(
                    rx.link(
                        rx.icon_button(
                            rx.icon(tag="arrow_left", size=16),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            custom_attrs={"aria-label": "Back to browse"},
                        ),
                        href="/browse",
                    ),
                    rx.heading(
                        rx.cond(
                            BrowseClassState.current_class_name != "",
                            BrowseClassState.current_class_name,
                            "Browse",
                        ),
                        size="6",
                    ),
                    # Total count badge in header
                    rx.cond(
                        BrowseClassState.total_count > 0,
                        rx.badge(
                            rx.text(
                                BrowseClassState.total_count.to(str),
                                rx.text(" docs", size="1"),
                                size="1",
                            ),
                            variant="surface",
                            color_scheme="gray",
                        ),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.spacer(),
                rx.cond(BrowseClassState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=BrowseClassState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error / not found
            rx.cond(
                BrowseClassState.not_found,
                rx.callout(
                    rx.vstack(
                        rx.text(f"Class '{BrowseClassState.current_class_name}' not found.", weight="medium"),
                        rx.link("Back to Browse", href="/browse", size="1"),
                        spacing="1",
                    ),
                    color_scheme="red",
                    size="1",
                    width="100%",
                ),
            ),
            rx.cond(
                (BrowseClassState.error != "") & (~BrowseClassState.not_found),
                rx.vstack(
                    error_callout(BrowseClassState.error),
                    rx.button(
                        rx.icon(tag="refresh_cw", size=14),
                        "Retry",
                        variant="outline",
                        size="1",
                        on_click=BrowseClassState.load,
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            # Loading spinner (while loading and no cached data)
            rx.cond(
                BrowseClassState.loading & (BrowseClassState.total_count == 0) & (~BrowseClassState.not_found) & (BrowseClassState.error == ""),
                loading_spinner(),
            ),
            # Main content area
            rx.cond(
                (~BrowseClassState.loading) & (BrowseClassState.error == "") & (~BrowseClassState.not_found),
                rx.cond(
                    # Have data to show (either from server page or hybrid all_rows)
                    (BrowseClassState.total_count > 0),
                    rx.vstack(
                        # Search input (only useful in hybrid mode; shown but with hint in server mode)
                        rx.cond(
                            BrowseClassState.use_server_pagination,
                            rx.hstack(
                                search_input(
                                    value=BrowseClassState.search_text,
                                    on_change=BrowseClassState.set_search,
                                    placeholder="Search…",
                                    disabled=True,
                                    width="300px",
                                ),
                                rx.text(
                                    "Search disabled — dataset too large for client-side filtering",
                                    size="1",
                                    color_scheme="gray",
                                ),
                                spacing="2",
                                align="center",
                            ),
                            search_input(
                                value=BrowseClassState.search_text,
                                on_change=BrowseClassState.set_search,
                                placeholder="Search…",
                                width="300px",
                            ),
                        ),
                        rx.card(
                            _class_table(),
                            rx.divider(),
                            # Pagination with page-size select as extra
                            pagination_bar(
                                page=BrowseClassState.page_index,
                                total_pages=BrowseClassState.total_pages,
                                total_count=BrowseClassState.effective_count,
                                on_prev=BrowseClassState.prev_page,
                                on_next=BrowseClassState.next_page,
                                extra=page_size_select(
                                    value=BrowseClassState.page_size,
                                    on_change=BrowseClassState.set_page_size,
                                    options=(10, 25, 50, 100),
                                ),
                            ),
                            size="2",
                            width="100%",
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    # Zero total_count: true empty state
                    empty_state(
                        "database",
                        "No documents found",
                        hint="This class exists in the schema but has no documents.",
                    ),
                ),
            ),
            # "No matches" for hybrid mode when search filters out everything
            rx.cond(
                (~BrowseClassState.loading)
                & (BrowseClassState.error == "")
                & (~BrowseClassState.not_found)
                & (BrowseClassState.total_count > 0)
                & (BrowseClassState.effective_count == 0),
                empty_state(
                    "search",
                    "No matching documents",
                    hint="Try a different search term.",
                ),
            ),
            # Detail drawer with references
            json_detail_drawer(
                doc_var=BrowseClassState.selected_doc,
                json_var=BrowseClassState.selected_json,
                iri_var=iri_var,
                on_close=BrowseClassState.clear_selection,
                references=BrowseClassState.references,
                on_navigate=BrowseClassState.navigate_to_reference,
            ),
            spacing="5",
            width="100%",
        ),
        active="browse",
    )
