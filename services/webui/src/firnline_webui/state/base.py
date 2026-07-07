"""Base state with shared env info."""

from __future__ import annotations

import reflex as rx

from firnline_webui.settings import get_settings

_settings = get_settings()


class BaseState(rx.State):
    """State shared by all pages — provides org/db/branch for the header badge."""

    org: str = _settings.tdb_org
    db: str = _settings.tdb_db
    branch: str = _settings.tdb_branch
