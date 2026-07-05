"""Console entrypoint for the ingestd extraction service."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

import structlog

from ingestd.extraction import build_agent, build_llm_model
from ingestd.pipeline import Pipeline
from ingestd.settings import Settings
from ingestd.tdb import TdbClient


def validate_llm_settings(settings: Settings) -> None:
    """Validate that required LLM settings are non-empty.

    Prints an error and exits with code 2 if any are missing.
    """
    missing: list[str] = []
    if not settings.llm_base_url:
        missing.append("INGESTD_LLM_BASE_URL")
    if not settings.llm_api_key:
        missing.append("INGESTD_LLM_API_KEY")
    if not settings.llm_model:
        missing.append("INGESTD_LLM_MODEL")
    if missing:
        logger = structlog.get_logger(__name__)
        logger.error("missing_llm_settings", missing=missing)
        sys.exit(2)


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


async def run_cycle_safe(pipeline: Pipeline, should_stop: asyncio.Event | None) -> bool:
    """Run one cycle, returning False if a cycle-level exception was caught."""
    try:
        await pipeline.run_cycle(should_stop)
    except Exception:
        structlog.get_logger(__name__).exception("cycle_failed")
        return False
    return True


async def async_main(
    once: bool,
    dry_run: bool,
    should_stop: asyncio.Event,
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    if dry_run:
        settings = settings.model_copy(update={"dry_run": True})

    validate_llm_settings(settings)

    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
    )

    model = build_llm_model(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
    )
    agent = build_agent(model)

    pipeline = Pipeline(tdb=tdb, agent=agent, settings=settings)

    last_cycle_ok = True
    try:
        while not should_stop.is_set():
            last_cycle_ok = await run_cycle_safe(pipeline, should_stop)
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

    parser = argparse.ArgumentParser(
        description="ingestd — LLM-powered inbox extraction service"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single extraction cycle and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract but do not write anything to the database.",
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
