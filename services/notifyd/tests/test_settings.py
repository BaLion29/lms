"""Tests for notifyd.settings."""

from notifyd.settings import NotifydSettings


def test_settings_defaults():
    """Settings have expected defaults."""
    s = NotifydSettings(tdb_db="testdb", tdb_password="secret")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_password == "secret"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.poll_interval_seconds == 30
    assert s.liveness_file == "/tmp/notifyd-alive"


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with NOTIFYD_ prefix."""
    monkeypatch.setenv("NOTIFYD_TDB_DB", "envdb")
    monkeypatch.setenv("NOTIFYD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("NOTIFYD_TDB_URL", "https://tdb.example.com")
    monkeypatch.setenv("NOTIFYD_TDB_ORG", "myorg")
    monkeypatch.setenv("NOTIFYD_TDB_BRANCH", "develop")
    monkeypatch.setenv("NOTIFYD_TDB_USER", "myuser")
    monkeypatch.setenv("NOTIFYD_POLL_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("NOTIFYD_LIVENESS_FILE", "/tmp/custom-alive")

    s = NotifydSettings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.tdb_url == "https://tdb.example.com"
    assert s.tdb_org == "myorg"
    assert s.tdb_branch == "develop"
    assert s.tdb_user == "myuser"
    assert s.poll_interval_seconds == 15
    assert s.liveness_file == "/tmp/custom-alive"
