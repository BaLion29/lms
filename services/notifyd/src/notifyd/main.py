"""Console entrypoint for the notifyd notification delivery service."""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import signal
import sys

import structlog
from typing import Any

from notifyd.engine import NotifyEngine
from notifyd.settings import NotifydSettings
from firnline_core.plugins import (
    HostPolicy,
    NotificationChannel,
    PluginHost,
)
from firnline_core.repository import Repository
from firnline_core.tdb import TdbClient

_CHANNEL_GROUP = "firnline.notifyd.channels"


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def run_cycle_safe(engine: NotifyEngine, should_stop: asyncio.Event | None) -> bool:
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


async def async_main(
    once: bool,
    should_stop: asyncio.Event,
) -> None:
    settings = NotifydSettings()  # type: ignore[call-arg]

    logger = structlog.get_logger(__name__)
    branch = settings.tdb_branch

    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        author="service:notifyd",
    )

    repo = Repository(tdb, transitions={
        "TriggerFiring": {
            "pending": ["notified"],
            "notified": ["acknowledged", "snoozed", "expired"],
            "snoozed": ["notified", "expired"],
            "acknowledged": [],
            "expired": [],
        },
    })

    # ── Discover channel plugins ────────────────────────────────────
    try:
        channels = await _discover_channel_plugins_async(repo.tdb, branch, logger)
    except (RuntimeError, ValueError):
        logger.exception("channel_plugin_discovery_failed")
        sys.exit(1)

    logger.info(
        "plugin_startup_complete",
        channel_count=len(channels),
        channel_names=[getattr(c, "name", "?") for c in channels],
    )

    engine = NotifyEngine(repo=repo, channels=channels, logger=logger)

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
    _configure_logging()
    logger = structlog.get_logger(__name__)

    parser = argparse.ArgumentParser(description="notifyd — notification delivery daemon")
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
        loop.run_until_complete(async_main(args.once, should_stop))
    except Exception:
        logger.exception("fatal_error")
        sys.exit(1)
    finally:
        loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
