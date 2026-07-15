"""react-force-graph-2d custom Reflex component.

Wraps the `ForceGraph2D` React component for interactive graph visualization.
"""

from __future__ import annotations

import reflex as rx


class ForceGraph2D(rx.NoSSRComponent):
    """react-force-graph-2d wrapper — must use NoSSR (accesses window/canvas)."""

    library = "react-force-graph-2d"
    tag = "ForceGraph2D"
    is_default = True

    # Data props
    graph_data: rx.Var[dict]  # {"nodes": [...], "links": [...]}
    node_label: rx.Var[str]  # field used for hover tooltip, e.g. "label"
    node_auto_color_by: rx.Var[str]  # e.g. "group" — legacy, prefer node_color
    node_color: rx.Var[str]  # field name for deterministic node colour, e.g. "color"
    width: rx.Var[int]
    height: rx.Var[int]
    background_color: rx.Var[str]

    # Link label — shown on edge hover
    link_label: rx.Var[str]

    # Link arrow props
    link_directional_arrow_length: rx.Var[int]
    link_directional_arrow_rel_pos: rx.Var[float]

    # Event — passes the clicked node's id string to the backend
    on_node_click: rx.EventHandler[lambda node: [node.id]]


force_graph = ForceGraph2D.create
