"""Chat state — AI chat via the queryd backend."""

from __future__ import annotations

import logging
from urllib.parse import quote

import reflex as rx

from firnline_webui.clients import QuerydClient, WebuiClientError
from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

logger = logging.getLogger(__name__)

_settings = get_settings()


def _make_queryd() -> QuerydClient:
    """Return a QuerydClient with a timeout suitable for LLM calls."""
    return QuerydClient(
        _settings.queryd_url,
        _settings.queryd_api_token,
        timeout=max(_settings.request_timeout_seconds, 120.0),
    )


class ChatState(BaseState):
    """State for the /chat page."""

    messages: list[dict[str, str]] = []
    input_text: str = ""
    sending: bool = False
    error: str = ""
    _query_consumed: bool = False

    @rx.event
    async def send(self):
        """Send the current input as a user message and get an AI reply."""
        if not self.input_text.strip() or self.sending:
            return
        self.messages = self.messages + [{"role": "user", "content": self.input_text}]
        self.input_text = ""
        yield
        await self._do_send()
        yield

    @rx.event
    async def init_from_query(self):
        """On mount, auto-send if a ``?q=...`` param is present and not consumed."""
        q = self.router.page.params.get("q", "")
        if q and not self._query_consumed:
            self._query_consumed = True
            if not self.messages:
                self.input_text = q
                self.messages = self.messages + [{"role": "user", "content": q}]
                self.input_text = ""
                yield
                await self._do_send()
                yield

    async def _do_send(self):
        """Shared core: call the backend and append response or set error."""
        self.sending = True
        self.error = ""
        try:
            client = _make_queryd()
            result = await client.chat(self.messages)
            self.messages = self.messages + [{"role": "assistant", "content": result.get("message", "")}]
        except WebuiClientError as exc:
            self.error = exc.detail
        except Exception:
            logger.exception("unexpected error talking to queryd")
            self.error = "unexpected error talking to queryd"
        finally:
            self.sending = False

    @rx.event
    def set_input(self, value: str):
        """Set the input text."""
        self.input_text = value

    @rx.event
    async def clear(self):
        """Reset messages, error, and query-consumed flag."""
        self.messages = []
        self.error = ""
        self._query_consumed = False
        yield


class HomeChatState(BaseState):
    """Tiny state for the "Quick Chat" card on the home page."""

    home_prompt: str = ""

    @rx.event
    def set_home_prompt(self, value: str):
        """Set the prompt text."""
        self.home_prompt = value

    @rx.event
    def go(self, form_data: dict | None = None):
        """Redirect to the chat page with the prompt as a query parameter."""
        if not self.home_prompt.strip():
            return
        return rx.redirect(f"/chat?q={quote(self.home_prompt)}")
