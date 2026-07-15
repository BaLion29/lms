from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """Application settings loaded from environment variables prefixed with INGESTD_."""

    model_config = SettingsConfigDict(env_prefix="INGESTD_")

    # LLM configuration
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Operational
    log_level: str = "INFO"
    poll_interval_seconds: int = 60
    max_llm_retries: int = 3
    dry_run: bool = False
    strict_plugins: bool = False
    liveness_file: str = "/tmp/ingestd-alive"

    # indexed grounding service
    indexed_enabled: bool = False
    indexed_url: str = "http://localhost:8089"
    indexed_token: str = ""
    indexed_min_confidence: float = 0.85
    indexed_timeout_seconds: float = 10.0
