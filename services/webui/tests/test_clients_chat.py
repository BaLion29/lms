"""Tests for QuerydClient.chat using httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from firnline_webui.clients import QuerydClient, WebuiClientError


def _ok_json(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body)


def _unauthorized(detail: str = "unauthorized") -> httpx.Response:
    return httpx.Response(401, json={"detail": detail})


# ---------------------------------------------------------------------------
# QuerydClient.chat
# ---------------------------------------------------------------------------


async def test_chat_happy_path():
    """200 returns the response dict with message and tool_trace."""
    expected = {"message": "Hello back!", "tool_trace": []}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer mytoken"
        assert req.url.path == "/v1/chat"
        body = json.loads(req.read())
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        return _ok_json(expected)

    client = QuerydClient("http://q", "mytoken", transport=httpx.MockTransport(handler))
    result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == expected


async def test_chat_401_raises_webuiclienterror():
    """401 response raises WebuiClientError with status 401."""
    transport = httpx.MockTransport(lambda req: _unauthorized("bad token"))
    client = QuerydClient("http://q", "tok", transport=transport)
    with pytest.raises(WebuiClientError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.status == 401
    assert "bad token" in exc_info.value.detail


async def test_chat_transport_error():
    """Transport errors raise WebuiClientError with status None."""

    async def failing_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(failing_handler)
    client = QuerydClient("http://q", "tok", transport=transport)
    with pytest.raises(WebuiClientError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.status is None
    assert "transport error" in exc_info.value.detail
