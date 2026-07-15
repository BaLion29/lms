"""Builtin WebUI page plugin — provides all standard pages.

This module is always loaded (needs no ModuleRequirements). It exposes the
same pages and on_load handlers as the previously hardcoded ``app.add_page``
calls in ``firnline_webui.py``.
"""

from __future__ import annotations

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import ModuleRequirement


class BuiltinPages:
    """Canonical builtin page provider conforming to :class:`WebUIPagePlugin`.

    Returns exactly the same pages, routes, titles, and on_load handlers
    as the original ``firnline_webui.py``.  Navigation metadata mirrors
    the current sidebar structure in ``ui/nav.py``.
    """

    name: str = "builtin"
    requires: list[ModuleRequirement] = []

    def pages(self) -> list[PageSpec]:
        # Import lazily so the plugin remains lightweight until pages()
        # is actually called (avoids circular imports during discovery).
        from firnline_webui.pages.automations import automations_page  # noqa: PLC0415
        from firnline_webui.pages.browse import browse_class_page, browse_page  # noqa: PLC0415
        from firnline_webui.pages.calendar import calendar_page  # noqa: PLC0415
        from firnline_webui.pages.capture import capture_page  # noqa: PLC0415
        from firnline_webui.pages.health import health_page  # noqa: PLC0415
        from firnline_webui.pages.history import history_page  # noqa: PLC0415
        from firnline_webui.pages.home import home_page  # noqa: PLC0415
        from firnline_webui.pages.inbox import inbox_page  # noqa: PLC0415
        from firnline_webui.pages.login import login_page  # noqa: PLC0415
        from firnline_webui.pages.modules import modules_page  # noqa: PLC0415
        from firnline_webui.state.auth import AuthState  # noqa: PLC0415
        from firnline_webui.state.automations import AutomationsState  # noqa: PLC0415
        from firnline_webui.state.browse import (  # noqa: PLC0415
            BrowseClassState,
            BrowseState,
        )
        from firnline_webui.state.calendar import CalendarState  # noqa: PLC0415
        from firnline_webui.state.capture import CaptureState  # noqa: PLC0415
        from firnline_webui.state.health import HealthState  # noqa: PLC0415
        from firnline_webui.state.history import HistoryState  # noqa: PLC0415
        from firnline_webui.state.inbox import InboxState  # noqa: PLC0415
        from firnline_webui.state.modules import ModulesState  # noqa: PLC0415

        return [
            PageSpec(
                route="/",
                title="Firnline — Dashboard",
                component=home_page,
                nav_section="MAIN",
                nav_icon="house",
                nav_order=0,
                on_load=[AuthState.check, HealthState.refresh],
            ),
            PageSpec(
                route="/capture",
                title="Firnline — Capture",
                component=capture_page,
                nav_section="MAIN",
                nav_icon="pencil_line",
                nav_order=10,
                on_load=[AuthState.check, CaptureState.load],
            ),
            PageSpec(
                route="/inbox",
                title="Firnline — Inbox",
                component=inbox_page,
                nav_section="MAIN",
                nav_icon="inbox",
                nav_order=20,
                on_load=[AuthState.check, InboxState.load],
            ),
            PageSpec(
                route="/browse",
                title="Firnline — Browse",
                component=browse_page,
                nav_section="MAIN",
                nav_icon="database",
                nav_order=30,
                on_load=[AuthState.check, BrowseState.load],
            ),
            PageSpec(
                route="/browse/[class_name]",
                title="Firnline — Browse",
                component=browse_class_page,
                nav_section=None,
                nav_icon=None,
                nav_order=100,
                on_load=[AuthState.check, BrowseClassState.load],
            ),
            PageSpec(
                route="/calendar",
                title="Firnline — Calendar",
                component=calendar_page,
                nav_section="MAIN",
                nav_icon="calendar_days",
                nav_order=40,
                on_load=[AuthState.check, CalendarState.load],
            ),
            PageSpec(
                route="/automations",
                title="Firnline — Automations",
                component=automations_page,
                nav_section="MAIN",
                nav_icon="zap",
                nav_order=50,
                on_load=[AuthState.check, AutomationsState.load],
            ),
            PageSpec(
                route="/health",
                title="Firnline — Health",
                component=health_page,
                nav_section="MAIN",
                nav_icon="activity",
                nav_order=60,
                on_load=[AuthState.check, HealthState.refresh],
            ),
            PageSpec(
                route="/modules",
                title="Firnline — Modules",
                component=modules_page,
                nav_section="MAIN",
                nav_icon="blocks",
                nav_order=70,
                on_load=[AuthState.check, ModulesState.load],
            ),
            PageSpec(
                route="/history",
                title="Firnline — History",
                component=history_page,
                nav_section="MAIN",
                nav_icon="history",
                nav_order=80,
                on_load=[AuthState.check, HistoryState.load],
            ),
            PageSpec(
                route="/login",
                title="Firnline — Sign in",
                component=login_page,
                nav_section=None,
                nav_icon=None,
                nav_order=100,
                on_load=AuthState.check_login,
            ),
        ]
