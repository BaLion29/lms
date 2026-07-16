"""Feedback widgets — errors, empty states, loading indicators."""
from __future__ import annotations
from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.containers import Vertical


class ErrorBanner(Static):
    """A red-bordered error banner."""

    def __init__(self, message: str = "", id: str | None = None) -> None:
        super().__init__(id=id)
        if message:
            self.update(message)
        else:
            self.display = False

    def show(self, message: str) -> None:
        """Show the error banner with a message."""
        self.update(f"⚠ {message}")
        self.display = True
        self.add_class("error-banner")

    def hide(self) -> None:
        """Hide the error banner."""
        self.display = False
        self.remove_class("error-banner")


class EmptyState(Vertical):
    """An empty-state placeholder with an icon, message, and optional hint."""

    def __init__(self, message: str = "Nothing here yet.", hint: str = "") -> None:
        super().__init__()
        self._message = message
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Label(self._message, classes="empty-state-msg")
        if self._hint:
            yield Label(self._hint, classes="chip")


class LoadingIndicator(Static):
    """A simple loading indicator."""

    def __init__(self, message: str = "Loading…") -> None:
        super().__init__(f"⟳ {message}")
        self.add_class("loading-indicator")
