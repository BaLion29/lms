"""Idempotent schema bootstrap – creates the TerminusDB database and pushes the schema."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from ingestd.settings import Settings
from lms_core.tdb import TdbClient, TdbError

logger = structlog.get_logger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def bootstrap(settings: Settings) -> None:
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
    )

    try:
        # 1. Ensure DB exists
        exists = await tdb.db_exists()
        if exists:
            logger.info("database_already_exists", db=settings.tdb_db)
        else:
            logger.info("creating_database", db=settings.tdb_db)
            await tdb.create_db(
                label=settings.tdb_db,
                comment="created by ingestd bootstrap",
            )
            logger.info("database_created", db=settings.tdb_db)

        # 2. Push schema (idempotent via full_replace=true)
        schema = json.loads(SCHEMA_PATH.read_text())
        logger.info("pushing_schema", path=str(SCHEMA_PATH), count=len(schema))
        await tdb.push_schema(schema)
        logger.info("schema_pushed", count=len(schema))
    finally:
        await tdb.aclose()


def main() -> None:
    _configure_logging()

    settings = Settings()  # type: ignore[call-arg]
    try:
        asyncio.run(bootstrap(settings))
    except TdbError as e:
        logger.error("tdb_error", status=e.status, body=e.body[:500])
        raise SystemExit(1) from e
    except Exception:
        logger.exception("unexpected_error")
        raise SystemExit(1) from None

    print("Bootstrap complete – database and schema are ready.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
