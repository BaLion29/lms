"""Reusable card and badge components."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.theme import RADIUS_MEDIUM, SHADOW_CARD, SPACE_1_5, SPACE_2
from firnline_webui.ui.typography import card_title


def status_card(
    title: str,
    status_badge: rx.Component,
    *children: rx.Component,
    size: str = "2",
) -> rx.Component:
    """A card with a title row (title + badge), then body content."""
    return rx.card(
        rx.hstack(
            card_title(title),
            rx.spacer(),
            status_badge,
            align="center",
            width="100%",
            border_bottom=f"1px solid {rx.color('gray', 3)}",
            padding_bottom=SPACE_2,
            margin_bottom=SPACE_2,
        ),
        *children,
        size=size,
        background=rx.color("gray", 1),
        border=f"1px solid {rx.color('gray', 4)}",
        border_radius=RADIUS_MEDIUM,
        box_shadow="none",
        _hover={
            "box_shadow": SHADOW_CARD,
        },
        transition="box-shadow 0.2s ease",
    )


def stat_badge(label: str, ok: rx.Var[bool] | bool) -> rx.Component:
    """A small coloured badge showing up/down status."""
    return rx.badge(
        rx.hstack(
            rx.box(
                width="6px",
                height="6px",
                border_radius="50%",
                background=rx.cond(ok, rx.color("green", 9), rx.color("red", 9)),
            ),
            rx.text(label, size="1"),
            spacing="1",
            align="center",
        ),
        color_scheme=rx.cond(ok, "green", "red"),
        variant="surface",
    )


def chip(label: rx.Var[str], color_scheme: str = "gray") -> rx.Component:
    """Tiny label chip."""
    return rx.badge(label, variant="surface", color_scheme=color_scheme, size="1")


def info_row(label: str, value: rx.Component | str) -> rx.Component:
    """Label: value row."""
    return rx.grid(
        rx.text(label, color_scheme="gray", size="2"),
        value if isinstance(value, rx.Component) else rx.text(value, size="2"),
        columns="120px 1fr",
        gap="2",
        width="100%",
        align="center",
    )


def status_dot_text(status: rx.Var[str] | str, color_map: dict[str, str] | None = None) -> rx.Component:
    """Small coloured dot + plain text label — for dense table rows.

    Follows the same status→colour mapping pattern as :func:`status_badge`,
    but renders as a lightweight ``hstack`` without a badge pill.

    Args:
        status: The status text to display (also used as lookup key).
        color_map: Optional dict mapping status values to colour-scheme
            names (e.g. ``"blue"``, ``"green"``).  Unknown statuses fall
            back to ``"gray"``.
    """
    s = rx.Var.create(status)
    _map = color_map or {}

    # Reactive colour lookup: chain rx.cond so unknown statuses fall back to gray.
    mapped_color: rx.Var = rx.color("gray", 9)
    for key, val in reversed(list(_map.items())):
        mapped_color = rx.cond(s == key, rx.color(val, 9), mapped_color)

    return rx.hstack(
        rx.box(
            width=SPACE_1_5,
            height=SPACE_1_5,
            border_radius="50%",
            background=mapped_color,
        ),
        rx.text(s, size="1", color=rx.color("gray", 11)),
        spacing="2",
        align="center",
    )


def status_badge(status: rx.Var[str] | str, color_map: dict[str, str] | None = None) -> rx.Component:
    """Coloured badge pill for table-row statuses.

    Follows the same status→colour mapping pattern as :func:`status_dot_text`,
    but renders as an ``rx.badge`` pill.

    Args:
        status: The status text to display (also used as lookup key).
        color_map: Optional dict mapping status values to colour-scheme
            names (e.g. ``"blue"``, ``"green"``).  Unknown statuses fall
            back to ``"gray"``.
    """
    s = rx.Var.create(status)
    _map = color_map or {}

    mapped_color: rx.Var = "gray"
    for key, val in reversed(list(_map.items())):
        mapped_color = rx.cond(s == key, val, mapped_color)

    return rx.badge(
        rx.text(s, size="1"),
        variant="surface",
        color_scheme=mapped_color,
    )
