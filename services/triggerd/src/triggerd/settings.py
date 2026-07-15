"""Application settings loaded from environment variables prefixed with TRIGGERD_."""

from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class Settings(TdbSettings):
    """TerminusDB-connected trigger evaluation daemon settings.

    All fields can be set via environment variables with the ``TRIGGERD_``
    prefix (e.g. ``TRIGGERD_POLL_INTERVAL_SECONDS``).
    """

    model_config = SettingsConfigDict(env_prefix="TRIGGERD_")

    poll_interval_seconds: int = 60
    lookback_seconds: int = 900
    default_timezone: str = "UTC"
    dry_run: bool = False
    strict_plugins: bool = False
    liveness_file: str = "/tmp/triggerd-alive"
    state_file: str = "/tmp/triggerd-state.json"
