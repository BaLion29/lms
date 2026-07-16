"""JsonDetailPanel — right-hand collapsible JSON viewer."""
from __future__ import annotations
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Label
import json


class JsonDetailPanel(VerticalScroll):
    """Collapsible right-hand panel showing JSON document detail."""

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._iri: str | None = None

    def compose(self) -> ComposeResult:
        yield Label("Document Detail", classes="card-title")
        yield Static("Select a row to view document details.", id="detail-content", classes="chip")

    def show_document(self, iri: str, json_str: str) -> None:
        """Display a document's JSON."""
        self._iri = iri
        content = self.query_one("#detail-content", Static)
        # Pretty-print JSON with syntax highlighting via Rich
        try:
            parsed = json.loads(json_str)
            formatted = json.dumps(parsed, indent=2, default=str)
        except (json.JSONDecodeError, TypeError):
            formatted = json_str
        content.update(formatted)

    def show_error(self, error: str) -> None:
        """Display an error message."""
        self._iri = None
        content = self.query_one("#detail-content", Static)
        content.update(f"Error: {error}")

    def clear(self) -> None:
        """Clear the panel."""
        self._iri = None
        content = self.query_one("#detail-content", Static)
        content.update("Select a row to view document details.", classes="chip")

    @property
    def current_iri(self) -> str | None:
        return self._iri
