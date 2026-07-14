"""Tests for liveness file behaviour in ingestd main loop."""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import AsyncMock

import pytest

from ingestd.main import async_main
from firnline_core.plugins import DiscoveryResult

# ── Helpers ────────────────────────────────────────────────────────────


def _patch_ingestd_for_liveness(monkeypatch, tdb_mock):
    """Common patching so we don't need LLM settings or real plugins."""
    monkeypatch.setattr("ingestd.main.TdbClient", lambda **kw: tdb_mock)
    monkeypatch.setattr("firnline_core.plugins.discover_plugins", lambda group: DiscoveryResult(active=[]))
    monkeypatch.setattr("firnline_core.plugins.check_requirements",
                        lambda tdb, reqs, branch="main", registry=None, required_classes=None: [])

    # Patch the two discovery helpers so they don't raise on empty plugins
    async def _fake_extractor_ctx(tdb, branch, logger, strict=False):
        return _FakeExtractionCtx()

    async def _fake_source_plugins(tdb, branch, logger, strict=False):
        return []

    monkeypatch.setattr(
        "ingestd.main._discover_extractor_plugins_async",
        _fake_extractor_ctx,
    )
    monkeypatch.setattr(
        "ingestd.main._discover_source_plugins_async",
        _fake_source_plugins,
    )

    monkeypatch.setenv("INGESTD_TDB_DB", "test")
    monkeypatch.setenv("INGESTD_TDB_PASSWORD", "test")
    monkeypatch.setenv("INGESTD_LLM_BASE_URL", "http://x")
    monkeypatch.setenv("INGESTD_LLM_API_KEY", "k")
    monkeypatch.setenv("INGESTD_LLM_MODEL", "m")


class _FakeExtractionCtx:
    """Minimal fake extraction context for test."""

    plugins = []
    kind_to_plugin = {}


@pytest.mark.asyncio
async def test_liveness_file_touched_after_successful_cycle(monkeypatch):
    """Liveness file is created/touched after a successful cycle."""
    tmp_file = pathlib.Path(tempfile.mktemp(suffix="-ingestd-liveness"))
    tmp_file.touch()

    monkeypatch.setenv("INGESTD_LIVENESS_FILE", str(tmp_file))
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_ingestd_for_liveness(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(return_value=None)

    import ingestd.pipeline

    monkeypatch.setattr(ingestd.pipeline.Pipeline, "run_cycle", run_cycle_mock)

    import asyncio

    await async_main(once=True, dry_run=True, should_stop=asyncio.Event())

    run_cycle_mock.assert_called_once()
    assert tmp_file.exists(), "Liveness file should exist after successful cycle"


@pytest.mark.asyncio
async def test_liveness_file_not_touched_after_failed_cycle(monkeypatch):
    """Liveness file is NOT updated when a cycle fails."""
    tmp_file = pathlib.Path(tempfile.mktemp(suffix="-ingestd-liveness"))
    tmp_file.touch()
    old_mtime = tmp_file.stat().st_mtime

    monkeypatch.setenv("INGESTD_LIVENESS_FILE", str(tmp_file))
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_ingestd_for_liveness(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(side_effect=RuntimeError("boom"))

    import ingestd.pipeline

    monkeypatch.setattr(ingestd.pipeline.Pipeline, "run_cycle", run_cycle_mock)

    import asyncio

    with pytest.raises(SystemExit):
        await async_main(once=True, dry_run=True, should_stop=asyncio.Event())

    new_mtime = tmp_file.stat().st_mtime
    assert new_mtime == old_mtime, "Liveness file should not be touched after failed cycle"


@pytest.mark.asyncio
async def test_liveness_touch_failure_does_not_raise(monkeypatch):
    """When the liveness path is unwritable, the error is swallowed — loop continues."""
    monkeypatch.setenv("INGESTD_LIVENESS_FILE", "/proc/__nonexistent__/ingestd-alive")
    tdb_mock = AsyncMock()
    tdb_mock.aclose = AsyncMock()
    _patch_ingestd_for_liveness(monkeypatch, tdb_mock)

    run_cycle_mock = AsyncMock(return_value=None)

    import ingestd.pipeline

    monkeypatch.setattr(ingestd.pipeline.Pipeline, "run_cycle", run_cycle_mock)

    import asyncio

    # Should complete without raising
    await async_main(once=True, dry_run=True, should_stop=asyncio.Event())
    run_cycle_mock.assert_called_once()
    tdb_mock.aclose.assert_called_once()
