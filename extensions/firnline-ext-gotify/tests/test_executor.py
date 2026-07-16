"""Tests for GotifyExecutor — native ActionExecutor seam."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import respx
from httpx import Response

from firnline_core.plugins import (
    ActionContext,
    ActionExecutor,
    validate_plugin,
)

from firnline_ext_gotify.executor import GotifyExecutor, GotifySettings, plugin


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_plugin_is_action_executor() -> None:
    """plugin instance passes isinstance check against ActionExecutor."""
    assert isinstance(plugin, ActionExecutor)


def test_plugin_name_requires_kinds() -> None:
    """plugin has correct name, requires, and kinds."""
    assert plugin.name == "gotify"
    assert plugin.kinds == ("notify:gotify",)
    assert len(plugin.requires) == 2
    req_names = {r.name for r in plugin.requires}
    assert req_names == {"triggers", "actions"}
    for r in plugin.requires:
        assert r.range == ">=0.1.0 <0.2.0"


def test_validate_plugin_returns_empty() -> None:
    """Structural validation against ActionExecutor returns no violations."""
    violations = validate_plugin(plugin, ActionExecutor)
    assert violations == []


# ---------------------------------------------------------------------------
# Settings (shared)
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
    assert plugin is not None
    s = plugin.settings
    assert s.url == ""


# ---------------------------------------------------------------------------
# Missing config
# ---------------------------------------------------------------------------


async def test_missing_config_returns_not_retryable() -> None:
    """When url/token are empty, execute returns not-retryable without HTTP call."""
    executor = GotifyExecutor()
    executor.settings  # noqa: B018  # force lazy init
    executor._settings = GotifySettings(url="", token="", priority=5, timeout_seconds=10)

    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute({}, {"scheduled_for": "2026-07-07T10:00:00Z"}, {"name": "Test"}, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "not configured" in result.detail.lower()


async def test_missing_url_only() -> None:
    """When url is empty but token is set, still returns not-retryable."""
    executor = GotifyExecutor()
    executor._settings = GotifySettings(url="", token="abc123", priority=5, timeout_seconds=10)
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute({}, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is False


async def test_missing_token_only() -> None:
    """When token is empty but url is set, still returns not-retryable."""
    executor = GotifyExecutor()
    executor._settings = GotifySettings(url="https://gotify.example.com", token="", priority=5, timeout_seconds=10)
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute({}, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is False


# ---------------------------------------------------------------------------
# Subject → title fallback chain (when no title_template)
# ---------------------------------------------------------------------------


async def test_subject_name_used_for_title(monkeypatch):
    """subject name is used as title when no title_template."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, {"name": "Walk dog"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Walk dog"


async def test_subject_title_fallback(monkeypatch):
    """subject title is used when name is absent and no title_template."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, {"title": "Team meeting"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Team meeting"


async def test_subject_type_fallback(monkeypatch):
    """@type used when name/title are absent."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, {"@type": "Task"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Task"


async def test_subject_id_fallback(monkeypatch):
    """@id used when nothing else is present."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, {"@id": "Task/abc123"}, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Task/abc123"


async def test_subject_none_title_fallback(monkeypatch):
    """When subject is None, default title used."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, None, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Firnline reminder"


# ---------------------------------------------------------------------------
# Template-based title/body rendering
# ---------------------------------------------------------------------------


async def test_title_template_rendered(monkeypatch):
    """title_template is rendered and used instead of subject fallback."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-abc")

    action = {"title_template": "Alert: $subject_label", "name": "my-action"}
    firing = {"@id": "Firing/f1", "status": "pending"}
    subject = {"name": "Walk dog"}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute(action, firing, subject, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert payload["title"] == "Alert: Walk dog"


async def test_body_template_rendered(monkeypatch):
    """body_template is rendered and used instead of firing-derived body."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-abc")

    action = {
        "body_template": "Firing $firing_id via $action_name",
        "name": "my-action",
    }
    firing = {"@id": "Firing/f1", "status": "pending"}
    subject = {"name": "Walk dog"}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute(action, firing, subject, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert "Firing/f1" in payload["message"]


async def test_template_vars_include_idempotency_key(monkeypatch):
    """idempotency_key variable is available in templates."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-xyz")

    action = {"body_template": "Key: $idempotency_key"}
    firing = {}
    subject = None

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute(action, firing, subject, ctx)

    assert result.ok
    payload = json.loads(route.calls.last.request.content)
    assert "ik-xyz" in payload["message"]


# ---------------------------------------------------------------------------
# Successful delivery — payload & headers
# ---------------------------------------------------------------------------


async def test_successful_delivery(monkeypatch):
    """2xx response → ExecutionResult(ok=True) with idempotency header."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-1")

    action = {}
    firing = {"scheduled_for": "2026-07-07T10:00:00Z", "occurrence_key": "abc"}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={"id": 42}))
        result = await executor.execute(action, firing, {"name": "Test"}, ctx)

    assert result.ok is True
    assert "200" in result.detail

    request = route.calls.last.request
    assert str(request.url) == "https://gotify.example.com/message"
    assert request.headers["X-Gotify-Key"] == "test-token"
    assert request.headers["X-Firnline-Idempotency-Key"] == "ik-1"

    payload = json.loads(request.content)
    assert payload["title"] == "Test"
    assert "Scheduled" in payload["message"]
    assert "abc" in payload["message"]
    assert payload["priority"] == 5


