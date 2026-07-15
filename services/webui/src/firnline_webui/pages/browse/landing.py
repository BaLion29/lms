"""/browse landing page — tabbed browse hub (Classes / Graph / Relationships)."""

from __future__ import annotations

import reflex as rx

from firnline_webui.pages.browse.graph_view import graph_view
from firnline_webui.pages.browse.relationships_view import relationships_view
from firnline_webui.state.browse import BrowseState
from firnline_webui.state.graph import GraphState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.controls import search_input
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner
from firnline_webui.ui.nav import shell
from firnline_webui.ui.theme import RADIUS_MEDIUM, SHADOW_CARD, SHADOW_CARD_HOVER, SPACING_EMPTY_STATE_Y
from firnline_webui.ui.typography import page_heading


def _module_card(name: str, version: str, class_ids: list[str]) -> rx.Component:
    """Render a single module card with class badges and per-class counts."""
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
            margin_bottom="8px",
        ),
        rx.flex(
            rx.foreach(
                rx.Var.create(class_ids),
                lambda cid: rx.link(
                    rx.hstack(
                        rx.badge(cid, variant="surface", color_scheme="cyan", cursor="pointer", size="2"),
                        rx.cond(
                            BrowseState.class_counts[cid].to(str) != "",  # type: ignore[index]
                            rx.badge(
                                BrowseState.class_counts[cid].to(str),  # type: ignore[index]
                                variant="outline",
                                color_scheme="gray",
                                size="1",
                            ),
                        ),
                        spacing="1",
                    ),
                    href=f"/browse/{cid}",
                ),
            ),
            wrap="wrap",
            gap="2",
        ),
        # Class count caption
        rx.text(
            rx.Var.create(class_ids).length().to_string() + " class",
            size="1",
            color_scheme="gray",
        ),
        size="2",
        width="100%",
        border=f"1px solid {rx.color('gray', 4)}",
        border_radius=RADIUS_MEDIUM,
        box_shadow=SHADOW_CARD,
        _hover={"box_shadow": SHADOW_CARD_HOVER},
        transition="box-shadow 0.2s ease",
    )


def _module_cards() -> rx.Component:
    """Render module cards from BrowseState.filtered_groups / filtered_module_keys."""
    return rx.vstack(
        rx.foreach(
            BrowseState.filtered_module_keys,
            lambda key: _module_card(
                key,
                BrowseState.module_versions[key].to(str),  # type: ignore[index]
                BrowseState.filtered_groups[key],  # type: ignore[index]
            ),
        ),
        spacing="3",
        width="100%",
    )


def _classes_tab() -> rx.Component:
    """Classes tab: search bar + module cards with counts."""
    return rx.vstack(
        # Toolbar: search + refresh + counts spinner
        rx.hstack(
            search_input(
                value=BrowseState.search_query,
                on_change=BrowseState.set_search,
                placeholder="Filter classes…",
                width="320px",
            ),
            rx.spacer(),
            rx.cond(BrowseState.counts_loading, rx.spinner(size="3")),
            rx.button(
                rx.icon(tag="refresh_cw", size=16),
                "Refresh",
                on_click=BrowseState.load,
                size="2",
                variant="soft",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        # Error
        rx.cond(
            BrowseState.error != "",
            rx.callout(
                rx.hstack(
                    rx.icon(tag="triangle_alert", size=14, color=rx.color("red", 9)),
                    rx.text(BrowseState.error, size="2"),
                    rx.button(
                        "Retry",
                        on_click=BrowseState.load,
                        size="1",
                        variant="soft",
                    ),
                    align="center",
                    spacing="2",
                    width="100%",
                ),
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Loading
        rx.cond(
            BrowseState.loading,
            loading_spinner(),
        ),
        # Main content area
        rx.cond(
            (~BrowseState.loading) & (BrowseState.error == ""),
            rx.cond(
                BrowseState.has_any_class,
                rx.cond(
                    BrowseState.filtered_module_keys.length() > 0,
                    _module_cards(),
                    # No matches state
                    rx.center(
                        rx.vstack(
                            rx.icon(tag="search_x", size=32, color=rx.color("gray", 7)),
                            rx.text("No classes match your search.", size="3", weight="medium"),
                            rx.text("Try a different query.", size="2", color_scheme="gray"),
                            rx.button(
                                "Clear search",
                                on_click=BrowseState.set_search(""),
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
                # Empty state — no classes at all
                empty_state("database", "No browsable classes found in schema."),
            ),
        ),
        spacing="4",
        width="100%",
    )


def browse_page() -> rx.Component:
    """Browse landing — tabbed hub with Classes, Graph, and Relationships views."""
    return shell(
        rx.vstack(
            # Page heading
            page_heading("Browse Schema Classes"),
            # ── Tabs ─────────────────────────────────────────────────
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Classes", value="classes"),
                    rx.tabs.trigger("Graph", value="graph"),
                    rx.tabs.trigger("Relationships", value="relationships"),
                    size="2",
                ),
                # Classes tab
                rx.tabs.content(
                    _classes_tab(),
                    value="classes",
                ),
                # Graph tab
                rx.tabs.content(
                    rx.vstack(
                        rx.cond(
                            GraphState.error != "",
                            error_callout(GraphState.error),
                        ),
                        graph_view(),
                        spacing="3",
                        width="100%",
                    ),
                    value="graph",
                ),
                # Relationships tab
                rx.tabs.content(
                    relationships_view(),
                    value="relationships",
                ),
                value=BrowseState.tab,
                on_change=BrowseState.set_tab,
                width="100%",
            ),
            # ── Detail drawer (shared) ──────────────────────────────
            json_detail_drawer(
                doc_var=GraphState.selected_doc,
                json_var=GraphState.selected_json,
                iri_var=iri_var(GraphState.selected_doc),
                on_close=GraphState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="browse",
    )
