from ingestd.settings import Settings
import pytest


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


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_validate_llm_settings_all_present_does_nothing():
    """validate_llm_settings does not exit when all LLM settings are set."""
    from ingestd.main import validate_llm_settings

    s = Settings(
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
    )
    # Should not raise / exit
    validate_llm_settings(s)


@pytest.mark.parametrize(
    "missing_fields",
    [
        ["llm_base_url"],
        ["llm_api_key"],
        ["llm_model"],
        ["llm_base_url", "llm_model"],
        ["llm_base_url", "llm_api_key", "llm_model"],
    ],
)
def test_validate_llm_settings_missing_exits_2(missing_fields):
    """validate_llm_settings raises SystemExit(2) when required fields are empty."""
    from ingestd.main import validate_llm_settings

    kwargs = {
        "tdb_db": "db",
        "tdb_password": "pw",
        "llm_base_url": "http://x",
        "llm_api_key": "k",
        "llm_model": "m",
    }
    for field in missing_fields:
        kwargs[field] = ""

    s = Settings(**kwargs)
    with pytest.raises(SystemExit) as exc_info:
        validate_llm_settings(s)
    assert exc_info.value.code == 2
