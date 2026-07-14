"""Tests for effectd.engine — delegation shell."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from effectd.engine import EffectEngine
from effectd.settings import EffectdSettings


class TestEffectEngineDelegation:
    @pytest.mark.asyncio
    async def test_legacy_loop_delegates_when_enabled(self):
        """When legacy_notification_loop is True (or settings is None), run_cycle delegates."""
        repo = AsyncMock()
        engine = EffectEngine(repo=repo, channels=[])

        assert engine._legacy is not None
        engine._legacy.run_cycle = AsyncMock()
        await engine.run_cycle()
        engine._legacy.run_cycle.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_loop_skipped_when_disabled(self):
        """When legacy_notification_loop=False, run_cycle is a no-op."""
        settings = EffectdSettings(tdb_db="db", tdb_password="pw", legacy_notification_loop=False)
        repo = AsyncMock()
        engine = EffectEngine(repo=repo, channels=[], settings=settings)

        assert engine._legacy is None
        await engine.run_cycle()  # no-op, should not raise


def test_module_imports_with_zero_extensions():
    """All modules import successfully even with no extensions installed."""
