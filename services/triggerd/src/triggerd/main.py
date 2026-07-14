"""Console entrypoint for the triggerd evaluation service."""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import signal
import sys

import structlog

from triggerd.engine import Engine
from triggerd.settings import Settings
from firnline_core.plugins import HostPolicy, PluginHost, TriggerEvaluator
from firnline_core.repository import Repository
from firnline_core.tdb import TdbClient


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


async def run_cycle_safe(engine: Engine, should_stop: asyncio.Event | None) -> bool:
    """Run one cycle, returning False if a cycle-level exception was caught."""
    try:
        await engine.run_cycle(should_stop)
    except Exception:
        structlog.get_logger(__name__).exception("cycle_failed")
        return False
    return True


# ---------------------------------------------------------------------------
# Plugin discovery via PluginHost
# ---------------------------------------------------------------------------

_EVALUATOR_GROUP = "firnline.triggerd.evaluators"


async def _discover_evaluator_plugins_async(
    tdb: TdbClient,
    branch: str,
    logger,
    strict: bool = False,
) -> list[object]:
    """Discover evaluator plugins via :class:`PluginHost`.

    Returns a flat list of active plugin objects.  Raises
    ``RuntimeError`` on broken entry points or trigger_types collisions.
    Zero active evaluators is a warning, not fatal.
    """
    host = PluginHost(
        group=_EVALUATOR_GROUP,
        protocol=TriggerEvaluator,
        tdb=tdb,
        branch=branch,
        policy=HostPolicy(broken_entry_point_fatal=True, zero_active_fatal=False, strict=strict),
        logger=logger,
    )
    result = await host.start(collision_key=lambda ev: ev.trigger_types)
    return [obj for _, obj in result.active]


# ---------------------------------------------------------------------------
# Main async entrypoint
# ---------------------------------------------------------------------------


async def async_main(
    once: bool,
    dry_run: bool,
    should_stop: asyncio.Event,
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    if dry_run:
        settings = settings.model_copy(update={"dry_run": True})

    logger = structlog.get_logger(__name__)
    branch = settings.tdb_branch

    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
        author="service:triggerd",
    )

    repo = Repository(tdb)

    # ── Discover evaluator plugins ──────────────────────────────────
    try:
        evaluators = await _discover_evaluator_plugins_async(repo.tdb, branch, logger, strict=settings.strict_plugins)
    except (RuntimeError, ValueError):
        logger.exception("evaluator_plugin_discovery_failed")
        sys.exit(1)

    logger.info(
        "plugin_startup_complete",
        evaluator_count=len(evaluators),
        evaluator_names=[getattr(e, "name", "?") for e in evaluators],
    )

    engine = Engine(repo=repo, settings=settings, evaluators=evaluators, logger=logger)

    last_cycle_ok = True
    liveness_path = pathlib.Path(settings.liveness_file)
    try:
        while not should_stop.is_set():
            last_cycle_ok = await run_cycle_safe(engine, should_stop)
            # Touch liveness file only on success so a wedged/failing daemon
            # becomes unhealthy.  Touching failures must never crash the loop.
            if last_cycle_ok:
                try:
                    liveness_path.touch(exist_ok=True)
                except OSError:
                    pass
            if once or should_stop.is_set():
                break
            # Interruptible sleep
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

    parser = argparse.ArgumentParser(description="triggerd — trigger evaluation daemon")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single evaluation cycle and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate but do not write anything to the database.",
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
            # Windows / unsupported platform
            pass

    try:
        loop.run_until_complete(async_main(args.once, args.dry_run, should_stop))
    except Exception:
        logger.exception("fatal_error")
        sys.exit(1)
    finally:
        loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
