"""Gotify notification channel plugin.

Delivers notification firings via the Gotify HTTP API.
"""

from __future__ import annotations

import logging
from typing import Any

from firnline_core.plugins import DeliveryResult, ModuleRequirement, NotificationChannel, NotifyContext

from firnline_ext_gotify._common import (
    GotifySettings,
    _build_body_message,
    _build_subject_title,
    _ensure_configured,
    _post_gotify,
)

logger = logging.getLogger(__name__)


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

        # Config guard
        fail = _ensure_configured(settings)
        if fail is not None:
            return fail

        title = _build_subject_title(subject)
        message = _build_body_message(firing)

        return await _post_gotify(
            url=settings.url,
            token=settings.token,
            title=title,
            message=message,
            priority=settings.priority,
            timeout=settings.timeout_seconds,
        )


plugin = GotifyChannel()
