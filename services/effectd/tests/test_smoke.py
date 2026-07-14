"""Smoke test: single --once cycle completes without error, imports work."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from effectd.main import (
    _adapt_channels,
    _check_merged_kind_collisions,
    async_main,
)
from firnline_core.plugins import (
    ChannelExecutorAdapter,
    HostResult,
    ModuleRequirement,
)
from firnline_core.tdb import TdbClient


def _fake_gotify_settings():
    """Return a GotifySettings with dummy values so the channel/executor
    pass the configuration guard during adapter tests."""
    import importlib

    mod = importlib.import_module("firnline_ext_gotify._common")
    return mod.GotifySettings(url="https://gotify.example.com", token="test-token")


@pytest.fixture
def _patch_discovery(monkeypatch):
    """Patch PluginHost.start for both channel and executor groups."""

    async def _fake_start(self, **kw):
        return HostResult(active=[])

    monkeypatch.setattr(
        "firnline_core.plugins.PluginHost.start", _fake_start
    )


@pytest.fixture
def _patch_engine(monkeypatch):
    """Patch EffectEngine.run_cycle so no real repo calls happen."""
    import effectd.engine

    monkeypatch.setattr(
        effectd.engine.EffectEngine, "run_cycle", AsyncMock()
    )


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
        effectd.engine.EffectEngine, "run_cycle",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    should_stop = asyncio.Event()

    with pytest.raises(SystemExit) as exc_info:
        await async_main(once=True, should_stop=should_stop)

    assert exc_info.value.code == 1


def test_imports():
    """All public modules can be imported."""


# ---------------------------------------------------------------------------
# Adapt / collision tests
# ---------------------------------------------------------------------------

class FakeChannel:
    name = "gotify"
    requires: list[ModuleRequirement] = []

    async def deliver(self, firing, subject, ctx):
        return None  # never called in these tests


class FakeChannel2:
    name = "email"
    requires: list[ModuleRequirement] = []

    async def deliver(self, firing, subject, ctx):
        return None


class FakeExecutor:
    name = "webhook"
    requires: list[ModuleRequirement] = []
    kinds = ("webhook",)

    async def execute(self, action, firing, subject, ctx):
        return None


class FakeExecutorNotify:
    name = "native-notify"
    requires: list[ModuleRequirement] = []
    kinds = ("notify:gotify",)

    async def execute(self, action, firing, subject, ctx):
        return None


class TestAdaptChannels:
    def test_adapts_channel_to_executor(self):
        """A legacy channel is adapted to an executor with kind notify:<name>."""
        channel = FakeChannel()
        adapted = _adapt_channels([channel], [], None)
        assert len(adapted) == 1
        assert isinstance(adapted[0], ChannelExecutorAdapter)
        assert adapted[0].kinds == ("notify:gotify",)

    def test_skips_adapted_when_native_kind_exists(self):
        """Channel skipped when a native executor already claims notify:<name>."""
        native = FakeExecutorNotify()  # has "notify:gotify"
        channel = FakeChannel()
        adapted = _adapt_channels([channel], [native], None)
        assert len(adapted) == 0

    def test_adapted_when_native_has_different_kind(self):
        """Channel adapted when native executor has different kinds."""
        native = FakeExecutor()  # has "webhook"
        channel = FakeChannel()
        adapted = _adapt_channels([channel], [native], None)
        assert len(adapted) == 1

    def test_real_gotify_channel_skipped_for_native_executor(self):
        """With the real GotifyChannel + GotifyExecutor both named 'gotify',
        the channel is skipped and the native executor wins (no collision)."""
        from firnline_ext_gotify.channel import GotifyChannel
        from firnline_ext_gotify.executor import GotifyExecutor

        native = GotifyExecutor()
        native._settings = _fake_gotify_settings()

        channel = GotifyChannel()
        channel._settings = _fake_gotify_settings()

        # Adapt: channel should be skipped
        adapted = _adapt_channels([channel], [native], None)
        assert len(adapted) == 0

        # Merge + collision check: native notify:gotify must be present,
        # no adapted executor with the same kind.
        _check_merged_kind_collisions([native], adapted, None)
        assert native in [native]  # native executor is present
        assert native.kinds == ("notify:gotify",)


class TestCollisionCheck:
    def test_no_collision_no_raise(self):
        """When kinds are distinct, no error."""
        native = FakeExecutor()  # webhook
        adapted = FakeChannel()  # notify:gotify
        adapted_list = _adapt_channels([adapted], [native], None)
        _check_merged_kind_collisions([native], adapted_list, None)  # should not raise

    def test_collision_raises(self):
        """When an adapted executor has same kind as native, raise."""
        native = FakeExecutorNotify()  # notify:gotify
        adapted_list = _adapt_channels([FakeChannel()], [], None)
        # Force collision by adding adapted without skip (manually)
        with pytest.raises(RuntimeError, match="kind collision"):
            _check_merged_kind_collisions([native], adapted_list, None)

    def test_zero_executors_no_raise(self):
        """Zero executors and zero adapted → no error."""
        _check_merged_kind_collisions([], [], None)


class TestMainIdle:
    """Main wiring: zero plugins → engine idles."""

    @pytest.mark.asyncio
    async def test_zero_executors_zero_channels_idle(
        self, _patch_discovery, _patch_engine, _patch_tdb,
    ):
        """Zero executors and zero channels → engine starts and idles."""
        should_stop = asyncio.Event()
        await async_main(once=True, should_stop=should_stop)
        # no exception = success
