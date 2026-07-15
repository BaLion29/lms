"""Tests for mcpd.settings."""

import pytest

from mcpd.settings import McpdSettings


@pytest.fixture(autouse=True)
def _isolate_toml(monkeypatch, tmp_path):
    """Ensure ambient FIRNLINE_CONFIG_FILE never leaks into test settings."""
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(tmp_path / "__nonexistent__.toml"))


def test_settings_defaults():
    """Settings have expected defaults."""
    s = McpdSettings()
    assert s.host == "0.0.0.0"
    assert s.port == 8090
    assert s.queryd_url == "http://localhost:8080"
    assert s.queryd_token == ""
    assert s.captured_url == "http://localhost:8080"
    assert s.captured_token == ""
    assert s.request_timeout_seconds == 30.0


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with MCPD_ prefix."""
    monkeypatch.setenv("MCPD_HOST", "127.0.0.1")
    monkeypatch.setenv("MCPD_PORT", "9090")
    monkeypatch.setenv("MCPD_QUERYD_URL", "https://query.example.com")
    monkeypatch.setenv("MCPD_QUERYD_TOKEN", "q-token")
    monkeypatch.setenv("MCPD_CAPTURED_URL", "https://capture.example.com")
    monkeypatch.setenv("MCPD_CAPTURED_TOKEN", "c-token")
    monkeypatch.setenv("MCPD_REQUEST_TIMEOUT_SECONDS", "10.5")

    s = McpdSettings()
    assert s.host == "127.0.0.1"
    assert s.port == 9090
    assert s.queryd_url == "https://query.example.com"
    assert s.queryd_token == "q-token"
    assert s.captured_url == "https://capture.example.com"
    assert s.captured_token == "c-token"
    assert s.request_timeout_seconds == 10.5


def test_toml_config_overrides_default(monkeypatch, tmp_path):
    """A [mcpd] table in the TOML config file overrides a defaulted field."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('[mcpd]\nport = 9876\n')
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_file))
    monkeypatch.delenv("MCPD_PORT", raising=False)

    s = McpdSettings()
    assert s.port == 9876
    assert s.host == "0.0.0.0"  # still the default
