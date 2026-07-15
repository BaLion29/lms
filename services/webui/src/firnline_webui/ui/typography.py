"""Typography helpers — consistent heading and text patterns."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.theme import SPACE_3


def page_heading(title: str | rx.Var[str]) -> rx.Component:
    """Page-level heading — exactly one per page, at the top."""
    return rx.heading(title, size="6", weight="medium")


def section_heading(title: str | rx.Var[str]) -> rx.Component:
    """Section title within a page."""
    return rx.heading(title, size="5", weight="medium", margin_bottom=SPACE_3)


def card_title(title: str | rx.Var[str]) -> rx.Component:
    """Title inside a card (status cards, Quick Capture, drawers)."""
    return rx.heading(title, size="4", weight="medium")
