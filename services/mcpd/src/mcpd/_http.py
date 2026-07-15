"""Shared HTTP helpers for mcpd — builds clients and sanitises errors."""

from __future__ import annotations

import httpx
from mcp.server.fastmcp.exceptions import ToolError


def build_client(base_url: str, token: str, timeout: float) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient with optional bearer auth."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)


def raise_for_status(resp: httpx.Response) -> None:
    """Like resp.raise_for_status() but with sanitized messages — never leaks
    headers, URL credentials, or full request details into the error."""
    if resp.is_success:
        return
    detail: str = f"HTTP {resp.status_code}"
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
    except Exception:
        pass
    raise ToolError(str(detail))
