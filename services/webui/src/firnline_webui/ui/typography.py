"""Typography helpers — consistent heading and text patterns."""

from __future__ import annotations

import reflex as rx


def page_heading(title: str) -> rx.Component:
    """Standard page-level heading — size 6, medium weight."""
    return rx.heading(title, size="6", weight="medium")


def section_heading(title: str) -> rx.Component:
    """Standard section heading — size 5, bold weight."""
    return rx.heading(title, size="5", weight="bold", margin_bottom="12px")
