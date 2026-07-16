"""TUI clients — thin re-exports of firnline_core.uiclients + settings-bound factories."""
from __future__ import annotations

from firnline_core.indexed_client import (  # noqa: F401
    EntityCandidate,
    IndexedClient,
    IndexedError,
)
from firnline_core.uiclients import (  # noqa: F401
    CapturedClient,
    QuerydClient,
    ServiceHealthClient,
    TdbBrowser,
    UiClientError,
    class_display_fields,
    schema_classes,
)

# TUI-specific alias for naming symmetry
TuiClientError = UiClientError


def make_tdb_browser() -> TdbBrowser:
    """Return a TdbBrowser configured from TUI application settings."""
    from firnline_tui.settings import get_settings

    s = get_settings()
    return TdbBrowser(
        s.tdb_url,
        s.tdb_org,
        s.tdb_db,
        s.tdb_user,
        s.tdb_password,
        branch=s.tdb_branch,
        timeout=s.request_timeout_seconds,
        author="service:tui",
    )


def make_health_clients() -> tuple[CapturedClient, QuerydClient, ServiceHealthClient, ServiceHealthClient]:
    """Return (CapturedClient, QuerydClient, indexed_client, mcpd_client)."""
    from firnline_tui.settings import get_settings

    s = get_settings()
    timeout = s.request_timeout_seconds
    return (
        CapturedClient(s.captured_url, s.captured_api_token, timeout=timeout),
        QuerydClient(s.queryd_url, s.queryd_api_token, timeout=timeout),
        ServiceHealthClient(s.indexed_url, token=s.indexed_api_token, timeout=timeout),
        ServiceHealthClient(s.mcpd_url, timeout=timeout),
    )


def make_captured_client() -> CapturedClient:
    """Return a CapturedClient configured from TUI settings."""
    from firnline_tui.settings import get_settings

    s = get_settings()
    return CapturedClient(s.captured_url, s.captured_api_token, timeout=s.request_timeout_seconds)


def make_indexed_client() -> IndexedClient:
    """Return an IndexedClient configured from TUI settings."""
    from firnline_tui.settings import get_settings

    s = get_settings()
    return IndexedClient(
        s.indexed_url,
        token=s.indexed_api_token,
        timeout=s.request_timeout_seconds,
    )
