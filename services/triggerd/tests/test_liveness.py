"""Tests for liveness file behaviour in triggerd main loop."""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import AsyncMock

import pytest

from triggerd.main import async_main
from firnline_core.plugins import DiscoveryResult


def _patch_for_liveness_test(monkeypatch, tdb_mock):
    """Common patching for liveness tests."""
    monkeypatch.setattr("triggerd.main.discover_plugins", lambda group: DiscoveryResult(active=[]))
    monkeypatch.setattr("firnline_core.plugins.check_requirements", lambda tdb, reqs, branch="main": [])
    monkeypatch.setattr("triggerd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setenv("TRIGGERD_TDB_DB", "test")
    monkeypatch.setenv("TRIGGERD_TDB_PASSWORD", "test")


@pytest.mark.asyncio
async def test_liveness_file_touched_after_successful_cycle(monkeypatch):
    """Liveness file is created/touched after a successful cycle."""
    tmp_file = pathlib.Path(tempfile.mktemp(suffix="-liveness"))
    tmp_file.touch()

    monkeypatch.setenv("TRIGGERD_LIVENESS_FILE", str(tmp_file))
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_for_liveness_test(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(return_value=None)

    import triggerd.engine

    monkeypatch.setattr(triggerd.engine.Engine, "run_cycle", run_cycle_mock)

    import asyncio

    await async_main(once=True, dry_run=True, should_stop=asyncio.Event())

    run_cycle_mock.assert_called_once()
    assert tmp_file.exists(), "Liveness file should exist after successful cycle"


@pytest.mark.asyncio
async def test_liveness_file_not_touched_after_failed_cycle(monkeypatch):
    """Liveness file is NOT updated when a cycle fails."""
    tmp_file = pathlib.Path(tempfile.mktemp(suffix="-liveness"))
    # Create it with an old mtime
    tmp_file.touch()
    old_mtime = tmp_file.stat().st_mtime

    monkeypatch.setenv("TRIGGERD_LIVENESS_FILE", str(tmp_file))
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_for_liveness_test(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(side_effect=RuntimeError("boom"))

    import triggerd.engine

    monkeypatch.setattr(triggerd.engine.Engine, "run_cycle", run_cycle_mock)

    import asyncio

    with pytest.raises(SystemExit):
        await async_main(once=True, dry_run=True, should_stop=asyncio.Event())

    # File mtime should not have changed since the cycle failed
    new_mtime = tmp_file.stat().st_mtime
    assert new_mtime == old_mtime, "Liveness file should not be touched after failed cycle"


@pytest.mark.asyncio
async def test_liveness_touch_failure_does_not_raise(monkeypatch):
    """When the liveness path is unwritable, the error is swallowed — loop continues."""
    monkeypatch.setenv("TRIGGERD_LIVENESS_FILE", "/proc/__nonexistent__/triggerd-alive")
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_for_liveness_test(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(return_value=None)

    import triggerd.engine

    monkeypatch.setattr(triggerd.engine.Engine, "run_cycle", run_cycle_mock)

    import asyncio

    # Should complete without raising
    await async_main(once=True, dry_run=True, should_stop=asyncio.Event())
    run_cycle_mock.assert_called_once()
    tdb_mock.aclose.assert_called_once()
