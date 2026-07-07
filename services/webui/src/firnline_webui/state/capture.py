"""Capture state — note and file capture via the captured service."""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import CapturedClient, WebuiClientError
from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

_settings = get_settings()


class CaptureState(BaseState):
    """State for the /capture page."""

    # ── Tab ──
    mode: str = "note"  # "note" | "file"

    # ── Note fields ──
    note_text: str = ""
    kind: str = "note"
    metadata_json: str = "{}"

    # ── Shared ──
    submitting: bool = False
    result_message: str = ""
    result_ok: bool = False

    # ── Display‑only handler names from captured healthz ──
    handler_names: list[str] = []

    # ── Metadata section expanded ──
    metadata_expanded: bool = False

    @rx.event
    async def load(self):
        """Fetch captured healthz to populate handler names (graceful on failure)."""
        try:
            client = _make_captured()
            data = await client.healthz()
            self.handler_names = list(data.get("handlers", []) or [])
        except Exception:
            self.handler_names = []
        yield

    @rx.event
    async def submit_note(self):
        """Submit a text note to the capture pipeline."""
        self.submitting = True
        self.result_message = ""
        yield

        if not self.note_text.strip():
            self.result_message = "Text must not be empty."
            self.result_ok = False
            self.submitting = False
            yield
            return

        try:
            metadata = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            self.result_message = "Metadata must be valid JSON."
            self.result_ok = False
            self.submitting = False
            yield
            return
        if not isinstance(metadata, dict):
            self.result_message = "Metadata must be a JSON object (dictionary)."
            self.result_ok = False
            self.submitting = False
            yield
            return

        try:
            client = _make_captured()
            result = await client.capture_note(
                text=self.note_text.strip(),
                kind=self.kind.strip() or "note",
                metadata=metadata if metadata else None,
            )
            doc_id = result.get("id", "?")
            self.result_message = f"Note captured: {doc_id}"
            self.result_ok = True
            self.note_text = ""
            yield rx.toast.success(f"Note captured: {doc_id}")
        except WebuiClientError as exc:
            self.result_message = f"Error ({exc.status}): {exc.detail}"
            self.result_ok = False
            yield rx.toast.error(f"Capture failed: {exc.detail}")

        self.submitting = False
        yield

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Handle file upload from the dropzone."""
        self.submitting = True
        self.result_message = ""
        yield

        # Validate metadata JSON
        try:
            metadata = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            self.result_message = "Metadata must be valid JSON."
            self.result_ok = False
            self.submitting = False
            yield
            return
        if not isinstance(metadata, dict):
            self.result_message = "Metadata must be a JSON object (dictionary)."
            self.result_ok = False
            self.submitting = False
            yield
            return

        if not files:
            self.result_message = "No file selected."
            self.result_ok = False
            self.submitting = False
            yield
            return

        file = files[0]
        data = await file.read()
        max_bytes = 25 * 1024 * 1024
        if len(data) > max_bytes:
            self.result_message = f"File exceeds 25 MB limit ({_fmt_size(len(data))})."
            self.result_ok = False
            self.submitting = False
            yield
            return

        try:
            client = _make_captured()
            result = await client.capture_file(
                filename=file.filename or "unnamed",
                content=data,
                content_type=file.content_type or "application/octet-stream",
                kind=self.kind.strip() or "file",
                metadata=metadata if metadata else None,
            )
            doc_id = result.get("id", "?")
            self.result_message = f"File captured: {doc_id}"
            self.result_ok = True
            yield rx.toast.success(f"File captured: {doc_id}")
        except WebuiClientError as exc:
            self.result_message = f"Error ({exc.status}): {exc.detail}"
            self.result_ok = False
            yield rx.toast.error(f"Capture failed: {exc.detail}")

        self.submitting = False
        yield

    @rx.event
    def clear_result(self):
        """Dismiss the result callout."""
        self.result_message = ""
        self.result_ok = False

    @rx.event
    def set_mode(self, mode: str):
        """Switch between note and file tabs."""
        self.mode = mode
        self.kind = "note" if mode == "note" else "file"

    @rx.event
    def toggle_metadata(self):
        """Toggle metadata section visibility."""
        self.metadata_expanded = not self.metadata_expanded

    @rx.event
    def set_kind(self, value: str):
        """Set the kind field."""
        self.kind = value

    @rx.event
    def set_note_text(self, value: str):
        """Set the note text."""
        self.note_text = value

    @rx.event
    def set_metadata_json(self, value: str):
        """Set the metadata JSON field."""
        self.metadata_json = value


def _make_captured() -> CapturedClient:
    return CapturedClient(
        _settings.captured_url,
        _settings.captured_api_token,
        timeout=_settings.request_timeout_seconds,
    )


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
