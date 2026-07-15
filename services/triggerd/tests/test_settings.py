"""Tests for triggerd.settings."""

from triggerd.settings import Settings


def test_settings_from_kwargs():
    """Settings can be constructed with explicit keyword arguments."""
    s = Settings(
        tdb_db="testdb",
        tdb_password="secret",
    )
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_password == "secret"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.poll_interval_seconds == 60
    assert s.lookback_seconds == 900
    assert s.default_timezone == "UTC"
    assert s.dry_run is False
    assert s.strict_plugins is False


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with TRIGGERD_ prefix."""
    monkeypatch.setenv("TRIGGERD_TDB_DB", "envdb")
    monkeypatch.setenv("TRIGGERD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("TRIGGERD_TDB_URL", "https://tdb.example.com")
    monkeypatch.setenv("TRIGGERD_TDB_ORG", "myorg")
    monkeypatch.setenv("TRIGGERD_TDB_BRANCH", "develop")
    monkeypatch.setenv("TRIGGERD_TDB_USER", "myuser")
    monkeypatch.setenv("TRIGGERD_POLL_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("TRIGGERD_LOOKBACK_SECONDS", "1800")
    monkeypatch.setenv("TRIGGERD_DEFAULT_TIMEZONE", "America/New_York")
    monkeypatch.setenv("TRIGGERD_DRY_RUN", "true")
    monkeypatch.setenv("TRIGGERD_STRICT_PLUGINS", "true")

    s = Settings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.tdb_url == "https://tdb.example.com"
    assert s.tdb_org == "myorg"
    assert s.tdb_branch == "develop"
    assert s.tdb_user == "myuser"
    assert s.poll_interval_seconds == 30
    assert s.lookback_seconds == 1800
    assert s.default_timezone == "America/New_York"
    assert s.dry_run is True
    assert s.strict_plugins is True
