"""Reusable card and badge components."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.theme import RADIUS_MEDIUM, SHADOW_CARD, SHADOW_CARD_HOVER


def status_card(
    title: str,
    status_badge: rx.Component,
    *children: rx.Component,
    size: str = "2",
) -> rx.Component:
    """A card with a title row (title + badge), then body content."""
    return rx.card(
        rx.hstack(
            rx.heading(title, size="4"),
            rx.spacer(),
            status_badge,
            align="center",
            width="100%",
            border_bottom=f"1px solid {rx.color('gray', 3)}",
            padding_bottom="8px",
            margin_bottom="8px",
        ),
        *children,
        size=size,
        background=rx.color("gray", 1),
        border=f"1px solid {rx.color('gray', 4)}",
        border_radius=RADIUS_MEDIUM,
        box_shadow=SHADOW_CARD,
        _hover={
            "box_shadow": SHADOW_CARD_HOVER,
            "border_color": rx.color("accent", 6),
        },
        transition="box-shadow 0.2s ease, border-color 0.2s ease",
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


def status_badge(status: str, color_map: dict[str, str] | None = None) -> rx.Component:
    """Colour-coded status badge — coloured dot + label.

    Args:
        status: The status text to display (also used as lookup key).
        color_map: Optional dict mapping status values to colour-scheme
            names (e.g. ``"blue"``, ``"green"``).  Unknown statuses fall
            back to ``"gray"``.
    """
    cs = (color_map or {}).get(status, "gray")
    return rx.badge(
        rx.hstack(
            rx.box(width="6px", height="6px", border_radius="50%", background=rx.color(cs, 9)),
            rx.text(status, size="1"),
            spacing="1",
            align="center",
        ),
        color_scheme=cs,
        variant="surface",
        size="1",
    )
