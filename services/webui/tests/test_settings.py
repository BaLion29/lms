"""Tests for firnline_webui.settings."""

from __future__ import annotations

from firnline_webui.settings import Settings, get_settings


def test_defaults():
    s = Settings()
    assert s.captured_url == "http://apid:8080"
    assert s.captured_api_token == ""
    assert s.queryd_url == "http://apid:8080"
    assert s.queryd_api_token == ""
    assert s.indexed_url == "http://apid:8080"
    assert s.indexed_api_token == ""
    assert s.mcpd_url == "http://apid:8080/mcp"
    assert s.tdb_url == "http://terminusdb:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "firnline"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.tdb_password == ""
    assert s.password == ""
    assert s.request_timeout_seconds == 30.0


def test_env_prefix_overrides(monkeypatch):
    monkeypatch.setenv("WEBUI_CAPTURED_URL", "http://capt:9999")
    monkeypatch.setenv("WEBUI_PASSWORD", "secret123")
    monkeypatch.setenv("WEBUI_REQUEST_TIMEOUT_SECONDS", "10")
    s = Settings()
    assert s.captured_url == "http://capt:9999"
    assert s.password == "secret123"
    assert s.request_timeout_seconds == 10.0


def test_get_settings_caches():
    a = get_settings()
    b = get_settings()
    assert a is b


def test_get_settings_after_monkeypatch_is_stale_by_design(monkeypatch):
    """get_settings caches; env changes after first call are not reflected."""
    _ = get_settings()
    monkeypatch.setenv("WEBUI_CAPTURED_URL", "http://changed:1234")
    s = get_settings()
    # Still the original cached value
    assert s.captured_url == "http://apid:8080"
