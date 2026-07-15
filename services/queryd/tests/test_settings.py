"""Tests for queryd.settings."""

import pytest
from pydantic import ValidationError

from queryd.settings import Settings


def test_settings_from_kwargs():
    """Settings can be constructed with explicit keyword arguments."""
    s = Settings(
        api_token="test-token",
        tdb_db="testdb",
        tdb_password="secret",
    )
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_password == "secret"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.api_token == "test-token"
    assert s.enable_writes is False
    assert s.request_timeout_seconds == 60
    assert s.listen_addr == "0.0.0.0:8087"
    assert s.cors_origins == []


def test_settings_from_env(monkeypatch):
    """Settings picks up values from environment variables with QUERYD_ prefix."""
    monkeypatch.setenv("QUERYD_TDB_DB", "envdb")
    monkeypatch.setenv("QUERYD_TDB_PASSWORD", "envsecret")
    monkeypatch.setenv("QUERYD_API_TOKEN", "env-token")
    monkeypatch.setenv("QUERYD_ENABLE_WRITES", "true")
    monkeypatch.setenv("QUERYD_LISTEN_ADDR", "127.0.0.1:9090")

    s = Settings()  # type: ignore[call-arg]
    assert s.tdb_db == "envdb"
    assert s.tdb_password == "envsecret"
    assert s.api_token == "env-token"
    assert s.enable_writes is True
    assert s.listen_addr == "127.0.0.1:9090"


def test_cors_origins_default_empty():
    """cors_origins defaults to empty list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
    )
    assert s.cors_origins == []


def test_cors_origins_comma_parsing():
    """cors_origins accepts comma-separated string."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        cors_origins="http://a.com, http://b.com",
    )
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_single():
    """cors_origins accepts a single string (no comma)."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        cors_origins="http://a.com",
    )
    assert s.cors_origins == ["http://a.com"]


def test_cors_origins_empty_string():
    """cors_origins empty/whitespace string yields empty list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        cors_origins="  ",
    )
    assert s.cors_origins == []


def test_cors_origins_list_passthrough():
    """cors_origins passes through when given as list."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        cors_origins=["http://a.com", "http://b.com"],
    )
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_listen_addr_valid():
    """Valid host:port is accepted."""
    s = Settings(
        api_token="t",
        tdb_db="db",
        tdb_password="pw",
        listen_addr="127.0.0.1:9000",
    )
    assert s.listen_addr == "127.0.0.1:9000"


def test_listen_addr_no_colon_raises():
    """listen_addr without colon raises ValidationError."""
    with pytest.raises(ValidationError, match="host:port"):
        Settings(
            api_token="t",
            tdb_db="db",
            tdb_password="pw",
            listen_addr="127.0.0.1",
        )


def test_listen_addr_bad_port_raises():
    """listen_addr with non-integer port raises ValidationError."""
    with pytest.raises(ValidationError, match="must be an integer"):
        Settings(
            api_token="t",
            tdb_db="db",
            tdb_password="pw",
            listen_addr="0.0.0.0:xyz",
        )


def test_listen_addr_port_out_of_range():
    """listen_addr with port > 65535 raises ValidationError."""
    with pytest.raises(ValidationError, match="out of range"):
        Settings(
            api_token="t",
            tdb_db="db",
            tdb_password="pw",
            listen_addr="0.0.0.0:99999",
        )


def test_api_token_required():
    """api_token must be at least 1 char (empty token rejected)."""
    with pytest.raises(ValidationError, match="api_token"):
        Settings(
            api_token="",
            tdb_db="db",
            tdb_password="pw",
        )
