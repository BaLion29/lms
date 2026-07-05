"""Application settings loaded from environment variables prefixed with QUERYD_."""

from __future__ import annotations

from lms_core.settings import TdbSettings
from pydantic import field_validator
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """Application settings loaded from environment variables prefixed with QUERYD_."""

    model_config = SettingsConfigDict(env_prefix="QUERYD_")

    # API auth
    api_token: str

    # LLM configuration
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # Operational
    enable_writes: bool = False
    max_tool_iterations: int = 8
    request_timeout_seconds: float = 60
    listen_addr: str = "0.0.0.0:8087"
    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        """Accept a comma-separated string or a list."""
        if isinstance(v, str):
            if v.strip() == "":
                return []
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @field_validator("listen_addr")
    @classmethod
    def _validate_listen_addr(cls, v: str) -> str:
        """Require ``host:port`` where port is a valid integer."""
        parts = v.rsplit(":", 1)
        if len(parts) != 2:
            raise ValueError(f"listen_addr must be 'host:port', got {v!r}")
        try:
            port = int(parts[1])
        except ValueError:
            raise ValueError(
                f"listen_addr port must be an integer, got {parts[1]!r}"
            ) from None
        if port < 0 or port > 65535:
            raise ValueError(f"listen_addr port out of range: {port}")
        return v
