from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables prefixed with INGESTD_."""

    model_config = SettingsConfigDict(env_prefix="INGESTD_")

    # TerminusDB connection
    tdb_url: str = "http://localhost:6363"
    tdb_org: str = "admin"
    tdb_db: str
    tdb_branch: str = "main"
    tdb_user: str = "admin"
    tdb_password: str

    # LLM configuration
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # Operational
    poll_interval_seconds: int = 60
    max_llm_retries: int = 3
    dry_run: bool = False
