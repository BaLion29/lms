"""Application settings loaded from environment variables prefixed with CAPTURED_."""

from __future__ import annotations

from firnline_core.settings import TdbSettings
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """Application settings loaded from environment variables prefixed with CAPTURED_."""

    model_config = SettingsConfigDict(env_prefix="CAPTURED_")

    # API auth
    api_token: str = Field(min_length=1)

    # Operational
    listen_addr: str = "0.0.0.0:8088"
    log_level: str = "INFO"
    strict_plugins: bool = False

    # Upload limits
    max_upload_bytes: int = Field(default=50_000_000, gt=0)

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
