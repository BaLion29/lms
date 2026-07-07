"""Tests for ChatState exception-safety guarantees."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from reflex.istate.data import HeaderData, PageData, RouterData, SessionData, ReflexURL

from firnline_webui.clients import QuerydClient, WebuiClientError
from firnline_webui.state.chat import ChatState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_queryd(*, raise_on_chat: Exception | None = None) -> QuerydClient:
    """Build a QuerydClient whose ``chat()`` can be controlled."""
    client = Mock(spec=QuerydClient)
    if raise_on_chat is None:
        client.chat = AsyncMock(return_value={"message": "Hello from AI", "tool_trace": []})
    else:
        client.chat = AsyncMock(side_effect=raise_on_chat)
    return client


def _make_router(params: dict | None = None) -> RouterData:
    """Build a RouterData with the given page params."""
    page = PageData(host="", path="", raw_path="", full_path="", full_raw_path="", params=params or {})
    return RouterData(
        session=SessionData(client_token="", client_ip="", session_id=""),
        headers=HeaderData(raw_headers={}),
        _page=page,
        url=ReflexURL(""),
        route_id="",
    )


# ---------------------------------------------------------------------------
# send() exception safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_happy_path():
    """Normal send: user message and assistant reply appended, sending=False at end."""
    state = ChatState()  # type: ignore[call-arg]
    state.input_text = "hi"

    with patch(
        "firnline_webui.state.chat._make_queryd",
        return_value=_fake_queryd(),
    ):
        gen = state.send()
        await gen.__anext__()  # first yield (after user message)
        try:
            await gen.__anext__()  # second yield (after _do_send)
        except StopAsyncIteration:
            pass

    assert state.sending is False
    assert state.error == ""
    assert len(state.messages) == 2
    assert state.messages[0] == {"role": "user", "content": "hi"}
    assert state.messages[1] == {"role": "assistant", "content": "Hello from AI"}


@pytest.mark.asyncio
async def test_send_webui_client_error():
    """WebuiClientError sets error but keeps user message, sending=False at end."""
    state = ChatState()  # type: ignore[call-arg]
    state.input_text = "boom"

    with patch(
        "firnline_webui.state.chat._make_queryd",
        return_value=_fake_queryd(raise_on_chat=WebuiClientError(503, "service unavailable")),
    ):
        gen = state.send()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    assert state.sending is False
    assert state.error == "service unavailable"
    assert len(state.messages) == 1
    assert state.messages[0] == {"role": "user", "content": "boom"}


@pytest.mark.asyncio
async def test_send_runtime_error_guarantees_sending_false():
    """Unexpected exception (RuntimeError) → sending=False and error set, user message kept."""
    state = ChatState()  # type: ignore[call-arg]
    state.input_text = "trigger crash"

    with patch(
        "firnline_webui.state.chat._make_queryd",
        return_value=_fake_queryd(raise_on_chat=RuntimeError("connection blown")),
    ):
        gen = state.send()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    assert state.sending is False, "sending must be False after any exception"
    assert state.error == "unexpected error talking to queryd"
    assert len(state.messages) == 1
    assert state.messages[0] == {"role": "user", "content": "trigger crash"}


@pytest.mark.asyncio
async def test_send_empty_input_no_op():
    """Empty/whitespace input should be a no-op, sending stays False."""
    state = ChatState()  # type: ignore[call-arg]
    state.input_text = "   "

    gen = state.send()
    # Early return means the generator is empty
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

    assert state.sending is False
    assert state.messages == []


# ---------------------------------------------------------------------------
# _query_consumed guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_from_query_sets_consumed_flag():
    """init_from_query must set _query_consumed=True after firing."""
    state = ChatState()  # type: ignore[call-arg]
    object.__setattr__(state, "router", _make_router({"q": "hello"}))

    with patch(
        "firnline_webui.state.chat._make_queryd",
        return_value=_fake_queryd(),
    ):
        gen = state.init_from_query()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    assert state._query_consumed is True
    assert len(state.messages) == 2


@pytest.mark.asyncio
async def test_init_from_query_skips_when_consumed():
    """init_from_query does nothing when _query_consumed is already True."""
    state = ChatState()  # type: ignore[call-arg]
    state._query_consumed = True
    object.__setattr__(state, "router", _make_router({"q": "hello"}))

    with patch(
        "firnline_webui.state.chat._make_queryd",
        return_value=_fake_queryd(),
    ):
        gen = state.init_from_query()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    assert state.messages == []
    assert state._query_consumed is True


@pytest.mark.asyncio
async def test_clear_resets_query_consumed():
    """clear() resets _query_consumed to False."""
    state = ChatState()  # type: ignore[call-arg]
    state._query_consumed = True
    state.messages = [{"role": "user", "content": "x"}]

    gen = state.clear()
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass

    assert state._query_consumed is False
    assert state.messages == []
