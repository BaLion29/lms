"""Shared structlog configuration for all Firnline services."""

from __future__ import annotations

import logging
import structlog


_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog and stdlib logging with the given *level*.

    *level* is validated case-insensitively.  Unknown values trigger a
    warning and fall back to ``"INFO"``.
    """
    # ── Validate level ──────────────────────────────────────────────────
    upper = level.upper()
    invalid = upper not in _VALID_LEVELS
    if invalid:
        upper = "INFO"

    # ── stdlib logging (uvicorn, httpx, …) ──────────────────────────────
    logging.basicConfig(level=upper, force=True)

    # ── structlog ───────────────────────────────────────────────────────
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, upper),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ── Warn if invalid level was requested (after configure) ──────────
    if invalid:
        logger = structlog.get_logger("firnline_core.logging")
        logger.warning(
            "invalid_log_level",
            requested=level,
            fallback="INFO",
        )
