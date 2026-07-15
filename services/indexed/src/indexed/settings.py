"""Application settings loaded from environment variables prefixed with INDEXED_."""

from __future__ import annotations

from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """TerminusDB-connected hybrid index service settings.

    All fields can be set via environment variables with the ``INDEXED_``
    prefix (e.g. ``INDEXED_POLL_INTERVAL_SECONDS``).
    """

    model_config = SettingsConfigDict(env_prefix="INDEXED_")

    llm_base_url: str = ""
    llm_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    api_token: str = ""

    log_level: str = "INFO"
    poll_interval_seconds: int = 60
    listen_addr: str = "0.0.0.0:8089"
    dry_run: bool = False
    strict_plugins: bool = False
    liveness_file: str = "/tmp/indexed-alive"
    data_dir: str = "/var/lib/firnline/index"

    min_confidence: float = 0.60
