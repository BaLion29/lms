"""Relationships browser — triples table with filters, pagination, and detail drawer."""

from __future__ import annotations

import reflex as rx

from firnline_webui.pages.browse.relationships_view_components import _pagination, _toolbar, triples_table
from firnline_webui.state.relationships import RelationshipsState
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner
from firnline_webui.ui.theme import SPACING_EMPTY_STATE_Y


# ── Index errors warning ─────────────────────────────────────────────────


def _index_errors_warning() -> rx.Component:
    """Dismissible warning for per-class fetch errors."""
    return rx.cond(
        (RelationshipsState.index_errors.length() > 0),
        rx.callout(
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="info", size=14, color=rx.color("amber", 9)),
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
    return json_detail_drawer(
        doc_var=RelationshipsState.selected_doc,
        json_var=RelationshipsState.selected_json,
        iri_var=iri_var(RelationshipsState.selected_doc),
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
                        variant="soft",
                    ),
                    spacing="3",
                    align="center",
                ),
                width="100%",
                padding_y=SPACING_EMPTY_STATE_Y,
            ),
        ),
        # ── Table + pagination ────────────────────────────────────
        rx.cond(
            (~RelationshipsState.loading)
            & (RelationshipsState.error == "")
            & RelationshipsState.loaded
            & (RelationshipsState.total_count > 0),
            rx.vstack(
                triples_table(),
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
