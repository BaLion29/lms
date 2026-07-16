"""Card and badge widgets — analog of firnline_webui/ui/cards.py."""
from __future__ import annotations
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label


class StatusCard(Vertical):
    """A card showing a service status with title, status, and optional detail."""

    def __init__(self, title: str, status: str = "unknown", version: str = "", error: str = "") -> None:
        super().__init__()
        self._title = title
        self._status = status
        self._version = version
        self._error = error

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="card-title")
        status_class = _status_class(self._status)
        yield Label(f"● {self._status}", classes=f"status-{status_class}", id="card-status")
        if self._version:
            yield Label(f"v{self._version}", classes="chip")
        if self._error:
            yield Label(self._error[:200], classes="status-err")


class StatBadge(Static):
    """A bold stat number with a label."""

    def __init__(self, value: str | int, label: str = "") -> None:
        super().__init__()
        if label:
            self.update(f"{value} {label}")
        else:
            self.update(str(value))


class Chip(Static):
    """A small muted text badge."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.add_class("chip")


class InfoRow(Horizontal):
    """A key-value row: label on the left, value on the right."""

    def __init__(self, label: str, value: str) -> None:
        super().__init__()
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="chip")
        yield Label(self._value, classes="info-value")


def _status_class(status: str) -> str:
    """Map a status string to a CSS status class."""
    s = status.lower()
    if s in ("ok", "healthy", "ready"):
        return "ok"
    if s in ("degraded", "warn", "warning"):
        return "warn"
    if s in ("error", "down", "unreachable", "failed"):
        return "err"
    return "unknown"


def status_dot(status: str) -> str:
    """Return a colored dot character for a status string."""
    cls = _status_class(status)
    return {
        "ok": "🟢", "warn": "🟡", "err": "🔴", "unknown": "⚪",
    }.get(cls, "⚪")
