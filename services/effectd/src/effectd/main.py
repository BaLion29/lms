"""Console entrypoint for the effectd effect delivery service."""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import signal
import sys
import warnings

import structlog
from typing import Any

from effectd.engine import EffectEngine
from effectd.settings import EffectdSettings
from firnline_core.plugins import (
    ActionExecutor,
    ChannelExecutorAdapter,
    HostPolicy,
    NotificationChannel,
    PluginHost,
)
from firnline_core.repository import Repository
from firnline_core.logging import configure_logging
from firnline_core.tdb import TdbClient

_CHANNEL_GROUP = "firnline.notifyd.channels"
_EXECUTOR_GROUP = "firnline.effectd.executors"


async def run_cycle_safe(engine: EffectEngine, should_stop: asyncio.Event | None) -> bool:
    """Run one cycle, returning False if a cycle-level exception was caught."""
    try:
        await engine.run_cycle(should_stop)
    except Exception:
        structlog.get_logger(__name__).exception("cycle_failed")
        return False
    return True


async def _discover_channel_plugins_async(
    tdb: TdbClient,
    branch: str,
    logger: Any,
    strict: bool = False,
) -> list[object]:
    """Discover notification channel plugins, check requirements, return active ones.

    Zero active channels is NOT fatal: the service idles gracefully,
    logging a clear message once at startup.
    """
    host = PluginHost(
        group=_CHANNEL_GROUP,
        protocol=NotificationChannel,
        tdb=tdb,
        branch=branch,
        policy=HostPolicy(
            broken_entry_point_fatal=False,
            zero_active_fatal=False,
        ),
        logger=logger,
    )
    result = await host.start(collision_key=lambda c: [c.name])
    return [obj for _, obj in result.active]


async def _discover_executor_plugins_async(
    tdb: TdbClient,
    branch: str,
    logger: Any,
    strict: bool = False,
) -> list[Any]:
    """Discover native ActionExecutor plugins, return active ones."""
    host = PluginHost(
        group=_EXECUTOR_GROUP,
        protocol=ActionExecutor,
        tdb=tdb,
        branch=branch,
        policy=HostPolicy(
            broken_entry_point_fatal=False,
            zero_active_fatal=False,
            strict=strict,
        ),
        logger=logger,
    )
    result = await host.start(collision_key=lambda e: e.kinds)
    return [obj for _, obj in result.active]


def _adapt_channels(
    channels: list[object],
    native_executors: list[Any],
    logger: Any,
) -> list[Any]:
    """Adapt legacy channels to executors, skipping kind collisions.

    Skips any channel whose ``notify:<name>`` kind already appears
    among native executor kinds (forward-compat for M4 dual registration).
    Logs a ``DeprecationWarning``-style warning for each adapted plugin.
    """
    native_kinds: set[str] = set()
    for ex in native_executors:
        for kind in ex.kinds:
            native_kinds.add(kind)

    adapted: list[Any] = []
    for channel in channels:
        name = getattr(channel, "name", "?")
        kind = f"notify:{name}"
        if kind in native_kinds:
            if logger is not None:
                logger.info("channel_adapt_skipped_duplicate_kind", channel=name, kind=kind)
            continue
        adapter = ChannelExecutorAdapter(channel)
        adapted.append(adapter)
        warnings.warn(
            f"Adapting legacy channel '{name}' to ActionExecutor — "
            f"migrate to native executor plugin registering as kind '{kind}'",
            DeprecationWarning,
            stacklevel=2,
        )
        if logger is not None:
            logger.warning("channel_adapted_as_executor", channel=name, kind=kind)

    return adapted


