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
from firnline_core.plugins import discover_plugins, select_plugins
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
# Plugin discovery helpers
# ---------------------------------------------------------------------------

_EVALUATOR_GROUP = "firnline.triggerd.evaluators"


async def _discover_evaluator_plugins_async(
    tdb: TdbClient,
    branch: str,
    logger,
    strict: bool = False,
) -> list[object]:
    """Discover evaluator plugins, check requirements, return active ones.

    Raises ``RuntimeError`` on broken entry points or
    ``trigger_types`` collisions.  Unlike ingestd, zero active evaluators
    is *not* fatal: an evaluator-less triggerd is semantically "everything
    unsupported" rather than broken.  Evaluators are added in a later
    phase.
    """
    discovered = discover_plugins(_EVALUATOR_GROUP)
    logger.info(
        "evaluator_plugins_discovered",
        group=_EVALUATOR_GROUP,
        count=len(discovered.active),
        failed=len(discovered.failed),
    )

    # Broken entry points ARE fatal
    if discovered.failed:
        names = [n for n, _ in discovered.failed]
        raise RuntimeError(f"Evaluator plugin entry points failed to load: {names}")

    selection = await select_plugins(tdb, discovered, strict=strict, branch=branch)

    for name, violations in selection.skipped:
        logger.warning(
            "evaluator_plugin_skipped",
            plugin=name,
            violations=violations,
        )

    # Deviating from ingestd: zero active evaluators is a warning, not fatal.
    # An evaluator-less triggerd is semantically "everything unsupported."
    if not selection.active:
        logger.warning("no_active_evaluator_plugins", message="no evaluators — nothing will fire")
        return []

    # Duck-typing: each evaluator needs name, trigger_types, and occurrences method
    evaluators: list[object] = []
    seen_types: set[str] = set()

    for name, obj in selection.active:
        if not hasattr(obj, "name") or not hasattr(obj, "trigger_types") or not hasattr(obj, "occurrences"):
            logger.warning("plugin_not_evaluator", name=name)
            continue

        trigger_types = obj.trigger_types
        if not isinstance(trigger_types, (tuple, list)):
            logger.warning("plugin_bad_trigger_types", name=name, reason="trigger_types must be a tuple/list")
            continue
        if not callable(obj.occurrences):
            logger.warning("plugin_bad_occurrences", name=name, reason="occurrences must be callable")
            continue

        for ttype in trigger_types:
            if ttype in seen_types:
                raise RuntimeError(
                    f"Evaluator collision: @type {ttype!r} claimed by both {name!r} and another active evaluator"
                )
            seen_types.add(ttype)

        evaluators.append(obj)

    if not evaluators:
        logger.warning("no_valid_evaluator_plugins", message="discovered plugins are not valid evaluators")

    return evaluators


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
    )

    # ── Discover evaluator plugins ──────────────────────────────────
    try:
        evaluators = await _discover_evaluator_plugins_async(tdb, branch, logger, strict=settings.strict_plugins)
    except (RuntimeError, ValueError):
        logger.exception("evaluator_plugin_discovery_failed")
        sys.exit(1)

    logger.info(
        "plugin_startup_complete",
        evaluator_count=len(evaluators),
        evaluator_names=[getattr(e, "name", "?") for e in evaluators],
    )

    engine = Engine(tdb=tdb, settings=settings, evaluators=evaluators, logger=logger)

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
        await tdb.aclose()

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
