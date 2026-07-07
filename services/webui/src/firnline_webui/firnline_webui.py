"""Reflex app entry point for firnline-webui.

This file must be importable as ``firnline_webui.firnline_webui`` at the root
of the Reflex project (``services/webui/``). Because the package lives under
``src/firnline_webui/`` (hatchling src layout), ``uv run`` installs the
package in dev mode, making the import work automatically.
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version

import reflex as rx

from firnline_webui.pages.browse import browse_class_page, browse_page
from firnline_webui.pages.calendar import calendar_page
from firnline_webui.pages.capture import capture_page
from firnline_webui.pages.chat import chat_page
from firnline_webui.pages.health import health_page
from firnline_webui.pages.home import home_page
from firnline_webui.pages.inbox import inbox_page
from firnline_webui.pages.login import login_page
from firnline_webui.pages.modules import modules_page
from firnline_webui.state.auth import AuthState
from firnline_webui.state.browse import BrowseClassState, BrowseState
from firnline_webui.state.calendar import CalendarState
from firnline_webui.state.capture import CaptureState
from firnline_webui.state.chat import ChatState
from firnline_webui.state.health import HealthState
from firnline_webui.state.inbox import InboxState
from firnline_webui.state.modules import ModulesState

__all__ = ["app"]


def _api_healthz(app):
    """Add ``GET /healthz`` endpoint returning status and version."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    try:
        ver = pkg_version("firnline-webui")
    except Exception:
        ver = "unknown"

    async def healthz(request):
        return JSONResponse({"status": "ok", "version": ver})

    app.routes.append(Route("/healthz", healthz, methods=["GET"]))
    return app


app = rx.App(
    theme=rx.theme(
        appearance="inherit",
        accent_color="cyan",
        gray_color="slate",
        radius="large",
        scaling="105%",
        panel_background="translucent",
    ),
    api_transformer=[_api_healthz],
)

# Register pages — each data page runs AuthState.check first, then its own loader.
# Reflex 0.9.6 supports a list of event handlers for on_load.
app.add_page(home_page, route="/", title="Firnline — Dashboard", on_load=[AuthState.check, HealthState.refresh])
app.add_page(capture_page, route="/capture", title="Firnline — Capture", on_load=[AuthState.check, CaptureState.load])
app.add_page(inbox_page, route="/inbox", title="Firnline — Inbox", on_load=[AuthState.check, InboxState.load])
app.add_page(browse_page, route="/browse", title="Firnline — Browse", on_load=[AuthState.check, BrowseState.load])
app.add_page(
    browse_class_page,
    route="/browse/[class_name]",
    title="Firnline — Browse",
    on_load=[AuthState.check, BrowseClassState.load],
)
app.add_page(health_page, route="/health", title="Firnline — Health", on_load=[AuthState.check, HealthState.refresh])
app.add_page(modules_page, route="/modules", title="Firnline — Modules", on_load=[AuthState.check, ModulesState.load])
app.add_page(chat_page, route="/chat", title="Firnline — Chat", on_load=[AuthState.check, ChatState.init_from_query])
app.add_page(calendar_page, route="/calendar", title="Firnline — Calendar", on_load=[AuthState.check, CalendarState.load])
app.add_page(login_page, route="/login", title="Firnline — Sign in", on_load=AuthState.check_login)