def _check_merged_kind_collisions(
    native_executors: list[Any],
    adapted_executors: list[Any],
    logger: Any,  # pylint: disable=unused-argument — kept for future use
) -> None:
    """Check for kind collisions across native and adapted executors.

    PluginHost collision detection runs per-group, so we manually verify
    that the merged set has no duplicated kinds.
    """
    seen: dict[str, tuple[str, str]] = {}  # kind → (source_name, source)
    for ex in native_executors:
        source = getattr(ex, "name", "?")
        for kind in ex.kinds:
            if kind in seen:
                other_name, other_source = seen[kind]
                raise RuntimeError(
                    f"Executor kind collision on {kind!r}: "
                    f"native '{source}' and '{other_name}' ({other_source})"
                )
            seen[kind] = (source, "native")
    for ex in adapted_executors:
        source = getattr(ex, "name", "?")
        for kind in ex.kinds:
            if kind in seen:
                other_name, other_source = seen[kind]
                raise RuntimeError(
                    f"Executor kind collision on {kind!r}: "
                    f"adapted '{source}' and '{other_name}' ({other_source})"
                )
            seen[kind] = (source, "adapted")


async def async_main(
    once: bool,
    should_stop: asyncio.Event,
    settings: EffectdSettings | None = None,
) -> None:
    if settings is None:
        settings = EffectdSettings()  # type: ignore[call-arg]
    logger = structlog.get_logger(__name__)
    branch = settings.tdb_branch

    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        author="service:effectd",
    )

    repo = Repository(tdb, transitions={
        "TriggerFiring": {
            "pending": ["notified"],
            "notified": ["acknowledged", "snoozed", "expired"],
            "snoozed": ["notified", "expired"],
            "acknowledged": [],
            "expired": [],
        },
        "ActionExecution": {
            "pending_approval": ["pending"],
            "pending": ["succeeded", "failed", "dead"],
            "succeeded": [],
            "failed": [],
            "dead": [],
            "skipped": [],
        },
    })

    # ── Discover channel plugins ────────────────────────────────────
    try:
        channels = await _discover_channel_plugins_async(
            repo.tdb, branch, logger,
            strict=settings.strict_plugins,
        )
    except (RuntimeError, ValueError):
        logger.exception("channel_plugin_discovery_failed")
        sys.exit(1)

    logger.info(
        "plugin_startup_complete",
        channel_count=len(channels),
        channel_names=[getattr(c, "name", "?") for c in channels],
    )

    # ── Discover native ActionExecutor plugins ──────────────────────
    try:
        native_executors = await _discover_executor_plugins_async(
            repo.tdb, branch, logger,
            strict=settings.strict_plugins,
        )
    except (RuntimeError, ValueError):
        logger.exception("executor_plugin_discovery_failed")
        sys.exit(1)

    logger.info(
        "executor_startup_complete",
        executor_count=len(native_executors),
        executor_names=[getattr(e, "name", "?") for e in native_executors],
    )

    # ── Adapt legacy channels to executors ──────────────────────────
    adapted_executors = _adapt_channels(channels, native_executors, logger)

    # ── Merge and collision-check ───────────────────────────────────
    _check_merged_kind_collisions(native_executors, adapted_executors, logger)
    all_executors = native_executors + adapted_executors

    logger.info(
        "executors_ready",
        native_count=len(native_executors),
        adapted_count=len(adapted_executors),
    )

    engine = EffectEngine(
        repo=repo,
        channels=channels,  # raw channels for legacy loop
        executors=all_executors,
        settings=settings,
        logger=logger,
    )

    last_cycle_ok = True
    liveness_path = pathlib.Path(settings.liveness_file)
    try:
        while not should_stop.is_set():
            last_cycle_ok = await run_cycle_safe(engine, should_stop)
            if last_cycle_ok:
                try:
                    liveness_path.touch(exist_ok=True)
                except OSError:
                    pass
            if once or should_stop.is_set():
                break
            try:
                await asyncio.wait_for(
                    should_stop.wait(),
                    timeout=settings.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await repo.tdb.aclose()

    if once and not last_cycle_ok:
        sys.exit(1)


def main() -> None:
    settings = EffectdSettings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    logger = structlog.get_logger(__name__)

    parser = argparse.ArgumentParser(description="effectd — effect delivery daemon")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single delivery cycle and exit.",
    )
    args = parser.parse_args()

    should_stop = asyncio.Event()
    loop = asyncio.new_event_loop()

    def _handle_signal() -> None:
        logger.info("shutdown_signal_received")
        should_stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(async_main(args.once, should_stop, settings))
    except Exception:
        logger.exception("fatal_error")
        sys.exit(1)
    finally:
        loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
