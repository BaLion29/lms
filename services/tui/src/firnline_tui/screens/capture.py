"""CaptureModal — quick note capture invoked via command palette."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static
from textual import work


class CaptureModal(ModalScreen):
    """Global quick-capture modal — invoked via the command palette (Ctrl+P)."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Quick Capture", classes="card-title")
        yield Input(placeholder="Type a note and press Enter\u2026", id="capture-input")
        yield Static("", id="capture-feedback")

    def on_mount(self) -> None:
        self.query_one("#capture-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "capture-input":
            self._submit(event.value)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def _submit(self, text: str) -> None:
        if not text.strip():
            self.dismiss(None)
            return
        self._do_submit_modal(text)

    @work
    async def _do_submit_modal(self, text: str) -> None:
        from firnline_tui.state.capture import submit_note

        result = await submit_note(self.app.ctx, text)
        feedback = self.query_one("#capture-feedback", Static)
        if result.ok:
            feedback.update(f"\u2713 Captured: {result.doc_id}")
            self.dismiss(result.doc_id)
        else:
            feedback.update(f"\u26a0 {result.error}")
