"""Application settings loaded from environment variables prefixed with CAPTURED_."""

from __future__ import annotations

from lms_core.settings import TdbSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """Application settings loaded from environment variables prefixed with CAPTURED_."""

    model_config = SettingsConfigDict(env_prefix="CAPTURED_")

    # API auth
    api_token: str = Field(min_length=1)

    # Operational
    listen_addr: str = "0.0.0.0:8088"
    strict_plugins: bool = False

    # Upload limits
    max_upload_bytes: int = Field(default=50_000_000, gt=0)
