"""Gotify notification channel plugin.

Delivers notification firings via the Gotify HTTP API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from firnline_core.plugins import DeliveryResult, ModuleRequirement, NotificationChannel, NotifyContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GotifySettings(BaseSettings):
    """Gotify connection settings, loaded from GOTIFY_* env vars."""

    model_config = SettingsConfigDict(env_prefix="GOTIFY_")

    url: str = ""
    token: str = ""
    priority: int = 5
    timeout_seconds: float = 10.0


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class GotifyChannel(NotificationChannel):
    """Deliver notifications via Gotify push service."""

    name: str = "gotify"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="triggers", range=">=0.1.0 <0.2.0"),
    ]

    def __init__(self) -> None:
        self._settings: GotifySettings | None = None

    @property
    def settings(self) -> GotifySettings:
        """Lazy-load settings on first use so import works without env vars."""
        if self._settings is None:
            self._settings = GotifySettings()  # type: ignore[call-arg]
        return self._settings

    async def deliver(
        self,
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: NotifyContext,
    ) -> DeliveryResult:
        settings = self.settings
        if not settings.url or not settings.token:
            logger.error("Gotify channel: GOTIFY_URL and/or GOTIFY_TOKEN not set")
            return DeliveryResult(
                ok=False,
                detail="Gotify not configured: GOTIFY_URL and GOTIFY_TOKEN are required",
                retryable=False,
            )

        # Compose title from subject metadata
        title = "Firnline reminder"
        if subject:
            if isinstance(subject, dict):
                title = str(
                    subject.get("name")
                    or subject.get("title")
                    or subject.get("@type", subject.get("@id", title))
                )

        # Compose a human-readable message from firing fields
        message_parts: list[str] = []
        scheduled_for = firing.get("scheduled_for")
        if scheduled_for:
            message_parts.append(f"Scheduled: {scheduled_for}")
        occurrence_key = firing.get("occurrence_key")
        if occurrence_key:
            message_parts.append(f"Key: {occurrence_key}")
        message = "; ".join(message_parts) if message_parts else "Reminder triggered"

        payload: dict[str, Any] = {
            "title": title,
            "message": message,
            "priority": settings.priority,
        }

        headers: dict[str, str] = {"X-Gotify-Key": settings.token}
        endpoint = f"{settings.url.rstrip('/')}/message"

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                return DeliveryResult(ok=True, detail=f"Gotify: {response.status_code}")
            elif 400 <= response.status_code < 500:
                return DeliveryResult(
                    ok=False,
                    detail=f"Gotify client error: {response.status_code} {response.text}",
                    retryable=False,
                )
            else:
                return DeliveryResult(
                    ok=False,
                    detail=f"Gotify server error: {response.status_code} {response.text}",
                    retryable=True,
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
            return DeliveryResult(
                ok=False,
                detail="Gotify network/timeout error",
                retryable=True,
            )
        except Exception as exc:
            logger.exception("Gotify channel: unexpected error during delivery")
            return DeliveryResult(
                ok=False,
                detail=f"Gotify unexpected error: {exc}",
                retryable=True,
            )


plugin = GotifyChannel()
