"""Smoke test: single --once --dry-run cycle completes without error, tdb.aclose() is called."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from triggerd.main import async_main
from firnline_core.tdb import TdbClient


@pytest.mark.asyncio
async def test_once_dry_run_cycle_completes(monkeypatch):
    """Simulate a single --once --dry-run cycle against an AsyncMock TdbClient.

    The loop body is exercised because once=True and should_stop is NOT
    pre-set (the ``if once: break`` exits after one cycle).
    Assertions:
    - async_main returns without raising.
    - Engine.run_cycle is called exactly once.
    - tdb.aclose() is called exactly once.
    """
    # Patch discover_plugins to return empty (no evaluators → warning, not crash)
    from firnline_core.plugins import DiscoveryResult

    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        lambda group: DiscoveryResult(active=[]),
    )

    # Patch check_requirements to always pass
    async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
        return []

    monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

    tdb_mock = AsyncMock(spec=TdbClient)
    tdb_mock.aclose = AsyncMock()

    # Patch TdbClient constructor
    monkeypatch.setattr("triggerd.main.TdbClient", lambda **kw: tdb_mock)

    # Patch Settings to provide required fields
    monkeypatch.setenv("TRIGGERD_TDB_DB", "smoke")
    monkeypatch.setenv("TRIGGERD_TDB_PASSWORD", "smoke")

    # Spy on Engine.run_cycle
    run_cycle_mock = AsyncMock()

    import triggerd.engine

    monkeypatch.setattr(triggerd.engine.Engine, "run_cycle", run_cycle_mock)

    should_stop = asyncio.Event()
    # Do NOT pre-set should_stop — the loop runs via once=True → break

    await async_main(once=True, dry_run=True, should_stop=should_stop)

    run_cycle_mock.assert_called_once()
    tdb_mock.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_once_failed_cycle_exits_nonzero(monkeypatch):
    """When once=True and a cycle raises → sys.exit(1)."""
    from firnline_core.plugins import DiscoveryResult

    monkeypatch.setattr(
        "firnline_core.plugins.discover_plugins",
        lambda group: DiscoveryResult(active=[]),
    )

    async def _noop_check(tdb, reqs, branch="main", registry=None, required_classes=None):
        return []

    monkeypatch.setattr("firnline_core.plugins.check_requirements", _noop_check)

    tdb_mock = AsyncMock(spec=TdbClient)
    tdb_mock.aclose = AsyncMock()
    monkeypatch.setattr("triggerd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setenv("TRIGGERD_TDB_DB", "smoke")
    monkeypatch.setenv("TRIGGERD_TDB_PASSWORD", "smoke")

    # Make Engine.run_cycle raise
    run_cycle_mock = AsyncMock(side_effect=RuntimeError("boom"))

    import triggerd.engine

    monkeypatch.setattr(triggerd.engine.Engine, "run_cycle", run_cycle_mock)

    should_stop = asyncio.Event()

    with pytest.raises(SystemExit) as exc_info:
        await async_main(once=True, dry_run=True, should_stop=should_stop)

    assert exc_info.value.code == 1
    tdb_mock.aclose.assert_called_once()
