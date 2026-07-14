"""Tests for firnline_webui.clients using httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from firnline_core.tdb import TdbError
from firnline_webui.clients import (
    CapturedClient,
    QuerydClient,
    ServiceHealthClient,
    TdbBrowser,
    WebuiClientError,
    class_display_fields,
    schema_classes,
)


# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------


def _ok_json(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body)


def _created_json(body: dict) -> httpx.Response:
    return httpx.Response(201, json=body)


def _degraded_json(body: dict) -> httpx.Response:
    return httpx.Response(503, json=body)


def _unauthorized(detail: str = "unauthorized") -> httpx.Response:
    return httpx.Response(401, json={"detail": detail})


def _text(status: int, text: str) -> httpx.Response:
    return httpx.Response(status, content=text.encode(), headers={"content-type": "text/plain"})


# ---------------------------------------------------------------------------
# CapturedClient
# ---------------------------------------------------------------------------


async def test_captured_healthz_200():
    transport = httpx.MockTransport(lambda req: _ok_json({"status": "ok"}))
    client = CapturedClient("http://x", "tok", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


async def test_captured_healthz_503():
    transport = httpx.MockTransport(lambda req: _degraded_json({"status": "degraded"}))
    client = CapturedClient("http://x", "tok", transport=transport)
    data = await client.healthz()
    assert data == {"status": "degraded"}


async def test_captured_healthz_non_json():
    transport = httpx.MockTransport(lambda req: _text(200, "not json"))
    client = CapturedClient("http://x", "tok", transport=transport)
    with pytest.raises(WebuiClientError) as exc_info:
        await client.healthz()
    assert exc_info.value.status == 200
    assert "non-JSON" in exc_info.value.detail


async def test_capture_note_happy_path():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer mytoken"
        body = json.loads(req.read())
        assert body["text"] == "hello"
        assert body["kind"] == "note"
        return _created_json({"id": "abc", "kind": "note"})

    client = CapturedClient("http://x", "mytoken", transport=httpx.MockTransport(handler))
    data = await client.capture_note("hello")
    assert data["id"] == "abc"


async def test_capture_note_401():
    transport = httpx.MockTransport(lambda req: _unauthorized("bad token"))
    client = CapturedClient("http://x", "tok", transport=transport)
    with pytest.raises(WebuiClientError) as exc_info:
        await client.capture_note("hi")
    assert exc_info.value.status == 401


async def test_capture_note_with_metadata():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.read())
        assert body["metadata"] == {"tags": ["a"]}
        return _created_json({"id": "x"})

    client = CapturedClient("http://x", "tok", transport=httpx.MockTransport(handler))
    data = await client.capture_note("hi", metadata={"tags": ["a"]})
    assert data["id"] == "x"


async def test_capture_file_happy_path():
    def handler(req: httpx.Request) -> httpx.Response:
        ct = req.headers.get("content-type", "")
        assert "multipart/form-data" in ct
        return _created_json({"id": "f1", "kind": "file"})

    client = CapturedClient("http://x", "tok", transport=httpx.MockTransport(handler))
    data = await client.capture_file("test.txt", b"hello", "text/plain")
    assert data["id"] == "f1"


async def test_capture_file_with_metadata():
    def handler(req: httpx.Request) -> httpx.Response:
        return _created_json({"id": "f2"})

    client = CapturedClient("http://x", "tok", transport=httpx.MockTransport(handler))
    data = await client.capture_file("test.txt", b"hello", "text/plain", metadata={"k": "v"})
    assert data["id"] == "f2"


# ---------------------------------------------------------------------------
# QuerydClient
# ---------------------------------------------------------------------------


async def test_queryd_healthz():
    transport = httpx.MockTransport(lambda req: _ok_json({"status": "ok"}))
    client = QuerydClient("http://q", "tok", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


# ---------------------------------------------------------------------------
# ServiceHealthClient (indexed + mcpd)
# ---------------------------------------------------------------------------


async def test_indexed_healthz():
    transport = httpx.MockTransport(lambda req: _ok_json({"status": "ok"}))
    client = ServiceHealthClient("http://i", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


async def test_indexed_healthz_injects_bearer_token():
    """When token is non-empty, the Authorization header is included."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer my-indexed-token"
        return _ok_json({"status": "ok"})

    transport = httpx.MockTransport(handler)
    client = ServiceHealthClient("http://i", token="my-indexed-token", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


async def test_indexed_healthz_no_token_when_empty():
    """When token is empty, no Authorization header is sent."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return _ok_json({"status": "ok"})

    transport = httpx.MockTransport(handler)
    client = ServiceHealthClient("http://i", token="", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


async def test_mcpd_healthz():
    transport = httpx.MockTransport(lambda req: _ok_json({"status": "ok"}))
    client = ServiceHealthClient("http://mcpd:8090", transport=transport)
    data = await client.healthz()
    assert data == {"status": "ok"}


async def test_mcpd_healthz_transport_error():
    """Transport errors raise WebuiClientError with status None."""

    async def failing_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(failing_handler)
    client = ServiceHealthClient("http://mcpd:8090", transport=transport)
    with pytest.raises(WebuiClientError) as exc_info:
        await client.healthz()
    assert exc_info.value.status is None
    assert "transport error" in exc_info.value.detail


# ---------------------------------------------------------------------------
# schema_classes
# ---------------------------------------------------------------------------


def test_schema_classes_filters():
    schema = [
        {"@type": "Class", "@id": "Person", "name": "xsd:string"},
        {"@type": "Enum", "@id": "Status", "@value": ["a", "b"]},
        {"@type": "Context"},
        {"@type": "Class", "@id": "Event", "name": "xsd:string", "date": "xsd:dateTime"},
    ]
    result = schema_classes(schema)
    assert len(result) == 2
    assert result[0]["@id"] == "Person"
    assert result[1]["@id"] == "Event"


def test_schema_classes_empty():
    assert schema_classes([]) == []


def test_schema_classes_no_classes():
    schema = [{"@type": "Enum", "@id": "X"}]
    assert schema_classes(schema) == []


# ---------------------------------------------------------------------------
# class_display_fields
# ---------------------------------------------------------------------------


def test_class_display_fields_preferred_first():
    class_def = {
        "@id": "Person",
        "@type": "Class",
        "name": "xsd:string",
        "status": "xsd:string",
        "other": "xsd:string",
        "title": "xsd:string",
    }
    fields = class_display_fields(class_def)
    # Preferred order: name, title, text, status, kind, created_at, updated_at
    # Present: name, title, status → then remaining alphabetically: other
    assert fields == ["name", "title", "status", "other"]


def test_class_display_fields_caps_at_5():
    class_def = {
        "@id": "X",
        "@type": "Class",
        "name": "xsd:string",
        "title": "xsd:string",
        "text": "xsd:string",
        "status": "xsd:string",
        "kind": "xsd:string",
        "created_at": "xsd:dateTime",
        "updated_at": "xsd:dateTime",
        "zebra": "xsd:string",
    }
    fields = class_display_fields(class_def)
    assert fields == ["name", "title", "text", "status", "kind"]


def test_class_display_fields_fills_alphabetically():
    class_def = {
        "@id": "X",
        "@type": "Class",
        "zoo": "xsd:string",
        "aardvark": "xsd:string",
    }
    fields = class_display_fields(class_def)
    assert fields == ["aardvark", "zoo"]


def test_class_display_fields_no_fields():
    class_def = {"@id": "X", "@type": "Class"}
    assert class_display_fields(class_def) == []


# ---------------------------------------------------------------------------
# TdbBrowser — TdbError → WebuiClientError wrapping
# ---------------------------------------------------------------------------


class _FakeTdb:
    """Fake TdbClient that returns canned data or raises TdbError."""

    def __init__(self, *, raise_on: str | None = None) -> None:
        self._raise_on = raise_on
        self.aclose_called = False

    async def get_schema(self, branch: str = "main") -> list[dict]:
        if self._raise_on == "schema":
            raise TdbError(500, "schema boom")
        return [{"@type": "Class", "@id": "Person"}]

    async def get_documents(self, type_: str, branch: str = "main") -> list[dict]:
        if self._raise_on == "docs":
            raise TdbError(404, "docs not found")
        return [{"@type": type_, "@id": f"{type_}/1"}]

    async def get_document(self, iri: str, branch: str = "main") -> dict:
        if self._raise_on == "doc":
            raise TdbError(404, "doc not found")
        return {"@id": iri}

    async def aclose(self) -> None:
        self.aclose_called = True


async def test_tdb_browser_get_schema_happy():
    fake = _FakeTdb()
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    result = await browser.get_schema()
    assert result == [{"@type": "Class", "@id": "Person"}]


async def test_tdb_browser_get_schema_error_wrapping():
    fake = _FakeTdb(raise_on="schema")
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    with pytest.raises(WebuiClientError) as exc_info:
        await browser.get_schema()
    assert exc_info.value.status == 500
    assert exc_info.value.detail == "schema boom"


async def test_tdb_browser_get_modules():
    fake = _FakeTdb()
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    result = await browser.get_modules()
    assert result == [{"@type": "SchemaModule", "@id": "SchemaModule/1"}]


async def test_tdb_browser_get_documents():
    fake = _FakeTdb()
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    result = await browser.get_documents("Person")
    assert result == [{"@type": "Person", "@id": "Person/1"}]


async def test_tdb_browser_get_doc_error_wrapping():
    fake = _FakeTdb(raise_on="doc")
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    with pytest.raises(WebuiClientError) as exc_info:
        await browser.get_document("x/y")
    assert exc_info.value.status == 404


async def test_tdb_browser_aclose():
    fake = _FakeTdb()
    browser = TdbBrowser("http://x", "o", "d", "u", "p", tdb=fake)
    await browser.aclose()
    assert fake.aclose_called
