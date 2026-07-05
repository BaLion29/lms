"""Tests for queryd.app: healthz, auth, payload validation."""

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
        llm_base_url="http://llm.test",
        llm_api_key="sk-test",
        llm_model="test-model",
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_v1_chat_no_auth():
    """Missing Authorization header returns 401."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "unauthorized"


def test_v1_chat_malformed_auth():
    """Malformed Authorization header returns 401."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Token abc"},
        )
    assert resp.status_code == 401


def test_v1_chat_wrong_token():
    """Wrong bearer token returns 401."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


def test_v1_chat_valid_auth_returns_501():
    """Valid auth + good payload returns 501 (stub)."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 501
    assert resp.json()["detail"] == "not implemented"


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


def test_v1_chat_empty_messages():
    """Empty messages list returns 422."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={"messages": []},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "messages must not be empty" in resp.text


def test_v1_chat_last_message_not_user():
    """Last message role != 'user' returns 422."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi there"},
                ]
            },
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
    assert "last message must be from the user" in resp.text


def test_v1_chat_missing_messages_field():
    """Missing messages field triggers FastAPI/pydantic validation error."""
    with _client() as client:
        resp = client.post(
            "/v1/chat",
            json={},
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422
