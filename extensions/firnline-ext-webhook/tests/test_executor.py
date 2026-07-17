"""Tests for WebhookExecutor — reference ActionExecutor for webhooks."""

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

from firnline_ext_webhook.executor import WebhookExecutor, WebhookSettings, plugin


# ── Public IP used in mock DNS resolution ────────────────────────────────
_PUBLIC_IP = "93.184.216.34"  # example.com (IPv4)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_plugin_is_action_executor() -> None:
    """plugin instance passes isinstance check against ActionExecutor."""
    assert isinstance(plugin, ActionExecutor)


def test_plugin_name_requires_kinds() -> None:
    """plugin has correct name, requires, and kinds."""
    assert plugin.name == "webhook"
    assert plugin.kinds == ("webhook",)
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
# Settings
# ---------------------------------------------------------------------------


def test_settings_env_prefix() -> None:
    """WebhookSettings uses WEBHOOK_ env prefix."""
    assert WebhookSettings.model_config.get("env_prefix") == "WEBHOOK_"


def test_settings_defaults() -> None:
    """WebhookSettings has sensible defaults."""
    s = WebhookSettings()
    assert s.default_token == ""
    assert s.timeout_seconds == 10.0


# ---------------------------------------------------------------------------
# Lazy settings loading
# ---------------------------------------------------------------------------


def test_import_works_without_env_vars() -> None:
    """Module-level plugin import succeeds without WEBHOOK_* env vars."""
    assert plugin is not None
    s = plugin.settings
    assert s.default_token == ""


# ---------------------------------------------------------------------------
# Missing URL — config error, not retryable
# ---------------------------------------------------------------------------


async def test_missing_url_config_error() -> None:
    """When action url is empty, execute returns not-retryable without HTTP call."""
    executor = WebhookExecutor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute(
        {"url": ""}, {"scheduled_for": "2026-07-07T10:00:00Z"}, {"name": "Test"}, ctx
    )

    assert result.ok is False
    assert result.retryable is False
    assert "missing" in result.detail.lower() or "empty" in result.detail.lower()


async def test_missing_url_key() -> None:
    """When action has no url key at all, returns not-retryable."""
    executor = WebhookExecutor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute({}, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is False


# ---------------------------------------------------------------------------
# Dry run — zero HTTP calls
# ---------------------------------------------------------------------------


async def test_dry_run_no_http_call() -> None:
    """ctx.dry_run=True returns ok without making any HTTP call."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), dry_run=True)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://example.com/hook").respond(200)
        result = await executor.execute(
            {"url": "https://example.com/hook"}, {}, {"name": "X"}, ctx
        )

    assert result.ok is True
    assert result.detail == "dry_run"
    assert route.call_count == 0


# ---------------------------------------------------------------------------
# 2xx success — default payload + idempotency header + no auth when unset
# ---------------------------------------------------------------------------


async def test_successful_delivery_default_payload() -> None:
    """2xx with default payload shape, idempotency header, no auth when token unset."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-1")

    action = {"url": "https://example.com/hook", "name": "my-action"}
    firing = {"@id": "Firing/f1", "status": "pending", "scheduled_for": "2026-07-07T10:00:00Z"}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://example.com/hook").mock(
            return_value=Response(200, json={"ok": True})
        )
        result = await executor.execute(action, firing, {"name": "Test subject"}, ctx)

    assert result.ok is True
    assert "200" in result.detail

    request = route.calls.last.request
    assert str(request.url) == "https://example.com/hook"
    assert request.headers["X-Firnline-Idempotency-Key"] == "ik-1"
    assert "Authorization" not in request.headers

    payload = json.loads(request.content)
    assert payload["action_name"] == "my-action"
    assert payload["idempotency_key"] == "ik-1"
    assert payload["firing"]["@id"] == "Firing/f1"
    assert payload["subject"]["name"] == "Test subject"


async def test_success_with_location_external_ref() -> None:
    """external_ref is set from response Location header."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-2")

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            return_value=Response(201, headers={"Location": "https://example.com/resource/42"})
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok
    assert result.external_ref == "https://example.com/resource/42"


async def test_success_without_location_header() -> None:
    """external_ref is None when Location header is absent."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(return_value=Response(200))
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok
    assert result.external_ref is None


# ---------------------------------------------------------------------------
# Bearer header when token set
# ---------------------------------------------------------------------------


async def test_bearer_header_when_token_set() -> None:
    """Authorization: Bearer header is sent when WEBHOOK_DEFAULT_TOKEN is set."""
    executor = _configured_executor(token="secret-token")
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-3")

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://example.com/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.headers["X-Firnline-Idempotency-Key"] == "ik-3"


# ---------------------------------------------------------------------------
# payload_template rendering
# ---------------------------------------------------------------------------


