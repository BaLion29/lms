"""Relationships browser — triples table with filters, pagination, and detail drawer."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.relationships import RelationshipsState
from firnline_webui.ui.controls import filter_chip, page_size_select, pagination_bar, search_input
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner


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


# ── Table ────────────────────────────────────────────────────────────────


def _triples_table() -> rx.Component:
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


# ── Index errors warning ─────────────────────────────────────────────────


def _index_errors_warning() -> rx.Component:
    """Dismissible warning for per-class fetch errors."""
    return rx.cond(
        (RelationshipsState.index_errors.length() > 0),
        rx.callout(
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="info", size=14, color="var(--amber-9)"),
                    rx.text("Some classes could not be fetched:", size="2"),
                    rx.spacer(),
                    rx.icon_button(
                        rx.icon(tag="x", size=14),
                        variant="ghost",
                        size="1",
                        on_click=RelationshipsState.dismiss_index_errors,
                        custom_attrs={"aria-label": "Dismiss warnings"},
                    ),
                    align="center",
                    spacing="2",
                ),
                rx.text(
                    rx.foreach(
                        RelationshipsState.index_errors,
                        lambda e: rx.text(e, size="1"),
                    ),
                ),
                spacing="1",
            ),
            color_scheme="amber",
            size="1",
            width="100%",
        ),
    )


# ── Detail drawer ────────────────────────────────────────────────────────


def _detail_drawer() -> rx.Component:
    """Own json_detail_drawer bound to RelationshipsState vars."""
    iri_var: rx.Var = rx.Var.create(
        rx.cond(
            RelationshipsState.selected_doc.to(bool)
            & (RelationshipsState.selected_doc["@id"].to(str) != ""),  # type: ignore[index]
            RelationshipsState.selected_doc["@id"].to(str),  # type: ignore[index]
            "",
        )
    )
    return json_detail_drawer(
        doc_var=RelationshipsState.selected_doc,
        json_var=RelationshipsState.selected_json,
        iri_var=iri_var,
        on_close=RelationshipsState.clear_selection,
    )


# ── Main view ────────────────────────────────────────────────────────────


def relationships_view() -> rx.Component:
    """Render the relationships browser with filters, table, pagination, and states."""
    return rx.vstack(
        # ── Loading spinner ───────────────────────────────────────
        rx.cond(
            RelationshipsState.loading,
            loading_spinner(),
        ),
        # ── Error ─────────────────────────────────────────────────
        rx.cond(
            (RelationshipsState.error != ""),
            rx.vstack(
                error_callout(RelationshipsState.error),
                rx.button(
                    "Retry",
                    on_click=RelationshipsState.refresh,
                    size="1",
                    variant="soft",
                ),
                spacing="2",
            ),
        ),
        # ── Index errors ──────────────────────────────────────────
        _index_errors_warning(),
        # ── Toolbar ───────────────────────────────────────────────
        rx.cond(
            RelationshipsState.loaded,
            _toolbar(),
        ),
        # ── Empty state: nothing loaded at all ────────────────────
        rx.cond(
            (~RelationshipsState.loading)
            & (RelationshipsState.error == "")
            & RelationshipsState.loaded
            & (RelationshipsState.total_count == 0)
            & (RelationshipsState.active_predicates.length() == 0)
            & (RelationshipsState.active_source_types.length() == 0)
            & (RelationshipsState.active_target_types.length() == 0)
            & (RelationshipsState.search_text == ""),
            empty_state(
                "git-compare-arrows",
                "No relationships found",
                "No edges were extracted from the schema documents.",
            ),
        ),
        # ── No matches (active filters, zero results) ─────────────
        rx.cond(
            (~RelationshipsState.loading)
            & (RelationshipsState.error == "")
            & RelationshipsState.loaded
            & (RelationshipsState.total_count == 0)
            & (
                (RelationshipsState.active_predicates.length() > 0)
                | (RelationshipsState.active_source_types.length() > 0)
                | (RelationshipsState.active_target_types.length() > 0)
                | (RelationshipsState.search_text != "")
            ),
            rx.center(
                rx.vstack(
                    rx.icon(tag="search_x", size=32, color=rx.color("gray", 7)),
                    rx.text("No matching relationships.", size="3", weight="medium"),
                    rx.text("Try adjusting your filters.", size="2", color_scheme="gray"),
                    rx.button(
                        "Clear all filters",
                        on_click=[
                            RelationshipsState.set_search(""),
                            RelationshipsState.refresh,
                        ],
                        size="2",
                        variant="outline",
                    ),
                    spacing="3",
                    align="center",
                ),
                width="100%",
                padding_y="64px",
            ),
        ),
        # ── Table + pagination ────────────────────────────────────
        rx.cond(
            (~RelationshipsState.loading)
            & (RelationshipsState.error == "")
            & RelationshipsState.loaded
            & (RelationshipsState.total_count > 0),
            rx.vstack(
                _triples_table(),
                _pagination(),
                spacing="3",
                width="100%",
            ),
        ),
        # ── Detail drawer ─────────────────────────────────────────
        _detail_drawer(),
        spacing="3",
        width="100%",
    )
