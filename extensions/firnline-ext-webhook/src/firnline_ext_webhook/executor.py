"""Webhook reference ActionExecutor plugin.

Entry-point group: ``firnline.effectd.executors``
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from firnline_core.plugins import ActionContext, ExecutionResult, ModuleRequirement
from firnline_core.templates import default_webhook_payload, render as render_template

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class WebhookSettings(BaseSettings):
    """Webhook settings, loaded from WEBHOOK_* env vars."""

    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    default_token: str = ""
    """Optional static bearer token sent as ``Authorization: Bearer <token>``."""

    timeout_seconds: float = 10.0


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class WebhookExecutor:
    """Execute WebhookAction documents by calling the configured HTTP endpoint."""

    name: str = "webhook"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="triggers", range=">=0.1.0 <0.2.0"),
        ModuleRequirement(name="actions", range=">=0.1.0 <0.2.0"),
    ]
    kinds: tuple[str, ...] = ("webhook",)

    def __init__(self) -> None:
        self._settings: WebhookSettings | None = None

    @property
    def settings(self) -> WebhookSettings:
        """Lazy-load settings on first use so import works without env vars."""
        if self._settings is None:
            self._settings = WebhookSettings()  # type: ignore[call-arg]
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

        # URL must be present
        url = action.get("url", "")
        if not url:
            return ExecutionResult(
                ok=False,
                detail="Webhook URL is missing or empty — configure action.url",
                retryable=False,
            )

        # Method
        method = (action.get("http_method") or "POST").upper()

        # Body — template wins over canonical default payload
        idempotency_key = ctx.idempotency_key
        scheduled_for = firing.get("scheduled_for", "")
        if action.get("payload_template"):
            body_content = render_template(
                action["payload_template"],
                firing=firing,
                subject=subject,
                action=action,
                idempotency_key=idempotency_key,
            )
            body = body_content or ""
        else:
            body = default_webhook_payload(
                firing=firing,
                subject=subject,
                action=action,
                idempotency_key=idempotency_key,
                scheduled_for=scheduled_for,
            )

        # Headers
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["X-Firnline-Idempotency-Key"] = idempotency_key
        if settings.default_token:
            headers["Authorization"] = f"Bearer {settings.default_token}"

        # Execute HTTP call
        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                if isinstance(body, dict):
                    response = await client.request(
                        method, url, json=body, headers=headers
                    )
                else:
                    response = await client.request(
                        method, url, content=body, headers=headers
                    )

            if 200 <= response.status_code < 300:
                external_ref = response.headers.get("Location")
                return ExecutionResult(
                    ok=True,
                    detail=f"Webhook: {response.status_code}",
                    external_ref=external_ref,
                )
            elif 400 <= response.status_code < 500:
                text = response.text
                if len(text) > 500:
                    text = text[:500]
                return ExecutionResult(
                    ok=False,
                    detail=f"Webhook client error: {response.status_code} {text}",
                    retryable=False,
                )
            else:
                text = response.text
                if len(text) > 500:
                    text = text[:500]
                return ExecutionResult(
                    ok=False,
                    detail=f"Webhook server error: {response.status_code} {text}",
                    retryable=True,
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            return ExecutionResult(
                ok=False,
                detail="Webhook network/timeout error",
                retryable=True,
            )
        except Exception as exc:
            logger.exception("Webhook plugin: unexpected error during delivery")
            return ExecutionResult(
                ok=False,
                detail=f"Webhook unexpected error: {exc}",
                retryable=True,
            )


plugin = WebhookExecutor()