async def test_payload_template_rendered() -> None:
    """payload_template is rendered and sent as the request body."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-4")

    action = {
        "url": "https://example.com/hook",
        "payload_template": '{"msg": "$action_name via $idempotency_key"}',
        "name": "my-action",
    }
    firing = {}

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://example.com/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(action, firing, None, ctx)

    assert result.ok
    request = route.calls.last.request
    body = request.content.decode()
    assert "my-action" in body
    assert "ik-4" in body


# ---------------------------------------------------------------------------
# http_method override
# ---------------------------------------------------------------------------


async def test_http_method_override_put() -> None:
    """action.http_method overrides default POST."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-5")

    action = {
        "url": "https://example.com/hook",
        "http_method": "PUT",
    }

    with respx.mock(assert_all_called=False) as mock:
        route = mock.put("https://example.com/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok
    request = route.calls.last.request
    assert request.method == "PUT"


async def test_http_method_lowercase_normalised() -> None:
    """Lowercase http_method is uppercased."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {
        "url": "https://example.com/hook",
        "http_method": "post",
    }

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://example.com/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok
    request = route.calls.last.request
    assert request.method == "POST"


# ---------------------------------------------------------------------------
# 4xx → not retryable
# ---------------------------------------------------------------------------


async def test_4xx_not_retryable() -> None:
    """Client error (404) → ExecutionResult(ok=False, retryable=False)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            return_value=Response(404, json={"error": "not found"})
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "404" in result.detail


# ---------------------------------------------------------------------------
# 5xx → retryable
# ---------------------------------------------------------------------------


async def test_5xx_retryable() -> None:
    """Server error (500) → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            return_value=Response(500, json={"error": "boom"})
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "500" in result.detail


# ---------------------------------------------------------------------------
# Connect error → retryable
# ---------------------------------------------------------------------------


async def test_connect_error_retryable() -> None:
    """httpx.ConnectError → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "network" in result.detail.lower()


# ---------------------------------------------------------------------------
# Timeout → retryable
# ---------------------------------------------------------------------------


async def test_timeout_retryable() -> None:
    """Network timeout → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "timeout" in result.detail.lower()


# ---------------------------------------------------------------------------
# Catch-all exception → retryable
# ---------------------------------------------------------------------------


async def test_unexpected_exception_retryable() -> None:
    """Unexpected Exception → ExecutionResult(ok=False, retryable=True)."""
    executor = _configured_executor()
    ctx = ActionContext(tdb=None, logger=MagicMock())

    action = {"url": "https://example.com/hook"}

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            side_effect=RuntimeError("something wild happened")
        )
        result = await executor.execute(action, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is True


# ---------------------------------------------------------------------------
# SSRF guard — WEBHOOK_ALLOWED_HOSTS enforcement (S-4)
# ---------------------------------------------------------------------------


async def test_allowlist_empty_fails_closed() -> None:
    """When WEBHOOK_ALLOWED_HOSTS is empty, webhooks are refused."""
    executor = _configured_executor(allowed_hosts="")
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute(
        {"url": "https://example.com/hook"}, {}, None, ctx
    )

    assert result.ok is False
    assert result.retryable is False
    assert "empty" in result.detail.lower() or "allow" in result.detail.lower()


async def test_allowlist_host_not_matched() -> None:
    """Host not in the allowlist is rejected."""
    executor = _configured_executor(allowed_hosts="example.com")
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute(
        {"url": "https://evil.example.com/hook"}, {}, None, ctx
    )

    assert result.ok is False
    assert result.retryable is False
    assert "not in" in result.detail.lower()


async def test_allowlist_host_matched_allows() -> None:
    """Host in the allowlist passes the guard."""
    executor = _configured_executor(allowed_hosts="example.com")
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-ok")

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(
            {"url": "https://example.com/hook"}, {}, None, ctx
        )

    assert result.ok is True


async def test_allowlist_port_mismatch_rejected() -> None:
    """When allowlist specifies a port, requests to other ports are rejected."""
    executor = _configured_executor(allowed_hosts="example.com:443")
    ctx = ActionContext(tdb=None, logger=MagicMock())

    result = await executor.execute(
        {"url": "https://example.com:8080/hook"}, {}, None, ctx
    )

    assert result.ok is False
    assert result.retryable is False


async def test_allowlist_port_match_passes() -> None:
    """When allowlist specifies a port, requests to that port pass."""
    executor = _configured_executor(allowed_hosts="example.com:443")
    ctx = ActionContext(tdb=None, logger=MagicMock(), idempotency_key="ik-port")

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com:443/hook").mock(
            return_value=Response(200)
        )
        result = await executor.execute(
            {"url": "https://example.com:443/hook"}, {}, None, ctx
        )

    assert result.ok is True


async def test_private_ip_blocked(monkeypatch) -> None:
    """URL whose hostname resolves to a private IP is blocked."""
    executor = _configured_executor(allowed_hosts="localhost,127.0.0.1,internal")
    ctx = ActionContext(tdb=None, logger=MagicMock())

    # Override the mock DNS for this test to return a private IP
    import firnline_ext_webhook.executor as exec_mod

    async def fake_private_resolve(hostname: str, port: int):
        return [(2, 1, 6, "", ("10.0.0.1", port))]

    monkeypatch.setattr(exec_mod, "_resolve_addrs", fake_private_resolve)

    result = await executor.execute(
        {"url": "https://internal/hook"}, {}, None, ctx
    )

    assert result.ok is False
    assert "private" in result.detail.lower() or "loopback" in result.detail.lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configured_executor(token: str = "", allowed_hosts: str = "example.com") -> WebhookExecutor:
    """Return a WebhookExecutor pre-configured with test settings."""
    executor = WebhookExecutor()
    executor._settings = WebhookSettings(
        default_token=token,
        timeout_seconds=10,
        allowed_hosts=allowed_hosts,
    )
    return executor
