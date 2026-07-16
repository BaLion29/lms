"""Smoke test: single --once cycle completes without error, imports work."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from effectd.main import async_main
from firnline_core.plugins import HostResult
from firnline_core.tdb import TdbClient


@pytest.fixture
def _patch_discovery(monkeypatch):
    """Patch PluginHost.start for both channel and executor groups."""

    async def _fake_start(self, **kw):
        return HostResult(active=[])

    monkeypatch.setattr("firnline_core.plugins.PluginHost.start", _fake_start)


@pytest.fixture
def _patch_engine(monkeypatch):
    """Patch EffectEngine.run_cycle so no real repo calls happen."""
    import effectd.engine

    monkeypatch.setattr(effectd.engine.EffectEngine, "run_cycle", AsyncMock())


@pytest.fixture
def _patch_tdb(monkeypatch):
    """Patch TdbClient constructor to return an AsyncMock."""
    tdb_mock = AsyncMock(spec=TdbClient)
    tdb_mock.aclose = AsyncMock()
    monkeypatch.setattr("effectd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setenv("EFFECTD_TDB_DB", "smoke")
    monkeypatch.setenv("EFFECTD_TDB_PASSWORD", "smoke")


@pytest.mark.asyncio
async def test_once_cycle_completes(_patch_discovery, _patch_engine, _patch_tdb):
    """Simulate a single --once cycle against an AsyncMock TdbClient."""
    should_stop = asyncio.Event()
    await async_main(once=True, should_stop=should_stop)


@pytest.mark.asyncio
async def test_once_failed_cycle_exits_nonzero(_patch_discovery, _patch_tdb, monkeypatch):
    """When once=True and a cycle raises → sys.exit(1)."""
    import effectd.engine

    monkeypatch.setattr(
        effectd.engine.EffectEngine,
        "run_cycle",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    should_stop = asyncio.Event()

    with pytest.raises(SystemExit) as exc_info:
        await async_main(once=True, should_stop=should_stop)

    assert exc_info.value.code == 1


def test_imports():
    """All public modules can be imported."""
    import importlib

    for mod in ("effectd", "effectd.main", "effectd.engine", "effectd.settings"):
        importlib.import_module(mod)


class TestMainIdle:
    """Main wiring: zero plugins → engine idles."""

    @pytest.mark.asyncio
    async def test_zero_executors_zero_channels_idle(
        self,
        _patch_discovery,
        _patch_engine,
        _patch_tdb,
    ):
        """Zero executors and zero channels → engine starts and idles."""
        should_stop = asyncio.Event()
        await async_main(once=True, should_stop=should_stop)
        # no exception = success
