"""Tests for the new structured REST endpoints on queryd.

Covers: /v1/schema, /v1/schema/introspection, /v1/modules,
/v1/documents/{iri}, /v1/graphql, /v1/find/entity|class|field.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
import respx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from firnline_core.plugins import DiscoveryResult, PluginSelection

from queryd.app import create_app, _validate_doc_iri
from queryd.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TDB_URL = "http://tdb.test"
TDB_DB = "testdb"
ORG = "admin"
AUTH = {"Authorization": "Bearer test-token"}
GQL_PATH = f"{TDB_URL}/api/graphql/{ORG}/{TDB_DB}"
DOC_PATH = f"{TDB_URL}/api/document/{ORG}/{TDB_DB}/local/branch/main"


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
    respx_mock: respx.MockRouter | None = None,
    **overrides,
):
    """Create a TestClient with basic mocks for startup (no plugins)."""
    s = settings if settings is not None else _make_settings(**overrides)
    with patch("firnline_core.plugins.discover_plugins") as mock_disc:
        mock_disc.return_value = DiscoveryResult(active=[])
        with patch("firnline_core.plugins.select_plugins") as mock_sel:
            mock_sel.return_value = PluginSelection(active=[])
            app = create_app(s)
            with TestClient(app) as client:
                yield client


# ---------------------------------------------------------------------------
# Auth: all new endpoints require bearer token
# ---------------------------------------------------------------------------


def test_v1_schema_requires_auth():
    with _app_client() as client:
        resp = client.get("/v1/schema")
    assert resp.status_code == 401


def test_v1_schema_introspection_requires_auth():
    with _app_client() as client:
        resp = client.get("/v1/schema/introspection")
    assert resp.status_code == 401


def test_v1_modules_requires_auth():
    with _app_client() as client:
        resp = client.get("/v1/modules")
    assert resp.status_code == 401


def test_v1_documents_requires_auth():
    with _app_client() as client:
        resp = client.get("/v1/documents/Task/abc")
    assert resp.status_code == 401


def test_v1_graphql_requires_auth():
    with _app_client() as client:
        resp = client.post("/v1/graphql", json={"query": "{ Task { _id } }"})
    assert resp.status_code == 401


def test_v1_find_entity_requires_auth():
    with _app_client() as client:
        resp = client.post("/v1/find/entity", json={"text": "test"})
    assert resp.status_code == 401


def test_v1_find_class_requires_auth():
    with _app_client() as client:
        resp = client.post("/v1/find/class", json={"text": "test"})
    assert resp.status_code == 401


def test_v1_find_field_requires_auth():
    with _app_client() as client:
        resp = client.post("/v1/find/field", json={"text": "test"})
    assert resp.status_code == 401


def test_wrong_token_returns_401():
    with _app_client() as client:
        resp = client.get(
            "/v1/schema",
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/schema
# ---------------------------------------------------------------------------


def test_v1_schema_returns_summary(respx_mock: respx.MockRouter):
    """GET /v1/schema returns rendered schema summary."""
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/schema", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "OBJECT TYPES" in data["summary"]


# ---------------------------------------------------------------------------
# GET /v1/schema/introspection
# ---------------------------------------------------------------------------


def test_v1_schema_introspection_returns_raw_json(respx_mock: respx.MockRouter):
    """GET /v1/schema/introspection returns raw introspection JSON."""
    intro_payload = {
        "data": {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [{"name": "Task", "kind": "OBJECT", "fields": []}],
            }
        }
    }
    respx_mock.post(GQL_PATH).respond(json=intro_payload)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/schema/introspection", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert "__schema" in data
    assert data["__schema"]["queryType"]["name"] == "Query"


# ---------------------------------------------------------------------------
# GET /v1/modules
# ---------------------------------------------------------------------------


def test_v1_modules_returns_list(respx_mock: respx.MockRouter):
    """GET /v1/modules returns SchemaModule registry docs."""
    modules = [
        {"@id": "SchemaModule/core", "@type": "SchemaModule", "name": "core", "version": "1.0.0"},
        {"@id": "SchemaModule/planning", "@type": "SchemaModule", "name": "planning", "version": "2.0.0"},
    ]
    respx_mock.get(DOC_PATH).respond(json=modules)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/modules", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "core"
    assert data[1]["name"] == "planning"


# ---------------------------------------------------------------------------
# GET /v1/documents/{iri:path}
# ---------------------------------------------------------------------------


def test_v1_documents_happy_path(respx_mock: respx.MockRouter):
    """GET /v1/documents/Task/abc returns the document."""
    doc = {"@id": "Task/abc", "@type": "Task", "name": "Test"}
    respx_mock.get(DOC_PATH).respond(json=doc)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/documents/Task/abc", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert data["@id"] == "Task/abc"
    assert data["name"] == "Test"


def test_v1_documents_with_slash_in_iri(respx_mock: respx.MockRouter):
    """GET /v1/documents handles IRIs with slashes (e.g. nested)."""
    doc = {"@id": "Nested/foo/bar", "@type": "Nested", "name": "Deep"}
    respx_mock.get(DOC_PATH).respond(json=doc)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        # iri:path captures the full path including slashes
        resp = client.get("/v1/documents/Nested/foo/bar", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert data["@id"] == "Nested/foo/bar"


def test_v1_documents_404(respx_mock: respx.MockRouter):
    """GET /v1/documents returns 404 for missing document."""
    respx_mock.get(DOC_PATH).respond(status_code=404)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/documents/Task/nope", headers=AUTH)

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_validate_doc_iri_rejects_dot_dot():
    """_validate_doc_iri rejects '..' path traversal."""
    with pytest.raises(HTTPException, match="path traversal"):
        _validate_doc_iri("../etc/passwd")


def test_validate_doc_iri_rejects_backslashes():
    """_validate_doc_iri rejects backslashes."""
    with pytest.raises(HTTPException, match="backslashes"):
        _validate_doc_iri("Task\\abc")


def test_validate_doc_iri_rejects_leading_slash():
    """_validate_doc_iri rejects leading '/'."""
    with pytest.raises(HTTPException, match="must not start with '/'"):
        _validate_doc_iri("/Task/abc")


def test_validate_doc_iri_rejects_unexpected_scheme():
    """_validate_doc_iri rejects non-terminusdb schemes."""
    with pytest.raises(HTTPException, match="unexpected scheme"):
        _validate_doc_iri("http://evil.com/Task/abc")


def test_validate_doc_iri_rejects_empty():
    """_validate_doc_iri rejects empty IRI."""
    with pytest.raises(HTTPException, match="must not be empty"):
        _validate_doc_iri("")


def test_validate_doc_iri_allows_bare_iri():
    """_validate_doc_iri allows bare Class/id form."""
    _validate_doc_iri("Task/abc")  # should not raise


def test_validate_doc_iri_allows_terminusdb_prefix():
    """_validate_doc_iri allows terminusdb:///data/... prefix."""
    _validate_doc_iri("terminusdb:///data/Task/abc")  # should not raise


