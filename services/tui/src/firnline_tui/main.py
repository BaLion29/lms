"""Entry point for firnline-tui."""
from __future__ import annotations

import asyncio
import logging
import sys

from firnline_tui.app import FirnlineApp
from firnline_tui.clients import make_tdb_browser
from firnline_tui.screen_registry import build_screen_registry
from firnline_tui.settings import get_settings

log = logging.getLogger(__name__)


def main() -> None:
    """Build registry and launch the TUI."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    settings = get_settings()
    tdb = make_tdb_browser()

    async def _build():
        try:
            return await build_screen_registry(
                tdb,
                timeout=settings.plugin_registry_timeout_seconds,
            )
        finally:
            await tdb.aclose()

    registry = asyncio.run(_build())

    app = FirnlineApp(registry=registry)
    app.run()


if __name__ == "__main__":
    main()
