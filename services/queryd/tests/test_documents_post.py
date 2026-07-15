"""Tests for the POST /v1/documents/{class_name} document ingestion endpoint."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import respx
from fastapi.testclient import TestClient

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

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
        llm_base_url="http://llm.test",
        llm_api_key="sk-test",
        llm_model="test-model",
        tdb_url=TDB_URL,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _tdb_exists_route() -> str:
    return f"{TDB_URL}/api/db/admin/{TDB_DB}"


def _setup_startup_mocks(respx_mock: respx.MockRouter) -> None:
    """Mock the TDB calls that happen during app startup (lifespan)."""
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
    # Module list fetch at startup (graceful degradation — not critical)
    respx_mock.get(DOC_PATH).respond(json=[])


# ---------------------------------------------------------------------------
# 1. Auth
# ---------------------------------------------------------------------------


def test_requires_auth():
    """POST without Authorization header → 401."""
    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
        )

    assert resp.status_code == 401


def test_wrong_token_returns_401():
    """POST with wrong bearer token → 401."""
    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
            headers={"Authorization": "Bearer wrong"},
        )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. enable_writes gate
# ---------------------------------------------------------------------------


def test_writes_disabled_returns_403(respx_mock: respx.MockRouter):
    """enable_writes=False → 403."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=False)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Happy path
# ---------------------------------------------------------------------------


def test_happy_path(respx_mock: respx.MockRouter):
    """POST /v1/documents/Task with valid body → 201, correct iri returned."""
    _setup_startup_mocks(respx_mock)
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "Review PR", "priority": 3},
            headers=AUTH,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["iri"] == "Task/abc"

    # Verify the request sent to TDB
    assert post_route.call_count == 1
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    assert isinstance(sent, list)
    assert len(sent) == 1
    doc = sent[0]
    assert doc["@type"] == "Task"
    assert doc["name"] == "Review PR"
    assert doc["priority"] == 3
    assert "provenance" in doc
    assert doc["provenance"]["agent"] == "service:queryd"
    assert doc["provenance"]["method"] == "direct"


# ---------------------------------------------------------------------------
# 4. Agent header override
# ---------------------------------------------------------------------------


def test_agent_header_override(respx_mock: respx.MockRouter):
    """X-Firnline-Agent header overrides the default agent in provenance."""
    _setup_startup_mocks(respx_mock)
    post_route = respx_mock.post(DOC_PATH).respond(json=["Task/abc"])

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
            headers={**AUTH, "X-Firnline-Agent": "user:basti"},
        )

    assert resp.status_code == 201
    req = post_route.calls.last.request
    sent = json.loads(req.read())
    assert sent[0]["provenance"]["agent"] == "user:basti"


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
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
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
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"@type": "Task", "name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 422
    assert "@type" in resp.json()["detail"].lower()


def test_body_with_at_id_returns_422(respx_mock: respx.MockRouter):
    """Body containing @id → 422."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"@id": "Task/mine", "name": "test"},
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
        pytest.param(None, "json", id="null"),
    ],
)
def test_non_dict_body_returns_422(
    respx_mock: respx.MockRouter, body_value: object, detail_keyword: str
):
    """Non-object bodies (array, string, number, bool, null) → 422."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json=body_value,
            headers=AUTH,
        )

    assert resp.status_code == 422
    assert detail_keyword in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 8. Bad class_name
# ---------------------------------------------------------------------------


def test_class_name_starts_with_digit_returns_400(respx_mock: respx.MockRouter):
    """class_name starting with digit → 400."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/1abc",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 400
    assert "class name" in resp.json()["detail"].lower()


def test_class_name_with_slash_returns_405(respx_mock: respx.MockRouter):
    """class_name containing '/' does not match the route pattern;
    the GET /v1/documents/{iri:path} route matches but is GET-only,
    so FastAPI returns 405 Method Not Allowed."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/foo/bar",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# 9. TDB errors
# ---------------------------------------------------------------------------


def test_tdb_400_schema_violation_returns_422(respx_mock: respx.MockRouter):
    """TDB returns 400 (schema validation) → endpoint returns 422."""
    _setup_startup_mocks(respx_mock)
    tdb_body = '{"error": "Unknown class \\"BogusClass\\""}'
    respx_mock.post(DOC_PATH).respond(status_code=400, text=tdb_body)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 422
    assert tdb_body in resp.json()["detail"]


def test_tdb_conflict_returns_409(respx_mock: respx.MockRouter):
    """TDBConflictError → 409."""
    from firnline_core.tdb import TdbConflictError

    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )

    with patch(
        "firnline_core.repository.Repository.create",
        side_effect=TdbConflictError("abc", "def"),
    ):
        app = create_app(settings, model=model, plugin_tools=[])

        with TestClient(app) as client:
            resp = client.post(
                "/v1/documents/Task",
                json={"name": "test"},
                headers=AUTH,
            )

    assert resp.status_code == 409
    assert "conflict" in resp.json()["detail"].lower()


def test_tdb_500_returns_502(respx_mock: respx.MockRouter):
    """Other TdbError → 502."""
    _setup_startup_mocks(respx_mock)
    respx_mock.post(DOC_PATH).respond(status_code=500, text="boom")

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )
    app = create_app(settings, model=model, plugin_tools=[])

    with TestClient(app) as client:
        resp = client.post(
            "/v1/documents/Task",
            json={"name": "test"},
            headers=AUTH,
        )

    assert resp.status_code == 502
    assert "TdbError" in resp.json()["detail"]


def test_repo_create_valueerror_returns_400(respx_mock: respx.MockRouter):
    """ValueError from Repository.create → 400."""
    _setup_startup_mocks(respx_mock)

    settings = _make_settings(enable_writes=True)
    model = FunctionModel(
        function=lambda messages, info: ModelResponse(parts=[TextPart(content="ok")])
    )

    with patch(
        "firnline_core.repository.Repository.create",
        side_effect=ValueError("something bad"),
    ):
        app = create_app(settings, model=model, plugin_tools=[])

        with TestClient(app) as client:
            resp = client.post(
                "/v1/documents/Task",
                json={"name": "test"},
                headers=AUTH,
            )

    assert resp.status_code == 400
    assert "something bad" in resp.json()["detail"]
