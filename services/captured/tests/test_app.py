"""Tests for captured.app: healthz, auth, capture endpoints, dispatch."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from firnline_core.conventions import BlobStore
from firnline_core.plugins import (
    CaptureContext,
    CaptureHandler,
    CapturePayload,
    DiscoveryResult,
    ModuleRequirement,
    PluginSelection,
)

from captured.app import create_app
from captured.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"


def _make_settings(**overrides) -> Settings:
    defaults: dict[str, object] = dict(
        api_token="test-token",
        tdb_db=TDB_DB,
        tdb_password="x",
        tdb_url=TDB_URL,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


# Fake TdbClient
class FakeTdbClient:
    def __init__(self) -> None:
        self.base_url = TDB_URL
        self.org = "admin"
        self.db = TDB_DB
        self.user = "admin"
        self.password = "x"

    async def db_exists(self) -> bool:
        return True

    async def get_documents(self, type_: str, branch: str = "main") -> list[dict]:
        return []

    async def aclose(self) -> None:
        pass


class FailingTdbClient(FakeTdbClient):
    async def db_exists(self) -> bool:
        raise ConnectionError("refused")


class FailingDocumentsTdbClient(FakeTdbClient):
    async def get_documents(self, type_: str, branch: str = "main") -> list[dict]:
        raise ConnectionError("refused")


# ── Fake handlers ──────────────────────────────────────────────────────────

class StubNoteHandler:
    name = "stub-note"
    kinds = ("note",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        if payload.text and payload.text == "fail-me":
            raise RuntimeError("simulated handler failure")
        return "stub-note-id"


class StubFileHandler:
    name = "stub-file"
    kinds = ("file", "image")
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        return "stub-file-id"


class StubConflictingHandler:
    name = "stub-conflict"
    kinds = ("note",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        return "stub-conflict-id"


# ── Async monkeypatch helpers for discover_plugins / select_plugins ───────


def _make_selection(*handlers: CaptureHandler) -> PluginSelection:
    return PluginSelection(active=[(h.name, h) for h in handlers], skipped=[])


def _make_discovery(*handlers: CaptureHandler) -> DiscoveryResult:
    return DiscoveryResult(active=[(h.name, h) for h in handlers], failed=[])


def _fake_discover_factory(result: DiscoveryResult):
    """Return a sync function that returns *result* (discover_plugins is sync)."""
    def _inner(group: str = "") -> DiscoveryResult:
        return result
    return _inner


def _fake_select_factory(result: PluginSelection):
    """Return an **async** function (select_plugins is async)."""
    async def _inner(tdb, discovered, *, strict=False, branch="main", protocol=None, registry=None):
        if strict and result.skipped:
            skipped_names = [n for n, _ in result.skipped]
            raise RuntimeError(
                f"Strict plugin mode: skipped={skipped_names}, failed=[]"
            )
        return result
    return _inner


# ── Client fixture providing a factory ────────────────────────────────────


def _patch_app(monkeypatch, *, handlers=None, tdb_client=None, selection=None, discovery=None):
    """Apply monkeypatches to captured.app for a single test."""
    import captured.app as app_mod

    tc = tdb_client if tdb_client is not None else FakeTdbClient()
    monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: tc)

    # PluginHost calls discover_plugins / select_plugins from firnline_core.plugins
    if discovery is not None:
        monkeypatch.setattr("firnline_core.plugins.discover_plugins", _fake_discover_factory(discovery))
    elif handlers is not None:
        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            _fake_discover_factory(_make_discovery(*handlers)),
        )
    else:
        monkeypatch.setattr(
            "firnline_core.plugins.discover_plugins",
            _fake_discover_factory(DiscoveryResult(active=[], failed=[])),
        )

    if selection is not None:
        monkeypatch.setattr("firnline_core.plugins.select_plugins", _fake_select_factory(selection))
    elif handlers is not None:
        monkeypatch.setattr(
            "firnline_core.plugins.select_plugins",
            _fake_select_factory(_make_selection(*handlers)),
        )
    else:
        monkeypatch.setattr(
            "firnline_core.plugins.select_plugins",
            _fake_select_factory(PluginSelection(active=[], skipped=[])),
        )


def _make_client(monkeypatch, settings=None, **overrides):
    """Create app + TestClient with monkeypatched plugins."""
    s = settings if settings is not None else _make_settings(**overrides)
    app = create_app(s)
    return TestClient(app)


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


def test_healthz_up(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["terminusdb"] == "up"
    assert "version" in data
    assert "handlers" in data
    assert "modules" in data
    assert "blob_root_writable" in data


def test_healthz_down_connection_error(monkeypatch):
    _patch_app(monkeypatch, tdb_client=FailingTdbClient())
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["terminusdb"] == "down"


def test_healthz_with_handlers(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["handlers"] == ["stub-note"]


def test_healthz_blob_root_writable_true(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch)
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["blob_root_writable"] is True


def test_healthz_blob_root_writable_null(monkeypatch):
    monkeypatch.delenv("FIRNLINE_BLOB_ROOT", raising=False)
    _patch_app(monkeypatch)
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["blob_root_writable"] is None


def test_healthz_modules_degraded(monkeypatch):
    _patch_app(monkeypatch, tdb_client=FailingDocumentsTdbClient())
    with _make_client(monkeypatch) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["modules"] == {}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_v1_capture_note_no_auth(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={"Content-Type": "text/plain"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unauthorized"


def test_v1_capture_note_malformed_auth(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Token abc",
            },
        )
    assert resp.status_code == 401


def test_v1_capture_note_wrong_token(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer wrong-token",
            },
        )
    assert resp.status_code == 401


def test_v1_capture_note_valid_auth(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "stub-note-id"
    assert data["kind"] == "note"


def test_empty_token_bypass_blocked():
    with pytest.raises(Exception):
        _make_settings(api_token="")


# ---------------------------------------------------------------------------
# Note capture happy path
# ---------------------------------------------------------------------------


def test_note_capture_plain_text(monkeypatch):
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="some note",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "note"
    assert resp.json()["id"] == "stub-note-id"


def test_note_capture_with_captured_at_header(monkeypatch):
    _patch_app(monkeypatch, handlers=[CapturedAtHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
                "X-Captured-At": "2026-07-05T14:00:00Z",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "captured-at-id"


def test_note_capture_content_type_with_charset(monkeypatch):
    """Content-Type: text/plain; charset=utf-8 should be accepted."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Note capture error cases
