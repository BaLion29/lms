"""Browse page — introspection-driven class browsing."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.browse import BrowseClassState, BrowseState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.nav import shell


# ── /browse landing page ────────────────────────────────────────────────


def _module_card(name: str, version: str, class_ids: list[str]) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.center(
                rx.icon(tag="box", size=14, color=rx.color("accent", 11)),
                background=rx.color("accent", 3),
                border_radius="8px",
                width="28px",
                height="28px",
            ),
            rx.text(name, size="3", weight="medium"),
            rx.spacer(),
            rx.cond(
                version != "",
                chip(version, "cyan"),
            ),
            spacing="2",
            align="center",
            margin_bottom="2",
        ),
        rx.flex(
            rx.foreach(
                rx.Var.create(class_ids),
                lambda cid: rx.link(
                    rx.badge(cid, variant="surface", color_scheme="cyan", cursor="pointer", size="2"),
                    href=f"/browse/{cid}",
                ),
            ),
            wrap="wrap",
            gap="2",
        ),
        size="2",
        width="100%",
        box_shadow="0 1px 2px rgba(0,0,0,0.04)",
        _hover={"box_shadow": "0 2px 4px rgba(0,0,0,0.06), 0 4px 8px rgba(0,0,0,0.08)"},
        transition="box-shadow 0.2s ease",
    )


def browse_page() -> rx.Component:
    """Browse landing — classes grouped by module."""
    return shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Browse Schema Classes", size="6"),
                rx.spacer(),
                rx.cond(BrowseState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=BrowseState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.cond(
                BrowseState.error != "",
                rx.callout(BrowseState.error, color_scheme="red", size="1"),
            ),
            rx.cond(
                (~BrowseState.loading) & (BrowseState.error == ""),
                rx.cond(
                    BrowseState.groups.length() > 0,
                    # Build module cards dynamically via foreach
                    _module_cards(),
                    rx.text("No browsable classes found in schema.", size="2", color_scheme="gray"),
                ),
            ),
            spacing="5",
            width="100%",
        ),
        active="browse",
    )


def _module_cards() -> rx.Component:
    """Render module cards from BrowseState.groups."""
    # groups is a dict[str, list[str]] — in Reflex we iterate its keys
    # We transform to a list of (name, version, classes) tuples
    group_entries = BrowseState.groups
    return rx.vstack(
        rx.foreach(
            group_entries.keys(),
            lambda key: rx.cond(
                key != "",
                _module_card(
                    key,
                    BrowseState.module_versions[key].to(str),  # type: ignore[index]
                    group_entries[key],  # type: ignore[index]
                ),
            ),
        ),
        spacing="3",
        width="100%",
    )


# ── /browse/[class_name] class page ─────────────────────────────────────


def _pagination_bar() -> rx.Component:
    return rx.hstack(
        rx.text(
            f"Page {BrowseClassState.page_index + 1} of {BrowseClassState.total_pages} "
            f"({BrowseClassState.total_count} total)",
            size="2",
            color_scheme="gray",
        ),
        rx.spacer(),
        rx.hstack(
            rx.icon_button(
                rx.icon(tag="chevron_left", size=16),
                variant="ghost",
                size="1",
                on_click=BrowseClassState.prev_page,
                disabled=BrowseClassState.page_index <= 0,
            ),
            rx.icon_button(
                rx.icon(tag="chevron_right", size=16),
                variant="ghost",
                size="1",
                on_click=BrowseClassState.next_page,
                disabled=BrowseClassState.page_index + 1 >= BrowseClassState.total_pages,
            ),
            spacing="1",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _class_table() -> rx.Component:
    # Build header cells from display_fields
    return rx.vstack(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("@id"),
                    rx.foreach(
                        BrowseClassState.display_fields,
                        lambda f: rx.table.column_header_cell(f),
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
                            ),
                        ),
                        cursor="pointer",
                        _hover={"bg": rx.color("accent", 2)},
                        _odd={"background": rx.color("gray", 2)},
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
                rx.callout(BrowseClassState.error, color_scheme="red", size="1"),
            ),
            # Table with pagination
            rx.cond(
                (~BrowseClassState.loading) & (BrowseClassState.error == "") & (~BrowseClassState.not_found),
                rx.cond(
                    BrowseClassState.paged_rows.length() > 0,
                    rx.card(
                        _class_table(),
                        rx.divider(),
                        rx.cond(
                            BrowseClassState.total_count > 0,
                            _pagination_bar(),
                        ),
                        size="2",
                        width="100%",
                    ),
                    rx.text("No documents found for this class.", size="2", color_scheme="gray"),
                ),
            ),
            # Detail drawer
            json_detail_drawer(
                doc_var=BrowseClassState.selected_doc,
                json_var=BrowseClassState.selected_json,
                iri_var=iri_var,
                on_close=BrowseClassState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="browse",
    )
