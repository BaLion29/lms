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
    # ── Action execution engine defaults ─────────────────────────────
    assert s.dry_run is False
    assert s.default_notify_executor == "notify:gotify"
    assert s.planning_lookback == "P7D"
    assert s.max_executions_per_cycle == 50
    assert s.default_max_attempts == 3
    assert s.default_retry_backoff == "PT1M"
    assert s.default_timeout == "PT30S"
    assert s.strict_plugins is False


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


def test_engine_settings_from_env(monkeypatch):
    """Action-execution-engine settings read from EFFECTD_ env vars."""
    monkeypatch.setenv("EFFECTD_DRY_RUN", "true")
    monkeypatch.setenv("EFFECTD_DEFAULT_NOTIFY_EXECUTOR", "notify:custom")
    monkeypatch.setenv("EFFECTD_PLANNING_LOOKBACK", "P14D")
    monkeypatch.setenv("EFFECTD_MAX_EXECUTIONS_PER_CYCLE", "10")
    monkeypatch.setenv("EFFECTD_DEFAULT_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("EFFECTD_DEFAULT_RETRY_BACKOFF", "PT30S")
    monkeypatch.setenv("EFFECTD_DEFAULT_TIMEOUT", "PT1M")
    monkeypatch.setenv("EFFECTD_STRICT_PLUGINS", "true")
    # TDB required fields
    monkeypatch.setenv("EFFECTD_TDB_DB", "db")
    monkeypatch.setenv("EFFECTD_TDB_PASSWORD", "pw")

    s = EffectdSettings()  # type: ignore[call-arg]
    assert s.dry_run is True
    assert s.default_notify_executor == "notify:custom"
    assert s.planning_lookback == "P14D"
    assert s.max_executions_per_cycle == 10
    assert s.default_max_attempts == 5
    assert s.default_retry_backoff == "PT30S"
    assert s.default_timeout == "PT1M"
    assert s.strict_plugins is True
