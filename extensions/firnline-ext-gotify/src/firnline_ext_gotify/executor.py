"""Gotify action executor plugin.

Entry-point group: ``firnline.effectd.executors``
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from firnline_core.plugins import ActionContext, ExecutionResult, ModuleRequirement
from firnline_core.templates import render as render_template

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GotifySettings(BaseSettings):
    """Gotify settings, loaded from GOTIFY_* env vars."""

    model_config = SettingsConfigDict(env_prefix="GOTIFY_")

    url: str = ""
    token: str = ""
    priority: int = 5
    timeout_seconds: float = 10.0


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

        # Dry-run — no side effects
        if ctx.dry_run:
            return ExecutionResult(ok=True, detail="dry_run")

        # Config guard
        url = settings.url
        token = settings.token
        if not url or not token:
            logger.error("Gotify plugin: GOTIFY_URL and/or GOTIFY_TOKEN not set")
            return ExecutionResult(
                ok=False,
                detail="Gotify not configured: GOTIFY_URL and GOTIFY_TOKEN are required",
                retryable=False,
            )

        # Title: template first, fall back to subject-derived title
        title = render_template(
            action.get("title_template"),
            firing=firing,
            subject=subject,
            action=action,
            idempotency_key=ctx.idempotency_key,
        ) or _build_subject_title(subject)

        # Body: template first, fall back to firing-derived message
        message = render_template(
            action.get("body_template"),
            firing=firing,
            subject=subject,
            action=action,
            idempotency_key=ctx.idempotency_key,
        ) or _build_body_message(firing)

        # Headers
        headers: dict[str, str] = {"X-Gotify-Key": token}
        if ctx.idempotency_key:
            headers["X-Firnline-Idempotency-Key"] = ctx.idempotency_key

        # Execute HTTP call
        endpoint = f"{url.rstrip('/')}/message"
        payload: dict[str, Any] = {
            "title": title,
            "message": message,
            "priority": settings.priority,
        }

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                response = await client.post(endpoint, json=payload, headers=headers)

            if 200 <= response.status_code < 300:
                external_ref: str | None = None
                try:
                    body = response.json()
                    if isinstance(body, dict) and "id" in body:
                        external_ref = str(body["id"])
                except Exception:
                    pass
                return ExecutionResult(
                    ok=True,
                    detail=f"Gotify: {response.status_code}",
                    external_ref=external_ref,
                )
            elif 400 <= response.status_code < 500:
                text = response.text
                if len(text) > 500:
                    text = text[:500]
                return ExecutionResult(
                    ok=False,
                    detail=f"Gotify client error: {response.status_code} {text}",
                    retryable=False,
                )
            else:
                text = response.text
                if len(text) > 500:
                    text = text[:500]
                return ExecutionResult(
                    ok=False,
                    detail=f"Gotify server error: {response.status_code} {text}",
                    retryable=True,
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
            return ExecutionResult(
                ok=False,
                detail="Gotify network/timeout error",
                retryable=True,
            )
        except Exception as exc:
            logger.exception("Gotify plugin: unexpected error during delivery")
            return ExecutionResult(
                ok=False,
                detail=f"Gotify unexpected error: {exc}",
                retryable=True,
            )


# ---------------------------------------------------------------------------
# Title / body fallback helpers
# ---------------------------------------------------------------------------


def _build_subject_title(subject: dict[str, Any] | None) -> str:
    """Fallback chain: name → title → @type → @id → default."""
    if subject is None:
        return "Firnline reminder"
    if isinstance(subject, dict):
        return str(
            subject.get("name") or subject.get("title") or subject.get("@type", subject.get("@id", "Firnline reminder"))
        )
    return "Firnline reminder"


def _build_body_message(firing: dict[str, Any]) -> str:
    """Compose a human-readable body from firing fields."""
    message_parts: list[str] = []
    scheduled_for = firing.get("scheduled_for")
    if scheduled_for:
        message_parts.append(f"Scheduled: {scheduled_for}")
    occurrence_key = firing.get("occurrence_key")
    if occurrence_key:
        message_parts.append(f"Key: {occurrence_key}")
    return "; ".join(message_parts) if message_parts else "Reminder triggered"


plugin = GotifyExecutor()
