"""Application settings loaded from environment variables prefixed with MCPD_."""

from firnline_core.settings import FirnlineBaseSettings
from pydantic_settings import SettingsConfigDict


class McpdSettings(FirnlineBaseSettings):
    """MCP daemon settings.

    All fields can be set via environment variables with the ``MCPD_`` prefix
    (e.g. ``MCPD_HOST``, ``MCPD_QUERYD_URL``).
    """

    model_config = SettingsConfigDict(env_prefix="MCPD_")

    host: str = "0.0.0.0"
    port: int = 8090
    log_level: str = "INFO"
    queryd_url: str = "http://localhost:8080"
    queryd_token: str = ""
    captured_url: str = "http://localhost:8080"
    captured_token: str = ""
    request_timeout_seconds: float = 30.0
    enable_queryd_tools: bool = True
