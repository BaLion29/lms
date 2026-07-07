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
        ),
        rx.divider(margin_y="2"),
        *children,
        size=size,
    )


def stat_badge(label: str, ok: rx.Var[bool] | bool) -> rx.Component:
    """A small coloured badge showing up/down status."""
    return rx.badge(
        rx.cond(
            ok,
            rx.hstack(rx.icon(tag="circle_check", size=14), rx.text(label)),
            rx.hstack(rx.icon(tag="circle_x", size=14), rx.text(label)),
        ),
        color_scheme=rx.cond(ok, "green", "red"),
        variant="soft",
    )


def chip(label: rx.Var[str], color_scheme: str = "gray") -> rx.Component:
    """Tiny label chip."""
    return rx.badge(label, variant="soft", color_scheme=color_scheme, size="1")


def info_row(label: str, value: rx.Component | str) -> rx.Component:
    """Label: value row."""
    return rx.hstack(
        rx.text(label, color_scheme="gray", size="2", width="120px"),
        value if isinstance(value, rx.Component) else rx.text(value, size="2"),
        spacing="2",
    )
