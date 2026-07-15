"""Graph view — interactive force-directed graph of document nodes.

Overhauled: multi-class/predicate filter chips, search, node cap, legend,
neighbourhood focus mode, loading/error states.
"""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.graph import GraphState
from firnline_webui.ui.controls import color_legend, filter_chip, search_input
from firnline_webui.ui.feedback import error_callout, loading_spinner
from firnline_webui.ui.graph import force_graph


def _type_filter_bar() -> rx.Component:
    """Row of type filter chips built from index type_counts."""
    return rx.flex(
        rx.cond(
            GraphState.type_counts_list.length() > 0,
            rx.foreach(
                rx.Var.create(GraphState.type_counts_list),
                lambda item: filter_chip(
                    label=item["type"].to(str) + " · " + item["count"].to(str),
                    selected=GraphState.active_types.contains(item["type"]),
                    on_click=GraphState.toggle_type(item["type"]),
                ),
            ),
        ),
        wrap="wrap",
        gap="1",
        width="100%",
    )


def _predicate_filter_bar() -> rx.Component:
    """Row of predicate filter chips."""
    return rx.flex(
        rx.cond(
            GraphState.predicate_list.length() > 0,
            rx.foreach(
                rx.Var.create(GraphState.predicate_list),
                lambda item: filter_chip(
                    label=item["prop"].to(str) + " · " + item["count"].to(str),
                    selected=GraphState.active_predicates.contains(item["prop"]),
                    on_click=GraphState.toggle_predicate(item["prop"]),
                ),
            ),
        ),
        wrap="wrap",
        gap="1",
        width="100%",
    )


def _node_cap_section() -> rx.Component:
    """Node cap selector and truncation warning."""
    return rx.hstack(
        rx.text("Node cap:", size="1", color_scheme="gray"),
        rx.select(
            ["500", "1000", "2000"],
            value=GraphState.max_nodes.to(str),
            on_change=GraphState.set_max_nodes,
            size="1",
            width="100px",
        ),
        rx.cond(
            GraphState.truncated,
            rx.badge(
                rx.text(
                    "Showing " + GraphState.nodes.length().to_string()
                    + " of "
                    + GraphState.total_filtered.to_string()
                    + " nodes — refine filters",
                    size="1",
                ),
                color_scheme="amber",
                variant="soft",
                size="1",
            ),
        ),
        spacing="2",
        align="center",
    )


def _focus_panel() -> rx.Component:
    """Info panel shown when a node is selected, with focus controls."""
    return rx.cond(
        GraphState.focus_node_id != "",
        rx.card(
            rx.vstack(
                rx.heading(
                    GraphState.focus_node_label,
                    size="3",
                ),
                rx.hstack(
                    rx.cond(
                        GraphState.focus_node_type != "",
                        rx.badge(
                            GraphState.focus_node_type,
                            variant="surface",
                            color_scheme="cyan",
                            size="1",
                        ),
                    ),
                    rx.text(
                        "deg " + GraphState.focus_node_degree.to_string(),
                        size="1",
                        color_scheme="gray",
                    ),
                    rx.text(
                        "in " + GraphState.focus_node_in.to_string(),
                        size="1",
                        color_scheme="gray",
                    ),
                    rx.text(
                        "out " + GraphState.focus_node_out.to_string(),
                        size="1",
                        color_scheme="gray",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    ~GraphState.is_focused,
                    rx.button(
                        rx.icon(tag="focus", size=14),
                        "Focus neighborhood",
                        variant="soft",
                        color_scheme="cyan",
                        size="1",
                        on_click=GraphState.focus_current,
                    ),
                    rx.hstack(
                        rx.text("Hops:", size="1", color_scheme="gray"),
                        rx.select(
                            ["1", "2", "3"],
                            value=GraphState.focus_hops.to(str),
                            on_change=GraphState.set_focus_hops,
                            size="1",
                            width="80px",
                        ),
                        rx.button(
                            rx.icon(tag="x", size=14),
                            "Exit focus",
                            variant="outline",
                            color_scheme="gray",
                            size="1",
                            on_click=GraphState.exit_focus,
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
                spacing="2",
            ),
            size="2",
            width="100%",
        ),
    )


def _focus_breadcrumb() -> rx.Component:
    """Breadcrumb showing current focus context."""
    return rx.cond(
        GraphState.is_focused,
        rx.badge(
            rx.text(
                "Neighborhood of "
                + GraphState.focus_node_label
                + " ("
                + GraphState.focus_hops.to_string()
                + " hops)",
                size="1",
            ),
            color_scheme="cyan",
            variant="soft",
            size="1",
        ),
    )


def _index_errors_warning() -> rx.Component:
    """Dismissible warning for per-class fetch errors."""
    return rx.cond(
        (GraphState.index_errors.length() > 0),
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
                        on_click=GraphState.dismiss_index_errors,
                        custom_attrs={"aria-label": "Dismiss warnings"},
                    ),
                    align="center",
                    spacing="2",
                ),
                rx.text(
                    rx.foreach(
                        GraphState.index_errors,
                        lambda e: rx.fragment(rx.text(e, size="1"), rx.text("", display="none")),
                    ),
                ),
                spacing="1",
            ),
            color_scheme="amber",
            size="1",
            width="100%",
        ),
    )


