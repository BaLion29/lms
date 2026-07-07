import os

import reflex as rx

config = rx.Config(
    app_name="firnline_webui",
    # Default api_url for dev (localhost:8000); overridable by REFLEX_API_URL env var.
    # In Docker, REFLEX_API_URL is set to "" so the frontend makes same-origin API calls.
    api_url=os.environ.get("REFLEX_API_URL", "http://localhost:8000"),
)
