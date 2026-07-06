"""Data migration for planning 2.0.0 — module re-cut.

This is a grouping-only change: Reminder moved to reminders module,
all trigger types moved to triggers module.  No data transformation needed
for existing documents; they are still valid under the composed schema.
"""

import logging

logger = logging.getLogger(__name__)


async def up(tdb, branch: str) -> None:
    """Idempotent no-op: re-cut is grouping-only, composed schema equivalent."""
    logger.info("planning 2.0.0 migration: no data changes needed (grouping re-cut)")
