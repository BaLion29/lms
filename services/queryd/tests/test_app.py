"""Tests for queryd.app: healthz, auth."""

from __future__ import annotations

from contextlib import contextmanager

import respx
from fastapi.testclient import TestClient

from queryd.app import create_app
from queryd.settings import Settings

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


def _tdb_exists_route() -> str:
    return f"{TDB_URL}/api/db/admin/{TDB_DB}"


@contextmanager
def _client(settings: Settings | None = None, **overrides):
    """Create a TestClient with the app lifespan managed."""
    s = settings if settings is not None else _make_settings(**overrides)
    app = create_app(s)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


def test_healthz_up(respx_mock: respx.MockRouter):
    """Returns 200 when TerminusDB is reachable."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["terminusdb"] == "up"
    assert "version" in data


def test_healthz_down_404(respx_mock: respx.MockRouter):
    """Returns 503 when TerminusDB returns 404."""
    respx_mock.get(_tdb_exists_route()).respond(404)
    with _client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["terminusdb"] == "down"


def test_healthz_down_connection_error(respx_mock: respx.MockRouter):
    """Returns 503 when TerminusDB is unreachable (connection error)."""
    respx_mock.get(_tdb_exists_route()).mock(side_effect=ConnectionError("refused"))
    with _client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 503


def test_healthz_blob_root_unset(monkeypatch):
    """blob_root_writable is null when FIRNLINE_BLOB_ROOT is unset."""
    monkeypatch.delenv("FIRNLINE_BLOB_ROOT", raising=False)
    with _client() as client:
        resp = client.get("/healthz")
    data = resp.json()
    assert data["blob_root_writable"] is None


def test_healthz_blob_root_writable(monkeypatch, tmp_path):
    """blob_root_writable is true when FIRNLINE_BLOB_ROOT points to a writable dir."""
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", str(tmp_path))
    with _client() as client:
        resp = client.get("/healthz")
    data = resp.json()
    assert data["blob_root_writable"] is True


def test_healthz_blob_root_unwritable(monkeypatch, respx_mock):
    """blob_root_writable is false on OSError; status unchanged when TDB is up."""
    monkeypatch.setenv("FIRNLINE_BLOB_ROOT", "/tmp/some-blob-root")

    def _raise_oserror(*args, **kwargs):
        raise OSError("permission denied")

    import tempfile

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _raise_oserror)
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _client() as client:
        resp = client.get("/healthz")
    data = resp.json()
    assert data["blob_root_writable"] is False
    assert data["status"] == "ok"
    assert data["terminusdb"] == "up"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_v1_schema_no_auth():
    """Missing Authorization header returns 401."""
    with _client() as client:
        resp = client.get("/v1/schema")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unauthorized"


def test_v1_schema_malformed_auth():
    """Malformed Authorization header returns 401."""
    with _client() as client:
        resp = client.get(
            "/v1/schema",
            headers={"Authorization": "Token abc"},
        )
    assert resp.status_code == 401


def test_v1_schema_wrong_token():
    """Wrong bearer token returns 401."""
    with _client() as client:
        resp = client.get(
            "/v1/schema",
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401
