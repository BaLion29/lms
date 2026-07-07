"""Application settings loaded from environment variables prefixed with NOTIFYD_."""

from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class NotifydSettings(TdbSettings):
    """TerminusDB-connected notification delivery daemon settings.

    All fields can be set via environment variables with the ``NOTIFYD_``
    prefix (e.g. ``NOTIFYD_POLL_INTERVAL_SECONDS``).
    """

    model_config = SettingsConfigDict(env_prefix="NOTIFYD_")

    poll_interval_seconds: int = 30
    liveness_file: str = "/tmp/notifyd-alive"
