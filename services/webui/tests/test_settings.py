"""Tests for firnline_webui.settings."""

from __future__ import annotations

import pytest

from firnline_webui.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolate_toml(monkeypatch, tmp_path):
    """Ensure ambient FIRNLINE_CONFIG_FILE never leaks into test settings."""
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(tmp_path / "__nonexistent__.toml"))


def test_defaults():
    s = Settings()
    assert s.captured_url == "http://captured:8088"
    assert s.captured_api_token == ""
    assert s.queryd_url == "http://queryd:8087"
    assert s.queryd_api_token == ""
    assert s.indexed_url == "http://indexed:8089"
    assert s.indexed_api_token == ""
    assert s.mcpd_url == "http://mcpd:8090"
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
    assert s.captured_url == "http://captured:8088"


def test_toml_config_overrides_default(monkeypatch, tmp_path):
    """A [webui] table in the TOML config file overrides a defaulted field."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('[webui]\npassword = "from-toml"\n')
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_file))
    monkeypatch.delenv("WEBUI_PASSWORD", raising=False)

    s = Settings()
    assert s.password == "from-toml"
    assert s.request_timeout_seconds == 30.0  # still the default
