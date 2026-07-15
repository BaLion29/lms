"""Reflex app entry point for firnline-webui.

This file must be importable as ``firnline_webui.firnline_webui`` at the root
of the Reflex project (``services/webui/``). Because the package lives under
``src/firnline_webui/`` (hatchling src layout), ``uv run`` installs the
package in dev mode, making the import work automatically.

Pages are registered dynamically from the plugin registry
(``firnline_webui.plugin_host``) so that external ``WebUIPagePlugin``
implementations can contribute additional pages at compile time.
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version

import reflex as rx

from firnline_webui.plugin_host import get_page_specs

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
    stylesheets=["/fonts.css"],
    api_transformer=[_api_healthz],
)

# Register pages from the plugin registry.
# Each PageSpec carries route, title, component, on_load, and nav metadata.
for spec in get_page_specs():
    # Reflex 0.9.x supports on_load as list[EventHandler] or single EventHandler.
    app.add_page(
        spec.component,
        route=spec.route,
        title=spec.title,
        on_load=spec.on_load if spec.on_load is not None else None,
    )
