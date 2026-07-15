"""Application settings loaded from environment variables prefixed with MCPD_."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpdSettings(BaseSettings):
    """MCP daemon settings.

    All fields can be set via environment variables with the ``MCPD_`` prefix
    (e.g. ``MCPD_HOST``, ``MCPD_QUERYD_URL``).
    """

    model_config = SettingsConfigDict(env_prefix="MCPD_")

    host: str = "0.0.0.0"
    port: int = 8090
    queryd_url: str = "http://localhost:8087"
    queryd_token: str = ""
    captured_url: str = "http://localhost:8088"
    captured_token: str = ""
    request_timeout_seconds: float = 30.0
    enable_queryd_tools: bool = True