def graph_view() -> rx.Component:
    """Render the force-graph view with filters, legend, focus, and states."""
    return rx.vstack(
        # ── Loading spinner ───────────────────────────────────────
        rx.cond(
            GraphState.loading,
            loading_spinner(),
        ),
        # ── Error ─────────────────────────────────────────────────
        rx.cond(
            (GraphState.error != ""),
            error_callout(GraphState.error),
        ),
        # ── Index errors ──────────────────────────────────────────
        _index_errors_warning(),
        # ── Filters (hidden in focus mode) ────────────────────────
        rx.cond(
            (~GraphState.is_focused) & GraphState.loaded,
            rx.vstack(
                # Search
                search_input(
                    value=GraphState.search_text,
                    on_change=GraphState.set_search,
                    placeholder="Search nodes…",
                ),
                # Type filter chips
                rx.cond(
                    GraphState.type_counts_list.length() > 0,
                    rx.vstack(
                        rx.text("Classes", size="1", color_scheme="gray"),
                        _type_filter_bar(),
                        spacing="1",
                        width="100%",
                    ),
                ),
                # Predicate filter chips
                rx.cond(
                    GraphState.predicate_list.length() > 0,
                    rx.vstack(
                        rx.text("Predicates", size="1", color_scheme="gray"),
                        _predicate_filter_bar(),
                        spacing="1",
                        width="100%",
                    ),
                ),
                spacing="2",
                width="100%",
            ),
        ),
        # ── Node cap + truncation warning ─────────────────────────
        rx.cond(
            (~GraphState.is_focused) & GraphState.loaded,
            _node_cap_section(),
        ),
        # ── Focus breadcrumb ──────────────────────────────────────
        _focus_breadcrumb(),
        # ── Colour legend ─────────────────────────────────────────
        rx.cond(
            GraphState.legend_items.length() > 0,
            color_legend(GraphState.legend_items.to(list[dict])),
        ),
        # ── Graph container ───────────────────────────────────────
        rx.box(
            rx.cond(
                (~GraphState.loading) & (GraphState.error == "") & (GraphState.loaded),
                force_graph(
                    graph_data=GraphState.graph_data,
                    node_label="label",
                    node_color="color",
                    width=1100,
                    height=640,
                    background_color="rgba(0,0,0,0)",
                    link_label="prop",
                    link_directional_arrow_length=4,
                    link_directional_arrow_rel_pos=1.0,
                    on_node_click=GraphState.select_node,
                ),
            ),
            border=f"1px solid {rx.color('gray', 4)}",
            border_radius="8px",
            height="640px",
            overflow="hidden",
            width="100%",
        ),
        # ── Focus panel ───────────────────────────────────────────
        _focus_panel(),
        # ── Node/edge count caption ───────────────────────────────
        rx.hstack(
            rx.text(
                GraphState.nodes.length().to_string() + " nodes",
                size="1",
                color_scheme="gray",
            ),
            rx.text("·", size="1", color_scheme="gray"),
            rx.text(
                GraphState.links.length().to_string() + " edges",
                size="1",
                color_scheme="gray",
            ),
            spacing="1",
        ),
        spacing="3",
        width="100%",
    )
