"""Application settings for firnline-tui, loaded from TUI_* env vars."""
from __future__ import annotations

import functools

from firnline_core.settings import FirnlineBaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(FirnlineBaseSettings):
    """Application settings loaded from environment variables prefixed with TUI_."""

    model_config = SettingsConfigDict(env_prefix="TUI_", env_file=".env")

    # Service URLs — localhost defaults (TUI runs on host, not in compose)
    captured_url: str = "http://localhost:8080"
    captured_api_token: str = ""
    queryd_url: str = "http://localhost:8080"
    queryd_api_token: str = ""
    indexed_url: str = "http://localhost:8080"
    indexed_api_token: str = ""
    mcpd_url: str = "http://localhost:8080/mcp"

    # TerminusDB
    tdb_url: str = "http://localhost:6363"
    tdb_org: str = "admin"
    tdb_db: str = "firnline"
    tdb_branch: str = "main"
    tdb_user: str = "admin"
    tdb_password: str = ""

    # Operational
    request_timeout_seconds: float = 10.0
    plugin_registry_timeout_seconds: float = 3.0
    start_screen: str = "dashboard"


@functools.lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance with TUI_ prefix."""
    return Settings()
