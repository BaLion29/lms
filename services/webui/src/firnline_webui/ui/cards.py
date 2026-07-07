"""Reusable card and badge components."""

from __future__ import annotations

import reflex as rx


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
        box_shadow="0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06)",
        _hover={
            "box_shadow": "0 2px 4px rgba(0,0,0,0.06), 0 4px 8px rgba(0,0,0,0.08)",
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
