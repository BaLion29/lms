"""Tests for GotifyChannel notification delivery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import respx
from httpx import Response

from firnline_core.plugins import (
    ModuleRequirement,
    NotificationChannel,
    NotifyContext,
    validate_plugin,
)

from firnline_ext_gotify.channel import GotifyChannel, GotifySettings, plugin


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_plugin_is_notification_channel() -> None:
    """plugin instance passes isinstance check against NotificationChannel."""
    assert isinstance(plugin, NotificationChannel)


def test_plugin_name_and_requires() -> None:
    """plugin has the correct name and requires."""
    assert plugin.name == "gotify"
    assert len(plugin.requires) == 1
    assert isinstance(plugin.requires[0], ModuleRequirement)
    assert plugin.requires[0].name == "triggers"
    assert plugin.requires[0].range == ">=0.1.0 <0.2.0"


def test_validate_plugin_returns_empty() -> None:
    """Structural validation against NotificationChannel returns no violations."""
    violations = validate_plugin(plugin, NotificationChannel)
    assert violations == []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_env_prefix() -> None:
    """GotifySettings uses GOTIFY_ env prefix."""
    assert GotifySettings.model_config.get("env_prefix") == "GOTIFY_"


def test_settings_defaults() -> None:
    """GotifySettings has sensible defaults."""
    s = GotifySettings()
    assert s.url == ""
    assert s.token == ""
    assert s.priority == 5
    assert s.timeout_seconds == 10.0


# ---------------------------------------------------------------------------
# Lazy settings loading
# ---------------------------------------------------------------------------


def test_import_works_without_env_vars() -> None:
    """Module-level plugin import succeeds without GOTIFY_* env vars."""
    # Already imported at top of file — if we got here, it works.
    assert plugin is not None
    # Accessing settings should work (lazy init with defaults)
    s = plugin.settings
    assert s.url == ""


# ---------------------------------------------------------------------------
# Missing config
# ---------------------------------------------------------------------------


async def test_missing_config_returns_not_retryable() -> None:
    """When url/token are empty, deliver returns not-retryable without HTTP call."""
    channel = GotifyChannel()
    # Ensure settings are blank
    channel.settings  # noqa: B018  # force lazy init
    channel._settings = GotifySettings(url="", token="", priority=5, timeout_seconds=10)

    ctx = NotifyContext(tdb=None, logger=MagicMock())

    result = await channel.deliver({"scheduled_for": "2026-07-07T10:00:00Z"}, {"name": "Test"}, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "not configured" in result.detail.lower()


async def test_missing_url_only() -> None:
    """When url is empty but token is set, still returns not-retryable."""
    channel = GotifyChannel()
    channel._settings = GotifySettings(url="", token="abc123", priority=5, timeout_seconds=10)
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    result = await channel.deliver({}, None, ctx)

    assert result.ok is False
    assert result.retryable is False


async def test_missing_token_only() -> None:
    """When token is empty but url is set, still returns not-retryable."""
    channel = GotifyChannel()
    channel._settings = GotifySettings(url="https://gotify.example.com", token="", priority=5, timeout_seconds=10)
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    result = await channel.deliver({}, None, ctx)

    assert result.ok is False
    assert result.retryable is False


# ---------------------------------------------------------------------------
# Subject → title fallback chain
# ---------------------------------------------------------------------------


async def test_subject_name_used_for_title(monkeypatch):
    """subject.get('name') is used as title."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={})
        )
        result = await channel.deliver({}, {"name": "Walk dog", "@type": "Task"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Walk dog"


async def test_subject_title_fallback(monkeypatch):
    """subject.get('title') is used when 'name' is absent."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={})
        )
        result = await channel.deliver({}, {"title": "Team meeting"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Team meeting"


async def test_subject_type_fallback(monkeypatch):
    """subject.get('@type') is used when 'name'/'title' are absent."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={})
        )
        result = await channel.deliver({}, {"@type": "Task"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Task"


async def test_subject_id_fallback(monkeypatch):
    """subject.get('@id') is used when nothing else is present."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={})
        )
        result = await channel.deliver({}, {"@id": "Task/abc123"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Task/abc123"


async def test_subject_none_title_fallback(monkeypatch):
    """When subject is None, default title is used."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={})
        )
        result = await channel.deliver({}, None, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Firnline reminder"


# ---------------------------------------------------------------------------
# Successful delivery
# ---------------------------------------------------------------------------


async def test_successful_delivery(monkeypatch):
    """2xx response → DeliveryResult(ok=True)."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(
            return_value=Response(200, json={"id": 42})
        )
        result = await channel.deliver(
            {"scheduled_for": "2026-07-07T10:00:00Z", "occurrence_key": "abc"},
            {"name": "Test"},
            ctx,
        )

    assert result.ok is True
    assert "200" in result.detail

    # Assert URL, header, payload shape
    request = route.calls.last.request
    assert str(request.url) == "https://gotify.example.com/message"
    assert request.headers["X-Gotify-Key"] == "test-token"
    payload = json.loads(request.content)
    assert payload["title"] == "Test"
    assert "Scheduled" in payload["message"]
    assert "abc" in payload["message"]
    assert payload["priority"] == 5


# ---------------------------------------------------------------------------
# 500 → retryable
# ---------------------------------------------------------------------------


async def test_500_retryable(monkeypatch):
    """Server error → DeliveryResult(ok=False, retryable=True)."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(
            return_value=Response(500, json={"error": "boom"})
        )
        result = await channel.deliver({}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "500" in result.detail


# ---------------------------------------------------------------------------
# 401 → not retryable
# ---------------------------------------------------------------------------


async def test_401_not_retryable(monkeypatch):
    """Client error (401) → DeliveryResult(ok=False, retryable=False)."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(
            return_value=Response(401, json={"error": "unauthorized"})
        )
        result = await channel.deliver({}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "401" in result.detail


# ---------------------------------------------------------------------------
# Timeout → retryable
# ---------------------------------------------------------------------------


async def test_timeout_retryable(monkeypatch):
    """Network timeout → DeliveryResult(ok=False, retryable=True)."""
    channel = _configured_channel()
    ctx = NotifyContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(side_effect=httpx.TimeoutException("timed out"))
        result = await channel.deliver({}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "timeout" in result.detail.lower() or "network" in result.detail.lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configured_channel() -> GotifyChannel:
    """Return a GotifyChannel pre-configured with test settings."""
    channel = GotifyChannel()
    channel._settings = GotifySettings(
        url="https://gotify.example.com",
        token="test-token",
        priority=5,
        timeout_seconds=10,
    )
    return channel
