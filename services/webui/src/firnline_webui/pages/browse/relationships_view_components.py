"""Relationships browser UI components — filter chips, toolbar, triples table, pagination."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.relationships import RelationshipsState
from firnline_webui.ui.controls import filter_chip, page_size_select, pagination_bar, search_input
from firnline_webui.ui.theme import TABLE_ROW_STYLE


# ── Chip filter groups ────────────────────────────────────────────────────


def _predicate_chips() -> rx.Component:
    """Row of predicate filter chips."""
    return rx.flex(
        rx.cond(
            RelationshipsState.predicate_options.length() > 0,
            rx.foreach(
                rx.Var.create(RelationshipsState.predicate_options),
                lambda item: filter_chip(
                    label=item["label"].to(str) + " · " + item["count"].to(str),
                    selected=RelationshipsState.active_predicates.contains(item["label"]),
                    on_click=RelationshipsState.toggle_predicate(item["label"]),
                ),
            ),
        ),
        wrap="wrap",
        gap="1",
        width="100%",
    )


def _source_type_chips() -> rx.Component:
    """Row of source-type filter chips."""
    return rx.flex(
        rx.cond(
            RelationshipsState.source_type_options.length() > 0,
            rx.foreach(
                rx.Var.create(RelationshipsState.source_type_options),
                lambda item: filter_chip(
                    label=item["label"].to(str) + " · " + item["count"].to(str),
                    selected=RelationshipsState.active_source_types.contains(item["label"]),
                    on_click=RelationshipsState.toggle_source_type(item["label"]),
                ),
            ),
        ),
        wrap="wrap",
        gap="1",
        width="100%",
    )


def _target_type_chips() -> rx.Component:
    """Row of target-type filter chips."""
    return rx.flex(
        rx.cond(
            RelationshipsState.target_type_options.length() > 0,
            rx.foreach(
                rx.Var.create(RelationshipsState.target_type_options),
                lambda item: filter_chip(
                    label=item["label"].to(str) + " · " + item["count"].to(str),
                    selected=RelationshipsState.active_target_types.contains(item["label"]),
                    on_click=RelationshipsState.toggle_target_type(item["label"]),
                ),
            ),
        ),
        wrap="wrap",
        gap="1",
        width="100%",
    )


# ── Filter toolbar ───────────────────────────────────────────────────────


def _toolbar() -> rx.Component:
    """Search input + three labelled chip groups."""
    return rx.vstack(
        search_input(
            value=RelationshipsState.search_text,
            on_change=RelationshipsState.set_search,
            placeholder="Search source or target…",
        ),
        rx.cond(
            RelationshipsState.predicate_options.length() > 0,
            rx.vstack(
                rx.text("Predicates", size="1", color_scheme="gray"),
                _predicate_chips(),
                spacing="1",
                width="100%",
            ),
        ),
        rx.cond(
            RelationshipsState.source_type_options.length() > 0,
            rx.vstack(
                rx.text("Source type", size="1", color_scheme="gray"),
                _source_type_chips(),
                spacing="1",
                width="100%",
            ),
        ),
        rx.cond(
            RelationshipsState.target_type_options.length() > 0,
            rx.vstack(
                rx.text("Target type", size="1", color_scheme="gray"),
                _target_type_chips(),
                spacing="1",
                width="100%",
            ),
        ),
        spacing="2",
        width="100%",
    )


# ── Triples table ────────────────────────────────────────────────────────


def triples_table() -> rx.Component:
    """Scrollable table of triple rows."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell(
                    rx.text("Source", size="2", weight="medium"),
                ),
                rx.table.column_header_cell(
                    rx.text("Predicate", size="2", weight="medium"),
                ),
                rx.table.column_header_cell(
                    rx.text("Target", size="2", weight="medium"),
                ),
                rx.table.column_header_cell(""),
            ),
        ),
        rx.table.body(
            rx.foreach(
                rx.Var.create(RelationshipsState.rows),
                lambda row: rx.table.row(
                    rx.table.cell(
                        rx.hstack(
                            rx.text(
                                row["source_label"].to(str),
                                size="2",
                                cursor="pointer",
                                on_click=RelationshipsState.select_endpoint(row["source_id"]),
                                _hover={"color": rx.color("accent", 9)},
                            ),
                            rx.badge(
                                row["source_type"].to(str),
                                variant="surface",
                                color_scheme="cyan",
                                size="1",
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.table.cell(
                        rx.code(
                            row["prop"].to(str),
                            variant="ghost",
                            color_scheme="cyan",
                        ),
                    ),
                    rx.table.cell(
                        rx.hstack(
                            rx.text(
                                row["target_label"].to(str),
                                size="2",
                                cursor="pointer",
                                on_click=RelationshipsState.select_endpoint(row["target_id"]),
                                _hover={"color": rx.color("accent", 9)},
                            ),
                            rx.badge(
                                row["target_type"].to(str),
                                variant="surface",
                                color_scheme="cyan",
                                size="1",
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.table.cell(
                        rx.icon_button(
                            rx.icon(tag="focus", size=14),
                            variant="ghost",
                            size="1",
                            color_scheme="cyan",
                            on_click=RelationshipsState.show_in_graph(row["source_id"]),
                            custom_attrs={"aria-label": "Show in graph"},
                        ),
                    ),
                    align="center",
                    **TABLE_ROW_STYLE,
                ),
            ),
        ),
        variant="surface",
        size="1",
        width="100%",
    )


# ── Pagination ───────────────────────────────────────────────────────────


def _pagination() -> rx.Component:
    """Pagination bar with page-size selector."""
    return pagination_bar(
        page=RelationshipsState.page,
        total_pages=RelationshipsState.total_pages,
        total_count=RelationshipsState.total_count,
        on_prev=RelationshipsState.prev_page,
        on_next=RelationshipsState.next_page,
        extra=page_size_select(
            value=RelationshipsState.page_size,
            on_change=RelationshipsState.set_page_size,
        ),
    )
