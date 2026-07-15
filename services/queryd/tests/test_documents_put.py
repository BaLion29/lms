"""Tests for the PUT /v1/documents/{iri:path} document update endpoint."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import respx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from firnline_core.plugins import DiscoveryResult, PluginSelection

from queryd.app import create_app
from queryd.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"
AUTH = {"Authorization": "Bearer test-token"}
DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"
GQL_PATH = f"{TDB_URL}/api/graphql/{ORG}/{TDB_DB}"


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
def _app_client(
    settings: Settings | None = None,
    **overrides,
):
    """Create a TestClient with plugin discovery mocked out (no plugins)."""
    s = settings if settings is not None else _make_settings(**overrides)
    with patch("firnline_core.plugins.discover_plugins") as mock_disc:
        mock_disc.return_value = DiscoveryResult(active=[])
        with patch("firnline_core.plugins.select_plugins") as mock_sel:
            mock_sel.return_value = PluginSelection(active=[])
            app = create_app(s)
            with TestClient(app) as client:
                yield client


# ---------------------------------------------------------------------------
# 1. Auth
# ---------------------------------------------------------------------------


def test_requires_auth():
    """PUT without Authorization header → 401."""
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
        )
    assert resp.status_code == 401


def test_wrong_token_returns_401():
    """PUT with wrong bearer token → 401."""
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. enable_writes gate
# ---------------------------------------------------------------------------


def test_writes_disabled_returns_403(respx_mock: respx.MockRouter):
    """enable_writes=False → 403."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=False) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
            headers=AUTH,
        )
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Happy path
# ---------------------------------------------------------------------------


def test_happy_path(respx_mock: respx.MockRouter):
    """PUT /v1/documents/Task/abc with valid body → 200, correct iri returned."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    # Mock GET to return existing document
    existing = {"@id": "Task/abc", "@type": "Task", "name": "Original", "priority": 1}
    doc_get = respx_mock.get(DOC_PATH).respond(json=existing)
    # Mock PUT for replace_document
    doc_put = respx_mock.put(DOC_PATH).respond(json="ok")

    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "Updated name", "priority": 2},
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["iri"] == "Task/abc"

    # Verify the GET was issued
    assert doc_get.call_count >= 1
    # Verify the PUT was issued to TDB with updated doc
    assert doc_put.call_count == 1
    req = doc_put.calls.last.request
    sent = json.loads(req.read())
    assert sent["@id"] == "Task/abc"
    assert sent["@type"] == "Task"
    assert sent["name"] == "Updated name"
    assert sent["priority"] == 2
    assert "provenance" in sent
    assert sent["provenance"]["agent"] == "service:queryd"


# ---------------------------------------------------------------------------
# 4. Agent header override
# ---------------------------------------------------------------------------


def test_agent_header_override(respx_mock: respx.MockRouter):
    """X-Firnline-Agent header overrides the default agent in provenance."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    existing = {"@id": "Task/abc", "@type": "Task", "name": "Original"}
    respx_mock.get(DOC_PATH).respond(json=existing)
    put_route = respx_mock.put(DOC_PATH).respond(json="ok")

    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
            headers={**AUTH, "X-Firnline-Agent": "user:basti"},
        )

    assert resp.status_code == 200
    req = put_route.calls.last.request
    sent = json.loads(req.read())
    assert sent["provenance"]["agent"] == "user:basti"


# ---------------------------------------------------------------------------
# 5. Bad agent header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent",
    [
        "foo:bar",
        "nonsense",
        "bad/agent",
        "",
    ],
)
def test_bad_agent_header_returns_400(respx_mock: respx.MockRouter, agent: str):
    """Invalid agent grammar in X-Firnline-Agent → 400."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
            headers={**AUTH, "X-Firnline-Agent": agent},
        )
    assert resp.status_code == 400
    assert "agent" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. Body contains @type or @id
# ---------------------------------------------------------------------------


def test_body_with_at_type_returns_422(respx_mock: respx.MockRouter):
    """Body containing @type → 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"@type": "Task", "name": "test"},
            headers=AUTH,
        )
    assert resp.status_code == 422
    assert "@type" in resp.json()["detail"].lower()


