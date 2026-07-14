"""Shared helpers for Gotify channel and executor plugins."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from firnline_core.plugins import ExecutionResult

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
# Configuration guard
# ---------------------------------------------------------------------------


def _ensure_configured(settings: GotifySettings) -> ExecutionResult | None:
    """Return a terminal result when settings are incomplete, else None."""
    if not settings.url or not settings.token:
        logger.error("Gotify plugin: GOTIFY_URL and/or GOTIFY_TOKEN not set")
        return ExecutionResult(
            ok=False,
            detail="Gotify not configured: GOTIFY_URL and GOTIFY_TOKEN are required",
            retryable=False,
        )
    return None


# ---------------------------------------------------------------------------
# Title / body helpers
# ---------------------------------------------------------------------------


def _build_subject_title(subject: dict[str, Any] | None) -> str:
    """Fallback chain: name → title → @type → @id → default."""
    if subject is None:
        return "Firnline reminder"
    if isinstance(subject, dict):
        return str(
            subject.get("name")
            or subject.get("title")
            or subject.get("@type", subject.get("@id", "Firnline reminder"))
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


# ---------------------------------------------------------------------------
# HTTP delivery
# ---------------------------------------------------------------------------


async def _post_gotify(
    url: str,
    token: str,
    title: str,
    message: str,
    priority: int,
    timeout: float,
    *,
    extra_headers: dict[str, str] | None = None,
) -> ExecutionResult:
    """POST /message to Gotify and return an ExecutionResult.

    On 2xx success, ``external_ref`` is set from the response JSON ``id`` field
    (if present).
    """
    endpoint = f"{url.rstrip('/')}/message"
    payload: dict[str, Any] = {
        "title": title,
        "message": message,
        "priority": priority,
    }
    headers: dict[str, str] = {"X-Gotify-Key": token}
    if extra_headers:
        headers.update(extra_headers)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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
            return ExecutionResult(
                ok=False,
                detail=f"Gotify client error: {response.status_code} {response.text}",
                retryable=False,
            )
        else:
            return ExecutionResult(
                ok=False,
                detail=f"Gotify server error: {response.status_code} {response.text}",
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
