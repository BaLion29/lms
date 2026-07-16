"""Application settings loaded from environment variables prefixed with EFFECTD_."""

from firnline_core.settings import TdbSettings
from pydantic_settings import SettingsConfigDict


class EffectdSettings(TdbSettings):
    """TerminusDB-connected effect delivery daemon settings.

    All fields can be set via environment variables with the ``EFFECTD_``
    prefix (e.g. ``EFFECTD_POLL_INTERVAL_SECONDS``).
    """

    model_config = SettingsConfigDict(env_prefix="EFFECTD_")

    log_level: str = "INFO"
    poll_interval_seconds: int = 30
    liveness_file: str = "/tmp/effectd-alive"
    lock_file: str = "/tmp/effectd.lock"
    """Exclusive lock file acquired at startup to prevent concurrent effectd processes."""

    # ── Action execution engine ──────────────────────────────────────
    dry_run: bool = False
    """Global override: forces dry_run on ALL executions."""

    default_notify_executor: str = "notify:gotify"
    """Default executor kind used when an Action document has no explicit executor field."""
    planning_lookback: str = "P7D"
    """ISO-8601 duration bounding the planner query window."""

    max_executions_per_cycle: int = 50
    default_max_attempts: int = 3
    default_retry_backoff: str = "PT1M"
    """Doubled per attempt: 1m, 2m, 4m ..."""

    default_timeout: str = "PT30S"
    strict_plugins: bool = False
