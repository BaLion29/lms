import os

import reflex as rx

config = rx.Config(
    app_name="firnline_webui",
    # api_url must be an absolute URL — Reflex's prerenderer parses it with new URL().
    # Set REFLEX_API_URL to the browser-facing URL in your deployment (e.g. http://server:3000).
    # In dev, reflex listens on port 8000.
    api_url=os.environ.get("REFLEX_API_URL") or "http://localhost:8000",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="inherit",
                accent_color="teal",
                gray_color="slate",
                radius="medium",
                scaling="100%",
                panel_background="solid",
            ),
        ),
    ],
)
