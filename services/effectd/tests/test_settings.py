"""Tests for effectd.settings."""

from effectd.settings import EffectdSettings


def test_settings_defaults():
    """Settings have expected defaults."""
    s = EffectdSettings(tdb_db="testdb", tdb_password="secret")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_password == "secret"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.poll_interval_seconds == 30
    assert s.liveness_file == "/tmp/effectd-alive"


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with EFFECTD_ prefix."""
    monkeypatch.setenv("EFFECTD_TDB_DB", "envdb")
    monkeypatch.setenv("EFFECTD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("EFFECTD_TDB_URL", "https://tdb.example.com")
    monkeypatch.setenv("EFFECTD_TDB_ORG", "myorg")
    monkeypatch.setenv("EFFECTD_TDB_BRANCH", "develop")
    monkeypatch.setenv("EFFECTD_TDB_USER", "myuser")
    monkeypatch.setenv("EFFECTD_POLL_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("EFFECTD_LIVENESS_FILE", "/tmp/custom-alive")

    s = EffectdSettings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.tdb_url == "https://tdb.example.com"
    assert s.tdb_org == "myorg"
    assert s.tdb_branch == "develop"
    assert s.tdb_user == "myuser"
    assert s.poll_interval_seconds == 15
    assert s.liveness_file == "/tmp/custom-alive"
