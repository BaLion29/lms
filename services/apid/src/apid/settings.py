"""Application settings loaded from environment variables prefixed with APID_."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from firnline_core.settings import FirnlineBaseSettings


class ApidSettings(FirnlineBaseSettings):
    """Combined API daemon settings.

    All fields can be set via environment variables with the ``APID_`` prefix
    (e.g. ``APID_LISTEN_ADDR``, ``APID_LOG_LEVEL``).
    """

    model_config = SettingsConfigDict(env_prefix="APID_")

    listen_addr: str = "0.0.0.0:8080"
    log_level: str = "INFO"

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
            raise ValueError(f"listen_addr port must be an integer, got {parts[1]!r}") from None
        if port < 0 or port > 65535:
            raise ValueError(f"listen_addr port out of range: {port}")
        return v
