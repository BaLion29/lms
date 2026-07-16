"""TUI screen plugin for the time-management extension.

Registered via the ``firnline.tui.screens`` entry point.  Provides a
read-only overview screen with tabs for Tasks, Projects, and Goals.

All ``firnline_tui`` imports are confined to lazy factory functions,
which are only loaded inside the TUI process.  The extension's
``[project] dependencies`` do NOT include firnline_tui.
"""

from __future__ import annotations

from firnline_core.plugins import ModuleRequirement
from firnline_core.screenspec import ScreenSpec


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class TimeManagementTuiPlugin:
    """TUI screen plugin providing the Time Management overview.

    Conforms to :class:`~firnline_core.plugins.TuiScreenPlugin`.
    """

    name: str = "time_management_tui"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.1.0 <0.2.0"),
    ]

    def screens(self) -> list[ScreenSpec]:
        def _factory():
            from firnline_ext_time_management._tui_screen import TimeManagementScreen

            return TimeManagementScreen()

        return [
            ScreenSpec(
                screen_id="time",
                title="Time Mgmt",
                screen_factory=_factory,
                nav_section="EXTENSIONS",
                nav_icon="◷",
                nav_order=0,
                key="t",
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level singleton for entry-point discovery
# ---------------------------------------------------------------------------

plugin = TimeManagementTuiPlugin()
