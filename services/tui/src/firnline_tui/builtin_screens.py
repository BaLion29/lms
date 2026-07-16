"""Builtin TUI screen plugin — provides all standard screens."""
from __future__ import annotations

from firnline_core.plugins import ModuleRequirement
from firnline_core.screenspec import ScreenSpec


class BuiltinScreens:
    """Canonical builtin screen provider conforming to TuiScreenPlugin."""

    name: str = "builtin"
    requires: list[ModuleRequirement] = []

    def screens(self) -> list[ScreenSpec]:
        # Lazy imports — screen classes are defined in Phase 2d
        def _dashboard():
            from firnline_tui.screens.dashboard import DashboardScreen

            return DashboardScreen()

        def _capture():
            from firnline_tui.screens.capture import CaptureScreen

            return CaptureScreen()

        def _inbox():
            from firnline_tui.screens.inbox import InboxScreen

            return InboxScreen()

        def _browse():
            from firnline_tui.screens.browse import BrowseScreen

            return BrowseScreen()

        def _browse_class():
            from firnline_tui.screens.browse import BrowseClassScreen

            return BrowseClassScreen()

        def _calendar():
            from firnline_tui.screens.calendar import CalendarScreen

            return CalendarScreen()

        def _automations():
            from firnline_tui.screens.automations import AutomationsScreen

            return AutomationsScreen()

        def _health():
            from firnline_tui.screens.health import HealthScreen

            return HealthScreen()

        def _modules():
            from firnline_tui.screens.modules import ModulesScreen

            return ModulesScreen()

        def _history():
            from firnline_tui.screens.history import HistoryScreen

            return HistoryScreen()

        return [
            ScreenSpec(
                screen_id="dashboard",
                title="Dashboard",
                screen_factory=_dashboard,
                nav_section="MAIN",
                nav_icon="◉",
                nav_order=0,
                key="d",
            ),
            ScreenSpec(
                screen_id="capture",
                title="Capture",
                screen_factory=_capture,
                nav_section="MAIN",
                nav_icon="✎",
                nav_order=10,
                key="c",
            ),
            ScreenSpec(
                screen_id="inbox",
                title="Inbox",
                screen_factory=_inbox,
                nav_section="MAIN",
                nav_icon="▤",
                nav_order=20,
                key="i",
            ),
            ScreenSpec(
                screen_id="browse",
                title="Browse",
                screen_factory=_browse,
                nav_section="MAIN",
                nav_icon="▣",
                nav_order=30,
                key="b",
            ),
            ScreenSpec(
                screen_id="browse-class",
                title="Browse Class",
                screen_factory=_browse_class,
                nav_section=None,
                nav_icon=None,
                nav_order=100,
            ),
            ScreenSpec(
                screen_id="calendar",
                title="Calendar",
                screen_factory=_calendar,
                nav_section="MAIN",
                nav_icon="▦",
                nav_order=40,
                key="a",
            ),
            ScreenSpec(
                screen_id="automations",
                title="Automations",
                screen_factory=_automations,
                nav_section="MAIN",
                nav_icon="⚡",
                nav_order=50,
                key="m",
            ),
            ScreenSpec(
                screen_id="health",
                title="Health",
                screen_factory=_health,
                nav_section="MAIN",
                nav_icon="♥",
                nav_order=60,
                key="h",
            ),
            ScreenSpec(
                screen_id="modules",
                title="Modules",
                screen_factory=_modules,
                nav_section="MAIN",
                nav_icon="▦",
                nav_order=70,
            ),
            ScreenSpec(
                screen_id="history",
                title="History",
                screen_factory=_history,
                nav_section="MAIN",
                nav_icon="⏱",
                nav_order=80,
            ),
        ]
