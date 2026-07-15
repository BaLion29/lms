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

    # ── Action execution engine ──────────────────────────────────────
    dry_run: bool = False
    """Global override: forces dry_run on ALL executions."""

    legacy_notification_loop: bool = True
    """Runs the legacy zero-config notification path (a.k.a. default_notify).

    This is the default_notify behaviour in this release — zero-config
    notification of every firing. Consolidating the nag policy onto
    ActionExecution is a documented follow-up.
    """

    default_notify_executor: str = "notify:gotify"
    planning_lookback: str = "P7D"
    """ISO-8601 duration bounding the planner query window."""

    max_executions_per_cycle: int = 50
    default_max_attempts: int = 3
    default_retry_backoff: str = "PT1M"
    """Doubled per attempt: 1m, 2m, 4m ..."""

    default_timeout: str = "PT30S"
    strict_plugins: bool = False