# ---------------------------------------------------------------------------


def test_note_capture_json_body_accepted(monkeypatch):
    """Sending valid application/json to /note returns 201."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "hello from json"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "stub-note-id"


def test_note_capture_json_with_kind(monkeypatch):
    """JSON body with explicit kind is accepted and forwarded."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "note with kind", "kind": "note"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "note"


def test_note_capture_json_with_metadata(monkeypatch):
    """JSON body with metadata is passed through to the handler."""
    _patch_app(monkeypatch, handlers=[MetadataVerifyingHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "with meta", "metadata": {"source": "web"}},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "meta-ok"


def test_note_capture_json_missing_text_422(monkeypatch):
    """JSON body missing the 'text' field returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"kind": "note"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"]


def test_note_capture_json_empty_text_422(monkeypatch):
    """JSON body with whitespace-only text returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "   "},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"]


def test_note_capture_json_invalid_json_422(monkeypatch):
    """Malformed JSON body returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="{not valid",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 422
    assert "valid JSON" in resp.json()["detail"]


def test_note_capture_json_non_object_422(monkeypatch):
    """JSON array body returns 422 (must be an object)."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json=[1, 2, 3],
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "JSON object" in resp.json()["detail"]


def test_note_capture_json_non_string_kind_422(monkeypatch):
    """JSON body with non-string kind returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "hello", "kind": 123},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "kind must be a string" in resp.json()["detail"]


def test_note_capture_json_non_dict_metadata_422(monkeypatch):
    """JSON body with non-object metadata returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "hello", "metadata": [1, 2, 3]},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "metadata must be a JSON object" in resp.json()["detail"]


