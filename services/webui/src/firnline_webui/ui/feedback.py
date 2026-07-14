"""Shared loading/empty/error feedback components for consistent UI states."""

from __future__ import annotations

import reflex as rx


def error_callout(message: rx.Var[str]) -> rx.Component:
    """Red callout with alert icon — for error states."""
    return rx.callout(
        rx.hstack(
            rx.icon(tag="triangle_alert", size=14, color="var(--red-9)"),
            rx.text(message, size="2"),
            align="center",
            spacing="2",
        ),
        color_scheme="red",
        size="1",
        width="100%",
    )


def empty_state(icon_tag: str, title: str, hint: str | None = None) -> rx.Component:
    """Centered muted block with icon + title + optional hint.

    Args:
        icon_tag: Lucide icon tag name (e.g. ``"inbox"``).
        title: Primary message.
        hint: Optional secondary message shown below the title.
    """
    return rx.center(
        rx.vstack(
            rx.icon(tag=icon_tag, size=32, color=rx.color("gray", 7)),
            rx.text(title, size="3", weight="medium"),
            rx.cond(
                hint is not None and hint != "",
                rx.text(hint, size="2", color_scheme="gray"),
                rx.text(""),
            ),
            spacing="3",
            align="center",
        ),
        width="100%",
        padding_y="64px",
    )


def loading_spinner() -> rx.Component:
    """Centered loading spinner."""
    return rx.center(rx.spinner(size="3"), padding="64px", width="100%")