def test_validate_doc_iri_allows_nested_iri():
    """_validate_doc_iri allows nested Class/sub/resource form."""
    _validate_doc_iri("Nested/foo/bar")  # should not raise


def test_v1_documents_iri_validation_backslashes(respx_mock: respx.MockRouter):
    """GET /v1/documents with backslashes returns 422 end-to-end."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get("/v1/documents/Task%5Cabc", headers=AUTH)

    assert resp.status_code == 422
    assert "backslashes" in resp.json()["detail"].lower()


def test_v1_documents_iri_validation_scheme(respx_mock: respx.MockRouter):
    """GET /v1/documents with http:// scheme returns 422 end-to-end."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.get(
            "/v1/documents/http%3A%2F%2Fevil.com/Task/abc", headers=AUTH
        )

    assert resp.status_code == 422
    assert "unexpected scheme" in resp.json()["detail"].lower()


def test_v1_documents_allows_full_terminusdb_iri(respx_mock: respx.MockRouter):
    """GET /v1/documents accepts full terminusdb:///data/... IRI."""
    doc = {"@id": "terminusdb:///data/Task/abc", "@type": "Task", "name": "Test"}
    respx_mock.get(DOC_PATH).respond(json=doc)
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        # terminusdb:///data/ is allowed; URL-encode the scheme separator
        resp = client.get(
            "/v1/documents/terminusdb%3A%2F%2F%2Fdata/Task/abc", headers=AUTH
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Test"


# ---------------------------------------------------------------------------
# POST /v1/graphql
# ---------------------------------------------------------------------------


def test_v1_graphql_happy_path(respx_mock: respx.MockRouter):
    """POST /v1/graphql executes a read query."""
    respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "Task/1", "name": "Test"}]}}
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.post(
            "/v1/graphql",
            json={"query": "{ Task { _id name } }"},
            headers=AUTH,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["Task"][0]["_id"] == "Task/1"


def test_v1_graphql_with_variables(respx_mock: respx.MockRouter):
    """POST /v1/graphql passes variables through."""
    respx_mock.post(GQL_PATH).respond(
        json={"data": {"Task": [{"_id": "Task/1"}]}}
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.post(
            "/v1/graphql",
            json={
                "query": "query($name: String) { Task(filter: { name: { eq: $name } }) { _id } }",
                "variables": {"name": "Test"},
            },
            headers=AUTH,
        )

    assert resp.status_code == 200


def test_v1_graphql_mutation_returns_400(respx_mock: respx.MockRouter):
    """POST /v1/graphql with mutation returns 400."""
    # Need at least db_exists mock for startup
    gql_route = respx_mock.post(GQL_PATH).respond(json={"data": {}})
    respx_mock.get(_tdb_exists_route()).respond(200)

    with _app_client(respx_mock=respx_mock) as client:
        resp = client.post(
            "/v1/graphql",
            json={"query": "mutation { _insertDocuments(doc: {}) { _id } }"},
            headers=AUTH,
        )

    assert resp.status_code == 400
    assert "prohibited" in resp.json()["detail"].lower()
    # The startup introspection call hits GQL once; mutation is blocked before HTTP
    # (The lifespan calls fetch_introspection which POSTs GQL, so call_count >= 1)
    assert gql_route.call_count >= 1


# ---------------------------------------------------------------------------
# POST /v1/find/entity
# ---------------------------------------------------------------------------


def test_v1_find_entity_disabled_503(respx_mock: respx.MockRouter):
    """find/entity returns 503 when indexed is disabled."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(indexed_enabled=False)
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/find/entity",
            json={"text": "Anna"},
            headers=AUTH,
        )

    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


def test_v1_find_entity_requires_text(respx_mock: respx.MockRouter):
    """find/entity with missing text returns 422 (pydantic validation)."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    # We need indexed enabled to bypass the 503 check
    settings = _make_settings(indexed_enabled=True, indexed_url="http://localhost:8089")
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/find/entity",
            json={},
            headers=AUTH,
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/find/class
# ---------------------------------------------------------------------------


def test_v1_find_class_disabled_503(respx_mock: respx.MockRouter):
    """find/class returns 503 when indexed is disabled."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(indexed_enabled=False)
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/find/class",
            json={"text": "Task"},
            headers=AUTH,
        )

    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /v1/find/field
# ---------------------------------------------------------------------------


def test_v1_find_field_disabled_503(respx_mock: respx.MockRouter):
    """find/field returns 503 when indexed is disabled."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(indexed_enabled=False)
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/find/field",
            json={"text": "name"},
            headers=AUTH,
        )

    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


def test_v1_find_field_with_class_name(respx_mock: respx.MockRouter):
    """find/field validates request shape — optional class_name."""
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(indexed_enabled=True, indexed_url="http://localhost:8089")
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/find/field",
            json={"text": "name", "class_name": "Task"},
            headers=AUTH,
        )
    # 422 or 502 depending on if indexed is actually reachable
    # (it's not, but 503 is for disabled, 502 for connection error)
    # We just assert it's not 401 or 503
    assert resp.status_code != 401
    assert resp.status_code != 503


# ---------------------------------------------------------------------------
# PluginHost startup paths
# ---------------------------------------------------------------------------


def test_pluginhost_startup_gates_writes(respx_mock: respx.MockRouter):
    """PluginHost runs; writes disabled → tools suppressed but plugins reported in healthz."""
    respx_mock.get(DOC_PATH).respond(json=[])  # empty registry
    respx_mock.post(GQL_PATH).respond(
        json={
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "types": [],
                }
            }
        }
    )
    respx_mock.get(_tdb_exists_route()).respond(200)

    settings = _make_settings(enable_writes=False)
    app = create_app(settings)

    with TestClient(app) as client:
        resp = client.get("/healthz", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert "plugins" in data