def test_note_capture_json_with_captured_at_header(monkeypatch):
    """X-Captured-At header works with application/json body."""
    _patch_app(monkeypatch, handlers=[CapturedAtHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            json={"text": "timestamped json"},
            headers={
                "Authorization": "Bearer test-token",
                "X-Captured-At": "2026-07-05T14:00:00Z",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "captured-at-id"


def test_note_capture_no_content_type_415(monkeypatch):
    """Missing Content-Type header returns 415."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 415
    assert "application/json" in resp.json()["detail"]


def test_note_capture_empty_body_422(monkeypatch):
    """Empty body returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"]


def test_note_capture_invalid_utf8_422(monkeypatch):
    """Invalid UTF-8 bytes return 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    invalid_utf8 = b"\xff\xfe\xfd"
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content=invalid_utf8,
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 422
    assert "UTF-8" in resp.json()["detail"]


def test_note_capture_invalid_captured_at_422(monkeypatch):
    """Invalid X-Captured-At header returns 422."""
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
                "X-Captured-At": "not-a-date",
            },
        )
    assert resp.status_code == 422
    assert "ISO 8601" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Kind collision → startup fatal (exercises REAL collision branch)
# ---------------------------------------------------------------------------


def test_kind_collision_fatal(monkeypatch):
    """Two handlers claiming same kind raises RuntimeError at startup (via PluginHost collision_key)."""
    import captured.app as app_mod

    tc = FakeTdbClient()
    monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: tc)
    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        _fake_discover_factory(_make_discovery(StubNoteHandler(), StubConflictingHandler())),
    )
    monkeypatch.setattr(
        "firnline_core.plugins.select_plugins",
        _fake_select_factory(_make_selection(StubNoteHandler(), StubConflictingHandler())),
    )

    with pytest.raises(RuntimeError, match="collision"):
        with TestClient(create_app(_make_settings())):
            pass


# ---------------------------------------------------------------------------
# Zero handlers
# ---------------------------------------------------------------------------


def test_zero_handlers_app_starts_and_capture_404s(monkeypatch):
    _patch_app(monkeypatch, handlers=[])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hi",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
            },
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# File capture happy path
# ---------------------------------------------------------------------------


def test_file_capture_happy_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello world", "text/plain")},
            data={"kind": "file"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kind"] == "file"
    assert "sha256" in data
    assert "id" in data

    blob_store = BlobStore(tmp_path)
    path = blob_store.get_path(data["sha256"])
    assert path is not None
    assert path.read_bytes() == b"hello world"


def test_file_capture_deduplication(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp1 = c.post(
            "/v1/capture/file",
            files={"file": ("dup.txt", b"same content", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
        resp2 = c.post(
            "/v1/capture/file",
            files={"file": ("dup2.txt", b"same content", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["sha256"] == resp2.json()["sha256"]


# ---------------------------------------------------------------------------
# File capture without blob root → 503
# ---------------------------------------------------------------------------


def test_file_capture_no_blob_root_503(monkeypatch):
    monkeypatch.delenv("FIRNLINE_BLOB_ROOT", raising=False)
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 503
    assert "FIRNLINE_BLOB_ROOT" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Unsafe filename extension → extensionless (genuinely unsafe suffix)
# ---------------------------------------------------------------------------


def test_unsafe_filename_ext_falls_back(monkeypatch, tmp_path):
    """Filename with genuinely unsafe extension is stored extensionless."""
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("evil.t<x>t", b"payload", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    sha256 = resp.json()["sha256"]
    blob_store = BlobStore(tmp_path)
    stored_path = blob_store.get_path(sha256)
    assert stored_path is not None
    assert stored_path.suffix == ""


# ---------------------------------------------------------------------------
# Max upload size → 413
# ---------------------------------------------------------------------------


def test_upload_exceeds_max_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    settings = _make_settings(max_upload_bytes=10)
    import captured.app as app_mod

    monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: FakeTdbClient())
    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        _fake_discover_factory(_make_discovery(StubFileHandler())),
    )
    monkeypatch.setattr(
        "firnline_core.plugins.select_plugins",
        _fake_select_factory(_make_selection(StubFileHandler())),
    )

    app = create_app(settings)
    with TestClient(app) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("big.txt", b"this is more than ten bytes", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 413
    assert "exceeds maximum size" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Metadata non-object JSON → 422
# ---------------------------------------------------------------------------


def test_file_capture_metadata_not_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello", "text/plain")},
            data={"metadata": json.dumps([1, 2, 3])},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "metadata must be a JSON object" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Handler exception → 500
# ---------------------------------------------------------------------------


class FailingHandler:
    name = "failing"
    kinds = ("fail",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        raise ValueError("boom")


def test_handler_exception_returns_500(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[FailingHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"trigger", "text/plain")},
            data={"kind": "fail"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "capture processing failed"


class HttpExceptionHandler:
    name = "http-error"
    kinds = ("fail",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        raise HTTPException(status_code=400, detail="handler says no")


def test_handler_http_exception_passes_through(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[HttpExceptionHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"trigger", "text/plain")},
            data={"kind": "fail"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "handler says no"


# ---------------------------------------------------------------------------
# Metadata JSON parse error → 422 (file capture)
# ---------------------------------------------------------------------------


def test_file_capture_invalid_metadata_json(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello", "text/plain")},
            data={"metadata": "not json"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "metadata must be valid JSON" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Unknown kind → 404 (via file endpoint)
# ---------------------------------------------------------------------------


def test_unknown_kind_file_returns_404(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubNoteHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hi", "text/plain")},
            data={"kind": "unknown-kind"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "no handler for kind" in detail["message"]
    assert "known_kinds" in detail
    assert "hint" in detail


# ---------------------------------------------------------------------------
# captured_at round-trips to handler
# ---------------------------------------------------------------------------


class CapturedAtHandler:
    name = "captured-at-handler"
    kinds = ("note",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        assert payload.captured_at is not None
        return "captured-at-id"


class MetadataVerifyingHandler:
    name = "meta-handler"
    kinds = ("note",)
    requires: list[ModuleRequirement] = []

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        assert payload.metadata == {"source": "web"}
        return "meta-ok"


def test_captured_at_roundtrips_to_handler(monkeypatch):
    _patch_app(monkeypatch, handlers=[CapturedAtHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/note",
            content="hello",
            headers={
                "Content-Type": "text/plain",
                "Authorization": "Bearer test-token",
                "X-Captured-At": "2026-07-05T14:00:00Z",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "captured-at-id"


# ---------------------------------------------------------------------------
# File upload — size in response
# ---------------------------------------------------------------------------


def test_file_capture_response_includes_size(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[StubFileHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello world", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["size"] == 11


# ---------------------------------------------------------------------------
# strict_plugins — skipped plugin + strict → startup fails
# ---------------------------------------------------------------------------


class _HandlerWithUnmetReq:
    name = "unmet-handler"
    kinds = ("note",)
    requires = [ModuleRequirement(name="nonexistent", range=">=2.0.0")]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str:
        return "nope"


def test_strict_plugins_fails_on_skipped(monkeypatch):
    """strict_plugins=True raises RuntimeError when a handler is skipped."""
    import captured.app as app_mod

    tc = FakeTdbClient()
    monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: tc)
    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        _fake_discover_factory(_make_discovery(_HandlerWithUnmetReq())),
    )
    monkeypatch.setattr(
        "firnline_core.plugins.select_plugins",
        _fake_select_factory(
            PluginSelection(
                active=[],
                skipped=[("unmet-handler", ["module 'nonexistent' not installed"])],
            )
        ),
    )

    settings = _make_settings(strict_plugins=True)

    # Must fail at startup because strict mode + skipped
    with pytest.raises(RuntimeError, match="Strict plugin mode"):
        with TestClient(create_app(settings)):
            pass


def test_strict_plugins_off_allows_skipped(monkeypatch):
    """strict_plugins=False: skipped handler logs warning, app starts."""
    import captured.app as app_mod

    tc = FakeTdbClient()
    monkeypatch.setattr(app_mod, "TdbClient", lambda **kw: tc)
    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        _fake_discover_factory(_make_discovery(_HandlerWithUnmetReq())),
    )
    monkeypatch.setattr(
        "firnline_core.plugins.select_plugins",
        _fake_select_factory(
            PluginSelection(
                active=[],
                skipped=[("unmet-handler", ["module 'nonexistent' not installed"])],
            )
        ),
    )

    settings = _make_settings(strict_plugins=False)

    # Should start fine (zero handlers)
    app = create_app(settings)
    with TestClient(app) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["handlers"] == []


# ---------------------------------------------------------------------------
# File upload captured_at round-trips to handler
# ---------------------------------------------------------------------------

async def test_file_capture_captured_at_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    _patch_app(monkeypatch, handlers=[CapturedAtHandler()])
    with _make_client(monkeypatch) as c:
        resp = c.post(
            "/v1/capture/file",
            files={"file": ("test.txt", b"hello", "text/plain")},
            data={
                "kind": "note",
                "captured_at": "2026-07-05T14:00:00Z",
            },
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 201
    assert resp.json()["id"] == "captured-at-id"
