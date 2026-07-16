"""AppContext — shared environment + client factory seam (DI for tests)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from firnline_core.indexed_client import IndexedClient
from firnline_core.uiclients import CapturedClient, QuerydClient, ServiceHealthClient, TdbBrowser


@dataclass(frozen=True)
class AppContext:
    """Shared environment + client factories (DI seam for tests).

    Screens reach this via ``self.app.ctx``.
    """

    org: str
    db: str
    branch: str
    make_tdb: Callable[[], TdbBrowser]
    make_captured: Callable[[], CapturedClient]
    make_health: Callable[[], tuple[CapturedClient, QuerydClient, ServiceHealthClient, ServiceHealthClient]]
    make_indexed: Callable[[], IndexedClient]


def default_context() -> AppContext:
    """Build an AppContext from TUI settings."""
    from firnline_tui.clients import make_captured_client, make_health_clients, make_indexed_client, make_tdb_browser
    from firnline_tui.settings import get_settings

    s = get_settings()
    return AppContext(
        org=s.tdb_org,
        db=s.tdb_db,
        branch=s.tdb_branch,
        make_tdb=make_tdb_browser,
        make_captured=make_captured_client,
        make_health=make_health_clients,
        make_indexed=make_indexed_client,
    )
