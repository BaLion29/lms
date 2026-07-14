"""Smoke test: single --once cycle completes without error, imports work."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from effectd.main import async_main
from firnline_core.plugins import HostResult
from firnline_core.tdb import TdbClient


@pytest.mark.asyncio
async def test_once_cycle_completes(monkeypatch):
    """Simulate a single --once cycle against an AsyncMock TdbClient."""

    async def _fake_start(self, **kw):
        return HostResult(active=[])

    monkeypatch.setattr(
        "firnline_core.plugins.PluginHost.start", _fake_start
    )

    tdb_mock = AsyncMock(spec=TdbClient)
    tdb_mock.aclose = AsyncMock()
    monkeypatch.setattr("effectd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setenv("EFFECTD_TDB_DB", "smoke")
    monkeypatch.setenv("EFFECTD_TDB_PASSWORD", "smoke")

    run_cycle_mock = AsyncMock()

    import effectd.engine

    monkeypatch.setattr(effectd.engine.EffectEngine, "run_cycle", run_cycle_mock)

    should_stop = asyncio.Event()

    await async_main(once=True, should_stop=should_stop)

    run_cycle_mock.assert_called_once()
    tdb_mock.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_once_failed_cycle_exits_nonzero(monkeypatch):
    """When once=True and a cycle raises → sys.exit(1)."""

    async def _fake_start(self, **kw):
        return HostResult(active=[])

    monkeypatch.setattr(
        "firnline_core.plugins.PluginHost.start", _fake_start
    )

    tdb_mock = AsyncMock(spec=TdbClient)
    tdb_mock.aclose = AsyncMock()
    monkeypatch.setattr("effectd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setenv("EFFECTD_TDB_DB", "smoke")
    monkeypatch.setenv("EFFECTD_TDB_PASSWORD", "smoke")

    run_cycle_mock = AsyncMock(side_effect=RuntimeError("boom"))

    import effectd.engine

    monkeypatch.setattr(effectd.engine.EffectEngine, "run_cycle", run_cycle_mock)

    should_stop = asyncio.Event()

    with pytest.raises(SystemExit) as exc_info:
        await async_main(once=True, should_stop=should_stop)

    assert exc_info.value.code == 1
    tdb_mock.aclose.assert_called_once()


def test_imports():
    """All public modules can be imported."""
