"""Application settings loaded from environment variables prefixed with EFFECTD_."""

from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class EffectdSettings(TdbSettings):
    """TerminusDB-connected effect delivery daemon settings.

    All fields can be set via environment variables with the ``EFFECTD_``
    prefix (e.g. ``EFFECTD_POLL_INTERVAL_SECONDS``).
    """

    model_config = SettingsConfigDict(env_prefix="EFFECTD_")

    poll_interval_seconds: int = 30
    liveness_file: str = "/tmp/effectd-alive"
