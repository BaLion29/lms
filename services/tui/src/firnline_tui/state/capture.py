"""Capture state — note capture via the captured service."""
from __future__ import annotations

from dataclasses import dataclass

from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class CaptureResult:
    ok: bool
    doc_id: str = ""
    error: str = ""


async def submit_note(ctx: AppContext, text: str) -> CaptureResult:
    """Submit a text note. Returns CaptureResult."""
    if not text.strip():
        return CaptureResult(ok=False, error="Text must not be empty.")
    client = ctx.make_captured()
    try:
        result = await client.capture_note(text=text.strip())
        return CaptureResult(ok=True, doc_id=str(result.get("id", "?")))
    except UiClientError as exc:
        return CaptureResult(ok=False, error=f"({exc.status}): {exc.detail}")
