"""Effect engine — orchestrates plan/execute phases over TriggerFiring documents."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from effectd.legacy_notify import LegacyNotifyLoop

if TYPE_CHECKING:
    from effectd.settings import EffectdSettings

logger = structlog.get_logger(__name__)


class EffectEngine:
    """Effect delivery engine.

    When ``legacy_notification_loop`` is enabled (default), delegates
    ``run_cycle`` to the zero-config ``LegacyNotifyLoop``.  Future
    releases will add plan/execute phases driven by ActionExecution
    documents.
    """

    def __init__(
        self,
        repo: Any,
        channels: list[object],
        *,
        settings: EffectdSettings | None = None,
        now: Any = None,
        logger: Any = None,
    ) -> None:
        self.repo = repo
        self.channels = channels
        self.settings = settings
        self.log = logger or structlog.get_logger(__name__)
        self._now = now

        if settings is None or settings.legacy_notification_loop:
            self._legacy = LegacyNotifyLoop(
                repo=repo,
                channels=channels,
                now=now,
                logger=logger,
            )
        else:
            self._legacy = None

    async def run_cycle(self, should_stop: Any = None) -> None:
        """Run one full delivery cycle."""
        if self._legacy is not None:
            await self._legacy.run_cycle(should_stop)
        # Part B will add plan/execute phases here.
