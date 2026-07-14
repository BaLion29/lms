"""Tests for the ui/feedback helpers."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.feedback import empty_state, error_callout, loading_spinner


def test_error_callout():
    """error_callout renders the given error message."""
    comp = error_callout(rx.Var.create("something went wrong"))
    assert comp is not None
    rendered = str(comp)
    assert "something went wrong" in rendered


def test_empty_state():
    """empty_state renders the given title."""
    comp = empty_state("inbox", "Nothing here")
    assert comp is not None
    rendered = str(comp)
    assert "Nothing here" in rendered


def test_empty_state_with_hint():
    """empty_state with hint renders both title and hint."""
    comp = empty_state("inbox", "Nothing here", hint="Try adding items.")
    assert comp is not None
    rendered = str(comp)
    assert "Nothing here" in rendered
    assert "Try adding items." in rendered


def test_loading_spinner():
    """loading_spinner returns a component."""
    comp = loading_spinner()
    assert comp is not None