async def test_successful_delivery_with_external_ref(monkeypatch):
    """external_ref is set from response json id."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-2")

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={"id": 99}))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok
    assert result.external_ref == "99"


async def test_success_without_id_in_response(monkeypatch):
    """external_ref is None when response json has no id."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(200, json={}))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok
    assert result.external_ref is None


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


async def test_dry_run_no_http_call(monkeypatch):
    """ctx.dry_run=True returns ok without making any HTTP call, even when unconfigured."""
    executor = GotifyExecutor()
    executor._settings = GotifySettings(url="", token="", priority=5, timeout_seconds=10)
    ctx = ActionContext(tdb=None, logger=MagicMock(), dry_run=True)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://gotify.example.com/message").respond(200)
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is True
    assert result.detail == "dry_run"
    # Verify zero HTTP calls made
    assert route.call_count == 0


# ---------------------------------------------------------------------------
# 500 → retryable
# ---------------------------------------------------------------------------


async def test_500_retryable(monkeypatch):
    """Server error → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(500, json={"error": "boom"}))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "500" in result.detail


# ---------------------------------------------------------------------------
# 5xx response text truncation
# ---------------------------------------------------------------------------


async def test_5xx_text_truncation(monkeypatch):
    """Response text > 500 chars is truncated to 500 on 5xx error."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    long_text = "y" * 600
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(500, text=long_text))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "500" in result.detail
    assert "y" * 500 in result.detail
    assert "y" * 600 not in result.detail


# ---------------------------------------------------------------------------
# 401 → not retryable
# ---------------------------------------------------------------------------


async def test_401_not_retryable(monkeypatch):
    """Client error (401) → ExecutionResult(ok=False, retryable=False)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(401, json={"error": "unauthorized"}))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "401" in result.detail


# ---------------------------------------------------------------------------
# Timeout → retryable
# ---------------------------------------------------------------------------


async def test_timeout_retryable(monkeypatch):
    """Network timeout → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(side_effect=httpx.TimeoutException("timed out"))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "timeout" in result.detail.lower() or "network" in result.detail.lower()


# ---------------------------------------------------------------------------
# Connect error → retryable
# ---------------------------------------------------------------------------


async def test_connect_error_retryable(monkeypatch):
    """httpx.ConnectError → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(side_effect=httpx.ConnectError("connection refused"))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True


# ---------------------------------------------------------------------------
# Unexpected exception → retryable (catch-all)
# ---------------------------------------------------------------------------


async def test_unexpected_exception_retryable(monkeypatch):
    """Unexpected RuntimeError → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(side_effect=RuntimeError("boom"))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is True


# ---------------------------------------------------------------------------
# 4xx response text truncation
# ---------------------------------------------------------------------------


async def test_4xx_text_truncation(monkeypatch):
    """Response text > 500 chars is truncated to 500 on 4xx error."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    long_text = "x" * 600
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://gotify.example.com/message").mock(return_value=Response(404, text=long_text))
        result = await executor.execute({}, {}, {"name": "X"}, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "404" in result.detail
    # The text should be truncated to 500 chars
    assert "x" * 500 in result.detail
    assert "x" * 600 not in result.detail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configured_executor() -> GotifyExecutor:
    """Return a GotifyExecutor pre-configured with test settings."""
    executor = GotifyExecutor()
    executor._settings = GotifySettings(
        url="https://gotify.example.com",
        token="test-token",
        priority=5,
        timeout_seconds=10,
    )
    return executor
