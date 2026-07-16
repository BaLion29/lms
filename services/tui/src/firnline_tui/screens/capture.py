"""Capture screen — quick note capture and global CaptureModal."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static
from textual import work

from firnline_tui.ui.feedback import ErrorBanner
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.typography import page_heading


class CaptureScreen(ShellScreen):
    """Full-screen capture view with input and result feedback."""

    SCREEN_ID = "capture"
    TITLE = "Capture"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Capture")
        yield Input(placeholder="Type a note and press Enter…", id="note-input")
        yield ErrorBanner(id="error")
        yield Static("", id="result-feedback")

    def on_mount(self) -> None:
        self.query_one("#note-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "note-input":
            self._submit_note(event.value)

    async def action_submit_note(self) -> None:
        inp = self.query_one("#note-input", Input)
        if not inp.value.strip():
            self.query_one("#error", ErrorBanner).show("Text must not be empty.")
            return
        self._submit_note(inp.value)

    def _submit_note(self, text: str) -> None:
        if not text.strip():
            self.query_one("#error", ErrorBanner).show("Text must not be empty.")
            return
        self.query_one("#error", ErrorBanner).hide()
        self.query_one("#result-feedback", Static).update("\u27f3 Submitting\u2026")
        self._do_submit(text)

    @work
    async def _do_submit(self, text: str) -> None:
        from firnline_tui.state.capture import submit_note

        result = await submit_note(self.app.ctx, text)
        if result.ok:
            self.query_one("#result-feedback", Static).update(
                f"\u2713 Captured: {result.doc_id}"
            )
            inp = self.query_one("#note-input", Input)
            inp.value = ""
            inp.focus()
        else:
            self.query_one("#error", ErrorBanner).show(result.error)
            self.query_one("#result-feedback", Static).update("")

    def action_refresh(self) -> None:
        pass  # no refresh needed for capture


class CaptureModal(ModalScreen):
    """Global quick-capture modal — invoked with 'c' from any screen."""

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
