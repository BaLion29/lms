"""Tests locking in try/finally cleanup guarantees in state handlers.

Specifically verifies that TdbBrowser.aclose() is awaited even when a
non-WebuiClientError is raised mid-load (fix #1 in inbox rework).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from firnline_core.tdb import TdbError
from firnline_webui.clients import TdbBrowser, WebuiClientError
from firnline_webui.state.inbox import InboxState, _load_inbox_rows


# ---------------------------------------------------------------------------
# Fake TdbBrowser building blocks
# ---------------------------------------------------------------------------


class _FakeTdb:
    """Drop-in for firnline_core TdbClient that records aclose calls."""

    def __init__(
        self,
        *,
        schema: list[dict] | None = None,
        docs: list[dict] | None = None,
        raise_runtime_on: str | None = None,
        raise_tdb_error_on: str | None = None,
        tdb_error: tuple[int, str] = (500, "boof"),
    ) -> None:
        if schema is None:
            schema = [
                {
                    "@type": "Class",
                    "@id": "Captured",
                    "content": "xsd:string",
                    "status": "xsd:string",
                    "captured_at": "xsd:dateTime",
                    "content_type": "xsd:string",
                }
            ]
        if docs is None:
            docs = [
                {
                    "@id": "Captured/1",
                    "status": "new",
                    "captured_at": "2025-01-01T00:00:00Z",
                    "content_type": "text/plain",
                    "content": "hello",
                }
            ]
        self._schema = schema
        self._docs = docs
        self._raise_runtime_on = raise_runtime_on
        self._raise_tdb_error_on = raise_tdb_error_on
        self._tdb_error = tdb_error
        self.aclose_called = False

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_runtime_on == "schema":
            raise RuntimeError("schema boom")
        if self._raise_tdb_error_on == "schema":
            raise TdbError(*self._tdb_error)
        return self._schema

    async def get_documents(self, type_: str, branch: str = "main") -> list[dict]:
        if self._raise_runtime_on == "docs":
            raise RuntimeError("docs boom")
        if self._raise_tdb_error_on == "docs":
            raise TdbError(*self._tdb_error)
        return self._docs

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        return {"@id": iri}

    async def aclose(self) -> None:
        self.aclose_called = True


def _make_fake_browser(fake_tdb: _FakeTdb) -> TdbBrowser:
    """Construct a TdbBrowser backed by *_fake_tdb*."""
    return TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake_tdb)


# ---------------------------------------------------------------------------
# _load_inbox_rows helper tests
# ---------------------------------------------------------------------------


async def test_helper_returns_rows_and_statuses():
    """Happy path: helper fetches schema, docs, and returns sorted rows + statuses."""
    fake = _FakeTdb()
    browser = _make_fake_browser(fake)

    rows, statuses = await _load_inbox_rows(browser)

    assert len(rows) == 1
    assert rows[0]["id"] == "Captured/1"
    assert rows[0]["status"] == "new"
    assert rows[0]["content_type"] == "text/plain"
    assert statuses == {"new"}


async def test_helper_empty_class_ids():
    """When no Captured class exists, returns empty results."""
    fake = _FakeTdb(schema=[])
    browser = _make_fake_browser(fake)

    rows, statuses = await _load_inbox_rows(browser)
    assert rows == []
    assert statuses == set()


async def test_helper_skips_webui_client_error_per_class():
    """Per-class WebuiClientError is silently skipped."""
    fake = _FakeTdb(raise_tdb_error_on="docs")
    browser = _make_fake_browser(fake)

    rows, statuses = await _load_inbox_rows(browser)
    assert rows == []
    assert statuses == set()


async def test_helper_propagates_runtime_error():
    """Non-WebuiClientError (e.g. RuntimeError) during get_documents propagates."""
    fake = _FakeTdb(raise_runtime_on="docs")
    browser = _make_fake_browser(fake)

    with pytest.raises(RuntimeError, match="docs boom"):
        await _load_inbox_rows(browser)

    # The helper itself does NOT own aclose — the handler does.
    assert not fake.aclose_called


async def test_helper_propagates_schema_webui_client_error():
    """WebuiClientError from get_schema propagates up (handled by caller)."""
    fake = _FakeTdb(raise_tdb_error_on="schema", tdb_error=(500, "schema boom"))
    browser = _make_fake_browser(fake)

    with pytest.raises(WebuiClientError) as exc_info:
        await _load_inbox_rows(browser)
    assert exc_info.value.detail == "schema boom"


# ---------------------------------------------------------------------------
# Handler cleanup tests — verifies try/finally in InboxState.load()
# ---------------------------------------------------------------------------


async def test_handler_closes_tdb_on_runtime_error():
    """InboxState.load() calls aclose even when _load_inbox_rows raises RuntimeError."""
    fake = _FakeTdb(raise_runtime_on="docs")
    browser = _make_fake_browser(fake)

    async def iter_handler():
        """Manually drive the async generator returned by InboxState.load."""
        state = InboxState()  # type: ignore[call-arg]
        gen = state.load()
        # Advance past the initial yield (loading=True, etc.)
        await gen.__anext__()
        # Then advance past the body — should raise RuntimeError which
        # Reflex would normally handle, but here we catch it to verify
        # aclose was already awaited.
        try:
            await gen.__anext__()
        except RuntimeError:
            pass
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.inbox.make_tdb_browser", return_value=browser):
        await iter_handler()

    assert fake.aclose_called, "aclose() must be awaited even after RuntimeError"


async def test_handler_closes_tdb_on_webui_client_error():
    """InboxState.load() calls aclose when get_schema raises WebuiClientError."""
    fake = _FakeTdb(raise_tdb_error_on="schema", tdb_error=(500, "schema dead"))
    browser = _make_fake_browser(fake)

    async def iter_handler():
        state = InboxState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.inbox.make_tdb_browser", return_value=browser):
        state = await iter_handler()

    assert fake.aclose_called, "aclose() must be awaited even on WebuiClientError"
    assert "schema dead" in state.error


async def test_handler_closes_tdb_on_success():
    """InboxState.load() calls aclose on the normal happy path too."""
    fake = _FakeTdb()
    browser = _make_fake_browser(fake)

    async def iter_handler():
        state = InboxState()  # type: ignore[call-arg]
        gen = state.load()
        await gen.__anext__()
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return state

    with patch("firnline_webui.state.inbox.make_tdb_browser", return_value=browser):
        state = await iter_handler()

    assert fake.aclose_called
    assert len(state.rows) == 1
    assert state.available_statuses == ["new"]
