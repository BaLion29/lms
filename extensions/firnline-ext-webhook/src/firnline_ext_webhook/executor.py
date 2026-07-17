"""Webhook reference ActionExecutor plugin.

Entry-point group: ``firnline.effectd.executors``
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from firnline_core.plugins import ActionContext, ExecutionResult, ModuleRequirement
from firnline_core.templates import default_webhook_payload, render as render_template

logger = logging.getLogger(__name__)


# ── Private / loopback / link-local IP ranges (SSRF guard) ───────────────
# NOTE: This validates resolved IPs at check time; httpx re-resolves at
# connect time, so a DNS-rebinding attack (allowlisted host flips to a
# private IP between check and connect) is not fully mitigated. The
# fail-closed hostname allowlist is the primary SSRF defense; this IP
# check is defense-in-depth. Full IP-pinning would require a custom
# httpx transport (complicated by TLS SNI) — deferred to a future release.

# CGNAT (100.64.0.0/10) is not covered by ipaddress.is_private in
# Python < 3.13, so we check it explicitly.
_CGNAT = ipaddress.IPv4Network("100.64.0.0/10")


def _is_private_or_loopback(addr: str) -> bool:
    """Return True if *addr* is in a private / loopback / link-local range.

    Uses ipaddress predicates (``is_private``, ``is_loopback``,
    ``is_link_local``, ``is_unspecified``) which cover all RFC 1918
    ranges (10/8, 172.16/12, 192.168/16), loopback (127/8), link-local
    (169.254/16), and unspecified (0/8). CGNAT (100.64/10) is checked
    explicitly for Python < 3.13 compat.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False  # not a valid IP, let it pass (hostname without resolution)

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return True
    # CGNAT — not covered by is_private in Python < 3.13
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return True
    return False


def _parse_allowed_hosts(raw: str) -> dict[str, set[int]]:
    """Parse ``host:port,host,...`` into ``{hostname: set_of_ports_or_empty}``.

    An empty set means *any port* is permitted for that host.
    """
    result: dict[str, set[int]] = {}
    if not raw.strip():
        return result
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            # Could be hostname:port or IPv6 — check if the part after the last colon is numeric
            host, _, port_str = entry.rpartition(":")
            try:
                port = int(port_str)
            except ValueError:
                # Likely IPv6 without port — treat as bare host
                result[entry.lower()] = set()
                continue
            if port < 1 or port > 65535:
                # Not a valid port — treat as bare host
                result[entry.lower()] = set()
                continue
            result.setdefault(host.lower(), set()).add(port)
        else:
            result.setdefault(entry.lower(), set())
    return result


def _host_matches_allowlist(hostname: str, port: int | None, allowed: dict[str, set[int]]) -> bool:
    """Check whether a (hostname, port) pair matches the allowlist."""
    host_lower = hostname.lower()
    if host_lower not in allowed:
        return False
    allowed_ports = allowed[host_lower]
    if not allowed_ports:
        # No port restriction — any port is fine
        return True
    if port is None:
        return False  # no port on URL but allowlist requires one
    return port in allowed_ports


async def _resolve_addrs(hostname: str, port: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """Resolve *hostname* to a list of ``getaddrinfo``-style tuples.

    Extracted to a standalone async function so tests can mock it easily.
    """
    loop = __import__("asyncio").get_running_loop()
    return await loop.getaddrinfo(hostname, port)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class WebhookSettings(BaseSettings):
    """Webhook settings, loaded from WEBHOOK_* env vars."""

    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    default_token: str = ""
    """Optional static bearer token sent only when the host is allowlisted."""

    timeout_seconds: float = 10.0

    allowed_hosts: str = ""
    """Comma-separated allowed host:port values (hostname or IP).

    When empty, webhooks are **refused** (fail-closed).  Each entry may
    include an optional ``:<port>`` (e.g. ``example.com:443``); without
    a port any port is permitted.  The hostname is resolved and its IPs
    are checked against private/loopback/link-local ranges.
    """


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

        # ── SSRF guard: hostname allowlist + private IP check ────────────
        allowed = _parse_allowed_hosts(settings.allowed_hosts)
        if not allowed:
            return ExecutionResult(
                ok=False,
                detail=(
                    "Webhook rejected: WEBHOOK_ALLOWED_HOSTS is empty. "
                    "Configure a comma-separated list of allowed hosts "
                    "(e.g. 'hooks.example.com,api.example.com:443')."
                ),
                retryable=False,
            )

        try:
            parsed = urlparse(url)
        except Exception:
            return ExecutionResult(
                ok=False,
                detail=f"Webhook URL is not parseable: {url!r}",
                retryable=False,
            )

        hostname = parsed.hostname
        port = parsed.port

        if not hostname:
            return ExecutionResult(
                ok=False,
                detail=f"Webhook URL has no hostname: {url!r}",
                retryable=False,
            )

        if not _host_matches_allowlist(hostname, port, allowed):
            return ExecutionResult(
                ok=False,
                detail=(
                    f"Webhook host {hostname!r} (with port {port}) "
                    "is not in WEBHOOK_ALLOWED_HOSTS."
                ),
                retryable=False,
            )

        # Resolve hostname & reject private/loopback/link-local IPs
        try:
            addrinfo = await _resolve_addrs(hostname, port or 80)
        except socket.gaierror:
            return ExecutionResult(
                ok=False,
                detail=f"Webhook hostname {hostname!r} could not be resolved.",
                retryable=False,
            )

        for family, _type, _proto, _canonname, sockaddr in addrinfo:
            ip = sockaddr[0]
            if _is_private_or_loopback(ip):
                return ExecutionResult(
                    ok=False,
                    detail=(
                        f"Webhook hostname {hostname!r} resolved to a "
                        f"private/loopback IP ({ip}) — blocked by SSRF guard."
                    ),
                    retryable=False,
                )

        # Host is allowlisted and passes the IP check → safe to proceed

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
