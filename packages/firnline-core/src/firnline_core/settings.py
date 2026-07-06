"""Base settings for TerminusDB connection shared across Firnline services.

Subclasses should set their own ``env_prefix`` via
``model_config = SettingsConfigDict(env_prefix="...")``.
"""

from pydantic_settings import BaseSettings


class TdbSettings(BaseSettings):
    """TerminusDB connection settings – meant to be subclassed."""

    # Intentionally no env_prefix here; subclasses set their own.
    tdb_url: str = "http://localhost:6363"
    tdb_org: str = "admin"
    tdb_db: str
    tdb_branch: str = "main"
    tdb_user: str = "admin"
    tdb_password: str
