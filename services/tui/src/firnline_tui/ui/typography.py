"""Typography helpers — page headings and section titles."""
from __future__ import annotations
from textual.widgets import Label


def page_heading(text: str) -> Label:
    """Return a styled page heading label."""
    label = Label(text)
    label.add_class("page-heading")
    return label


def section_heading(text: str) -> Label:
    """Return a styled section heading label."""
    label = Label(text)
    label.add_class("section-heading")
    return label


def card_title(text: str) -> Label:
    """Return a styled card title label."""
    label = Label(text)
    label.add_class("card-title")
    return label
