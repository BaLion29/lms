"""Gotify native ActionExecutor plugin.

Entry-point group: ``firnline.effectd.executors``
"""

from __future__ import annotations

import logging
from typing import Any

from firnline_core.plugins import ActionContext, ActionExecutor, ExecutionResult, ModuleRequirement
from firnline_core.templates import render as render_template

from firnline_ext_gotify._common import (
    GotifySettings,
    _build_body_message,
    _build_subject_title,
    _ensure_configured,
    _post_gotify,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class GotifyExecutor:
    """Execute NotifyAction documents via the Gotify push service."""

    name: str = "gotify"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="triggers", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="actions", range=">=0.1.0 <0.2.0"),
    ]
    kinds: tuple[str, ...] = ("notify:gotify",)

    def __init__(self) -> None:
        self._settings: GotifySettings | None = None

    @property
    def settings(self) -> GotifySettings:
        """Lazy-load settings on first use so import works without env vars."""
        if self._settings is None:
            self._settings = GotifySettings()  # type: ignore[call-arg]
        return self._settings

    async def execute(
        self,
        action: dict[str, Any],
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: ActionContext,
    ) -> ExecutionResult:
        settings = self.settings

        # Config guard
        fail = _ensure_configured(settings)
        if fail is not None:
            return fail

        # Dry-run — no side effects
        if ctx.dry_run:
            return ExecutionResult(ok=True, detail="dry_run")

        # Title: template first, fall back to subject-derived title
        title = (
            render_template(
                action.get("title_template"),
                firing=firing,
                subject=subject,
                action=action,
                idempotency_key=ctx.idempotency_key,
            )
            or _build_subject_title(subject)
        )

        # Body: template first, fall back to firing-derived message
        message = (
            render_template(
                action.get("body_template"),
                firing=firing,
                subject=subject,
                action=action,
                idempotency_key=ctx.idempotency_key,
            )
            or _build_body_message(firing)
        )

        extra_headers: dict[str, str] = {}
        if ctx.idempotency_key:
            extra_headers["X-Firnline-Idempotency-Key"] = ctx.idempotency_key

        return await _post_gotify(
            url=settings.url,
            token=settings.token,
            title=title,
            message=message,
            priority=settings.priority,
            timeout=settings.timeout_seconds,
            extra_headers=extra_headers,
        )


plugin = GotifyExecutor()
