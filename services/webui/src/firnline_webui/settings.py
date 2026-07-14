"""Application settings for firnline-webui, loaded from WEBUI_* env vars."""

from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables prefixed with WEBUI_."""

    model_config = SettingsConfigDict(env_prefix="WEBUI_")

    # Service URLs
    captured_url: str = "http://captured:8088"
    captured_api_token: str = ""
    queryd_url: str = "http://queryd:8087"
    queryd_api_token: str = ""
    indexed_url: str = "http://indexed:8089"
    indexed_api_token: str = ""
    mcpd_url: str = "http://mcpd:8090"

    # TerminusDB
    tdb_url: str = "http://terminusdb:6363"
    tdb_org: str = "admin"
    tdb_db: str = "firnline"
    tdb_branch: str = "main"
    tdb_user: str = "admin"
    tdb_password: str = ""

    # UI gate
    password: str = ""  # empty = disabled

    # Operational
    request_timeout_seconds: float = 30.0


@functools.lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance with WEBUI_ prefix."""
    return Settings()
