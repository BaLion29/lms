"""Tests for firnline_core.settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

import pytest

from firnline_core.settings import FirnlineBaseSettings, TdbSettings


@pytest.fixture(autouse=True)
def _isolate_toml(monkeypatch, tmp_path):
    """Ensure ambient FIRNLINE_CONFIG_FILE never leaks into test settings."""
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(tmp_path / "__nonexistent__.toml"))


class _FakeServiceSettings(FirnlineBaseSettings):
    """Test settings with a fake env_prefix for TOML-file tests."""

    model_config = SettingsConfigDict(env_prefix="FAKESVC_")

    name: str = "default-name"
    port: int = 8080


# ---------------------------------------------------------------------------
# Existing TdbSettings tests (keep passing unchanged)
# ---------------------------------------------------------------------------


def test_tdb_settings_from_kwargs():
    """TdbSettings can be constructed with explicit keyword arguments."""
    s = TdbSettings(tdb_db="testdb", tdb_password="secret")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.tdb_password == "secret"


def test_tdb_settings_defaults():
    """TdbSettings has correct default values."""
    s = TdbSettings(tdb_db="db", tdb_password="pw")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"


def test_tdb_settings_extra_ignored():
    """Unknown extra fields are ignored (for subclassing compatibility)."""
    # pydantic-settings BaseSettings doesn't have extra="ignore" by default
    # but we just verify the standard behavior
    s = TdbSettings(tdb_db="db", tdb_password="pw")
    assert s.tdb_db == "db"


# ---------------------------------------------------------------------------
# New TOML config-file tests
# ---------------------------------------------------------------------------


def test_missing_file_fallback(monkeypatch, tmp_path):
    """Point FIRNLINE_CONFIG_FILE at a nonexistent path → defaults used."""
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(tmp_path / "nope.toml"))
    monkeypatch.delenv("FAKESVC_NAME", raising=False)
    monkeypatch.delenv("FAKESVC_PORT", raising=False)

    s = _FakeServiceSettings()
    assert s.name == "default-name"
    assert s.port == 8080


def test_file_overrides_defaults(monkeypatch, tmp_path):
    """TOML values win over hard-coded defaults."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[fakesvc]\n"
        "name = \"from-toml\"\n"
        "port = 9999\n"
    )
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_path))
    monkeypatch.delenv("FAKESVC_NAME", raising=False)
    monkeypatch.delenv("FAKESVC_PORT", raising=False)

    s = _FakeServiceSettings()
    assert s.name == "from-toml"
    assert s.port == 9999


def test_two_services_disjoint_tables(monkeypatch, tmp_path):
    """Two settings classes with different prefixes each see only their table."""

    class _SvcA(FirnlineBaseSettings):
        model_config = SettingsConfigDict(env_prefix="SVCA_")
        x: str = "x-default"

    class _SvcB(FirnlineBaseSettings):
        model_config = SettingsConfigDict(env_prefix="SVCB_")
        y: str = "y-default"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[svca]\n"
        "x = \"a-value\"\n"
        "[svcb]\n"
        "y = \"b-value\"\n"
    )
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_path))

    a = _SvcA()
    b = _SvcB()
    assert a.x == "a-value"
    assert b.y == "b-value"


def test_env_wins_over_file(monkeypatch, tmp_path):
    """Environment variable wins over the TOML file value."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[fakesvc]\n"
        "name = \"from-toml\"\n"
        "port = 7777\n"
    )
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_path))
    monkeypatch.setenv("FAKESVC_NAME", "from-env")
    # keep port from TOML

    s = _FakeServiceSettings()
    assert s.name == "from-env"   # env wins over TOML
    assert s.port == 7777         # TOML wins over default


def test_missing_table_in_file(monkeypatch, tmp_path):
    """File exists but has no table for the prefix → defaults used."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[othersvc]\n"
        "name = \"other\"\n"
    )
    monkeypatch.setenv("FIRNLINE_CONFIG_FILE", str(toml_path))
    monkeypatch.delenv("FAKESVC_NAME", raising=False)
    monkeypatch.delenv("FAKESVC_PORT", raising=False)

    s = _FakeServiceSettings()
    assert s.name == "default-name"
    assert s.port == 8080
