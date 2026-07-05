"""Tests for queryd.settings."""

from queryd.settings import Settings


def test_settings_from_kwargs():
    """Settings can be constructed with explicit keyword arguments."""
    s = Settings(
        api_token="test-token",
        tdb_db="testdb",
        tdb_password="secret",
        llm_base_url="https://api.example.com",
        llm_api_key="sk-test",
        llm_model="gpt-4",
    )
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_password == "secret"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.api_token == "test-token"
    assert s.llm_base_url == "https://api.example.com"
    assert s.llm_api_key == "sk-test"
    assert s.llm_model == "gpt-4"
    assert s.enable_writes is False
    assert s.max_tool_iterations == 8
    assert s.request_timeout_seconds == 60
    assert s.listen_addr == "0.0.0.0:8087"
    assert s.cors_origins == []


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with QUERYD_ prefix."""
    monkeypatch.setenv("QUERYD_TDB_DB", "envdb")
    monkeypatch.setenv("QUERYD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("QUERYD_API_TOKEN", "env-token")
    monkeypatch.setenv("QUERYD_LLM_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("QUERYD_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("QUERYD_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("QUERYD_ENABLE_WRITES", "true")
    monkeypatch.setenv("QUERYD_MAX_TOOL_ITERATIONS", "5")
    monkeypatch.setenv("QUERYD_LISTEN_ADDR", "127.0.0.1:9090")

    s = Settings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.api_token == "env-token"
    assert s.llm_base_url == "https://env.example.com"
    assert s.llm_api_key == "sk-env"
    assert s.llm_model == "gpt-4o"
    assert s.enable_writes is True
    assert s.max_tool_iterations == 5
    assert s.listen_addr == "127.0.0.1:9090"


def test_cors_origins_default_empty():
    """cors_origins defaults to empty list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
    )
    assert s.cors_origins == []


def test_cors_origins_comma_parsing():
    """cors_origins accepts comma-separated string."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
        cors_origins="http://a.com, http://b.com",
    )
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_single():
    """cors_origins accepts a single string (no comma)."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
        cors_origins="http://a.com",
    )
    assert s.cors_origins == ["http://a.com"]


def test_cors_origins_empty_string():
    """cors_origins empty/whitespace string yields empty list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
        cors_origins="  ",
    )
    assert s.cors_origins == []


def test_cors_origins_list_passthrough():
    """cors_origins passes through when given as list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        llm_base_url="http://x",
        llm_api_key="k",
        llm_model="m",
        cors_origins=["http://a.com", "http://b.com"],
    )
    assert s.cors_origins == ["http://a.com", "http://b.com"]