def test_body_with_at_id_returns_422(respx_mock: respx.MockRouter):
    """Body containing @id → 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"@id": "Task/xyz", "name": "test"},
            headers=AUTH,
        )
    assert resp.status_code == 422
    assert "@id" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 7. Non-object body
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body_value,detail_keyword",
    [
        pytest.param(["not", "a", "dict"], "object", id="array"),
        pytest.param("string", "object", id="string"),
        pytest.param(42, "object", id="int"),
        pytest.param(True, "object", id="bool"),
    ],
)
def test_non_dict_body_returns_422(
    respx_mock: respx.MockRouter, body_value: object, detail_keyword: str
):
    """Non-object bodies → 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json=body_value,
            headers=AUTH,
        )
    assert resp.status_code == 422
    assert detail_keyword in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 8. Bad IRI
# ---------------------------------------------------------------------------


def test_bad_iri_backslashes_returns_422(respx_mock: respx.MockRouter):
    """IRI with backslashes → 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task%5Cabc",
            json={"name": "test"},
            headers=AUTH,
        )
    assert resp.status_code == 422


def test_bad_iri_scheme_returns_422(respx_mock: respx.MockRouter):
    """IRI with unexpected scheme → 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/http%3A%2F%2Fevil.com/Task/abc",
            json={"name": "test"},
            headers=AUTH,
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 9. Document not found (404)
# ---------------------------------------------------------------------------


def test_not_found_returns_404(respx_mock: respx.MockRouter):
    """GET from TDB returns 404 → endpoint returns 404."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    # TDB returns 404 for the get_document call
    respx_mock.get(DOC_PATH).respond(status_code=404)

    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/nope",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 10. TDB errors
# ---------------------------------------------------------------------------


def test_tdb_400_schema_violation_returns_422(respx_mock: respx.MockRouter):
    """TDB returns 400 (schema validation) → endpoint returns 422."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    existing = {"@id": "Task/abc", "@type": "Task", "name": "Original"}
    respx_mock.get(DOC_PATH).respond(json=existing)
    tdb_body = '{"error": "Unknown field \\"bogus\\""}'
    respx_mock.put(DOC_PATH).respond(status_code=400, text=tdb_body)

    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"bogus": "value"},
            headers=AUTH,
        )

    assert resp.status_code == 422
    assert tdb_body in resp.json()["detail"]


def test_tdb_conflict_returns_409(respx_mock: respx.MockRouter):
    """TDBConflictError → 409."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    from firnline_core.tdb import TdbConflictError

    settings = _make_settings(enable_writes=True)

    with patch(
        "firnline_core.repository.Repository.update",
        side_effect=TdbConflictError("abc", "def"),
    ):
        with _app_client(settings=settings) as client:
            resp = client.put(
                "/v1/documents/Task/abc",
                json={"name": "test"},
                headers=AUTH,
            )

    assert resp.status_code == 409
    assert "conflict" in resp.json()["detail"].lower()


def test_tdb_500_returns_502(respx_mock: respx.MockRouter):
    """Other TdbError → 502."""
    respx_mock.get(_tdb_exists_route()).respond(200)
    existing = {"@id": "Task/abc", "@type": "Task", "name": "Original"}
    respx_mock.get(DOC_PATH).respond(json=existing)
    respx_mock.put(DOC_PATH).respond(status_code=500, text="boom")

    with _app_client(enable_writes=True) as client:
        resp = client.put(
            "/v1/documents/Task/abc",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 502
    assert "TdbError" in resp.json()["detail"]


def test_repo_update_valueerror_returns_400(respx_mock: respx.MockRouter):
    """ValueError from Repository.update → 400."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(enable_writes=True)

    with patch(
        "firnline_core.repository.Repository.update",
        side_effect=ValueError("Cannot change @type"),
    ):
        with _app_client(settings=settings) as client:
            resp = client.put(
                "/v1/documents/Task/abc",
                json={"name": "test"},
                headers=AUTH,
            )

    assert resp.status_code == 400
    assert "Cannot change @type" in resp.json()["detail"]
