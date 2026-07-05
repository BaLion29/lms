from ingestd.settings import Settings


def test_settings_from_kwargs():
    """Settings can be constructed with explicit keyword arguments."""
    s = Settings(
        tdb_db="testdb",
        tdb_password="secret",
        llm_base_url="https://api.example.com",
        llm_api_key="sk-test",
        llm_model="gpt-4",
    )
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_db == "testdb"
    assert s.llm_model == "gpt-4"
    assert s.poll_interval_seconds == 60
    assert s.dry_run is False


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with INGESTD_ prefix."""
    monkeypatch.setenv("INGESTD_TDB_DB", "envdb")
    monkeypatch.setenv("INGESTD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("INGESTD_LLM_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("INGESTD_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("INGESTD_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("INGESTD_DRY_RUN", "true")

    s = Settings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.llm_base_url == "https://env.example.com"
    assert s.llm_model == "gpt-4o"
    assert s.dry_run is True
