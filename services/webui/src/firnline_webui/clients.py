"""Async HTTP clients — re-exported from firnline_core.uiclients.

The canonical implementation now lives in firnline_core.uiclients so
both the WebUI and the TUI share one source of truth.
"""
from firnline_core.uiclients import (  # noqa: F401
    CapturedClient,
    QuerydClient,
    ServiceHealthClient,
    TdbBrowser,
    UiClientError,
    class_display_fields,
    schema_classes,
)

# Backward-compat alias
WebuiClientError = UiClientError


def make_tdb_browser() -> TdbBrowser:
    """Return a TdbBrowser configured from WebUI application settings."""
    from firnline_webui.settings import get_settings

    s = get_settings()
    return TdbBrowser(
        s.tdb_url,
        s.tdb_org,
        s.tdb_db,
        s.tdb_user,
        s.tdb_password,
        branch=s.tdb_branch,
        timeout=s.request_timeout_seconds,
        author="service:webui",
    )


def make_health_clients():
    """Return (CapturedClient, QuerydClient, indexed_client, mcpd_client)."""
    from firnline_webui.settings import get_settings

    s = get_settings()
    timeout = s.request_timeout_seconds
    return (
        CapturedClient(s.captured_url, s.captured_api_token, timeout=timeout),
        QuerydClient(s.queryd_url, s.queryd_api_token, timeout=timeout),
        ServiceHealthClient(s.indexed_url, token=s.indexed_api_token, timeout=timeout),
        ServiceHealthClient(s.mcpd_url, timeout=timeout),
    )
