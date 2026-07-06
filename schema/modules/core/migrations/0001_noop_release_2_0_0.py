"""Data migration for core 2.0.0 — module re-cut.

This is a grouping-only change: Trigger moved to triggers module,
ExternalRef added as new class.  No data transformation needed.
"""

import logging

logger = logging.getLogger(__name__)


async def up(tdb, branch: str) -> None:
    """Idempotent no-op: re-cut is grouping-only, composed schema equivalent."""
    logger.info("core 2.0.0 migration: no data changes needed (grouping re-cut + ExternalRef addition)")
