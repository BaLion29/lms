"""Tests for apid.app: healthz, openapi schema, /mcp mount."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.routing import Route


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def set_env(monkeypatch):
    """Set minimum required env vars so all component settings can be constructed."""
    monkeypatch.setenv("CAPTURED_API_TOKEN", "test-token")
    monkeypatch.setenv("CAPTURED_TDB_DB", "testdb")
    monkeypatch.setenv("CAPTURED_TDB_PASSWORD", "x")
    monkeypatch.setenv("QUERYD_API_TOKEN", "test-token")
    monkeypatch.setenv("QUERYD_TDB_DB", "testdb")
    monkeypatch.setenv("QUERYD_TDB_PASSWORD", "x")
    monkeypatch.setenv("INDEXED_TDB_DB", "testdb")
    monkeypatch.setenv("INDEXED_TDB_PASSWORD", "x")
    monkeypatch.setenv("MCPD_ENABLE_QUERYD_TOOLS", "false")


# ---------------------------------------------------------------------------
# Helpers for tests that need lifespans to succeed
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _wrap_lifespan(orig_factory):
    """Wraps a ``create_component`` factory to use a noop lifespan."""

    def wrapped(settings=None):
        comp = orig_factory(settings)
        comp.lifespan = _noop_lifespan
        return comp

    return wrapped


def _mock_all_components(monkeypatch):
    """Replace all component factories in apid.app's namespace with noop-lifespan versions.

    We patch ``apid.app`` directly (not the source modules) because ``apid.app``
    imports the factories with ``from … import … as …``, binding them in its own
    namespace.  If another test already imported ``apid.app``, patching the source
    modules afterwards would have no effect.
    """
    # Force-import apid.app so we have a reference to its module namespace.
    import apid.app as apid_mod  # noqa: E402

    import captured.app as cap_mod

    monkeypatch.setattr(
        apid_mod,
        "captured_create_component",
        _wrap_lifespan(cap_mod.create_component),
    )

    import queryd.app as qd_mod

    monkeypatch.setattr(
        apid_mod,
        "queryd_create_component",
        _wrap_lifespan(qd_mod.create_component),
    )

    import indexed.app as idx_mod

    monkeypatch.setattr(
        apid_mod,
        "indexed_create_component",
        _wrap_lifespan(idx_mod.create_component),
    )

    noop_starlette = Starlette()
    monkeypatch.setattr(
        apid_mod,
        "mcpd_create_mcp_component",
        lambda settings=None: (noop_starlette, _noop_lifespan, None),
    )


# ---------------------------------------------------------------------------
# Tests — app construction & openapi (no lifespan needed)
# ---------------------------------------------------------------------------


def test_app_builds(set_env):
    """App factory returns a FastAPI instance without error."""
    from apid.app import create_app  # noqa: E402 — deferred for monkeypatch

    app = create_app()
    assert app is not None
    assert app.title == "Firnline Core API"


def test_openapi_has_routes(set_env):
    """OpenAPI schema contains expected routes from all three components."""
    from apid.app import create_app  # noqa: E402

    app = create_app()
    schema = app.openapi()
    paths = schema["paths"]

    # Spot-check routes from each component
    assert "/v1/capture/note" in paths, "captured route missing"
    assert "/v1/graphql" in paths, "queryd route missing"
    assert "/v1/find_entity" in paths, "indexed route missing (POST /v1/find_entity)"
    # Verify queryd's /v1/find/entity is present and distinct from indexed's /v1/find_entity
    assert "/v1/find/entity" in paths, "queryd /v1/find/entity missing"


# ---------------------------------------------------------------------------
# Tests — healthz & /mcp (need lifespan to succeed)
# ---------------------------------------------------------------------------


def test_healthz(set_env, monkeypatch):
    """/healthz returns 200 with per-component status."""
    _mock_all_components(monkeypatch)

    from apid.app import create_app  # noqa: E402

    with TestClient(create_app()) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "components" in data
    assert data["components"]["captured"] == "ok"
    assert data["components"]["queryd"] == "ok"
    assert data["components"]["indexed"] == "ok"
    assert data["components"]["mcpd"] == "ok"


def test_mcp_mount_healthz(set_env, monkeypatch):
    """/mcp/healthz returns 200 (healthz route is inside the mcpd sub-app)."""
    import apid.app as apid_mod  # noqa: E402

    import captured.app as cap_mod

    monkeypatch.setattr(
        apid_mod,
        "captured_create_component",
        _wrap_lifespan(cap_mod.create_component),
    )

    import queryd.app as qd_mod

    monkeypatch.setattr(
        apid_mod,
        "queryd_create_component",
        _wrap_lifespan(qd_mod.create_component),
    )

    import indexed.app as idx_mod

    monkeypatch.setattr(
        apid_mod,
        "indexed_create_component",
        _wrap_lifespan(idx_mod.create_component),
    )

    # mcpd component provides /healthz inside its Starlette wrapper
    async def mcp_healthz(request):
        return StarletteJSONResponse({"status": "ok"})

    mcp_subapp = Starlette(routes=[Route("/healthz", mcp_healthz)])
    monkeypatch.setattr(
        apid_mod,
        "mcpd_create_mcp_component",
        lambda settings=None: (mcp_subapp, _noop_lifespan, None),
    )

    from apid.app import create_app  # noqa: E402

    with TestClient(create_app()) as c:
        resp = c.get("/mcp/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_mcp_mount(set_env, monkeypatch):
    """/mcp mount exists (returns non-404)."""
    import apid.app as apid_mod  # noqa: E402

    import captured.app as cap_mod

    monkeypatch.setattr(
        apid_mod,
        "captured_create_component",
        _wrap_lifespan(cap_mod.create_component),
    )

    import queryd.app as qd_mod

    monkeypatch.setattr(
        apid_mod,
        "queryd_create_component",
        _wrap_lifespan(qd_mod.create_component),
    )

    import indexed.app as idx_mod

    monkeypatch.setattr(
        apid_mod,
        "indexed_create_component",
        _wrap_lifespan(idx_mod.create_component),
    )

    # Override just the mcpd component so the mock app responds at root
    async def mcp_root(request):
        return StarletteJSONResponse({"jsonrpc": "2.0"})

    mcp_subapp = Starlette(routes=[Route("/", mcp_root)])
    monkeypatch.setattr(
        apid_mod,
        "mcpd_create_mcp_component",
        lambda settings=None: (mcp_subapp, _noop_lifespan, None),
    )

    from apid.app import create_app  # noqa: E402

    with TestClient(create_app()) as c:
        resp = c.get("/mcp")
    assert resp.status_code == 200
    assert resp.json() == {"jsonrpc": "2.0"}


# ---------------------------------------------------------------------------
# Tests — proxy / trusted-host settings
# ---------------------------------------------------------------------------


def test_trusted_hosts_disabled_by_default(set_env, monkeypatch):
    """TrustedHostMiddleware is NOT active when APID_TRUSTED_HOSTS is empty."""
    _mock_all_components(monkeypatch)

    from apid.app import create_app  # noqa: E402

    with TestClient(create_app()) as c:
        resp = c.get("/healthz", headers={"Host": "evil.example.com"})
    # Middleware is not added → request succeeds regardless of Host
    assert resp.status_code == 200


def test_trusted_hosts_rejects_wrong_host(set_env, monkeypatch):
    """TrustedHostMiddleware rejects requests with an unlisted Host header."""
    monkeypatch.setenv("APID_TRUSTED_HOSTS", "firnline.example.com")
    _mock_all_components(monkeypatch)

    from apid.app import create_app  # noqa: E402

    with TestClient(create_app()) as c:
        # Wrong host → 400 Bad Request
        resp = c.get("/healthz", headers={"Host": "evil.example.com"})
        assert resp.status_code == 400

        # Correct host → 200 OK
        resp = c.get("/healthz", headers={"Host": "firnline.example.com"})
        assert resp.status_code == 200


def test_proxy_settings_via_env(monkeypatch):
    """ApidSettings reads proxy_headers and forwarded_allow_ips via APID_ env vars."""
    monkeypatch.setenv("APID_PROXY_HEADERS", "true")
    monkeypatch.setenv("APID_FORWARDED_ALLOW_IPS", "10.0.0.0/8")

    from apid.settings import ApidSettings  # noqa: E402

    settings = ApidSettings()
    assert settings.proxy_headers is True
    assert settings.forwarded_allow_ips == "10.0.0.0/8"


def test_apid_env_prefix_still_works(monkeypatch):
    """Existing APID_ env vars still work after base-class change."""
    monkeypatch.setenv("APID_LISTEN_ADDR", "127.0.0.1:9090")
    monkeypatch.setenv("APID_LOG_LEVEL", "DEBUG")

    from apid.settings import ApidSettings  # noqa: E402

    settings = ApidSettings()
    assert settings.listen_addr == "127.0.0.1:9090"
    assert settings.log_level == "DEBUG"
