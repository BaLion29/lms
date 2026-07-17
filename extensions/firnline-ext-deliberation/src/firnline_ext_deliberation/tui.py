"""TUI screen plugin for the deliberation extension.

Registered via the ``firnline.tui.screens`` entry point.  Provides a
read-only browser screen with tabs for Decisions, Problems, and Questions.

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


class DeliberationTuiPlugin:
    """TUI screen plugin providing the Deliberation browser.

    Conforms to :class:`~firnline_core.plugins.TuiScreenPlugin`.
    """

    name: str = "deliberation_tui"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="deliberation", range=">=0.1.0 <0.2.0"),
    ]

    def screens(self) -> list[ScreenSpec]:
        def _factory():
            from firnline_ext_deliberation._tui_screen import DeliberationScreen

            return DeliberationScreen()

        return [
            ScreenSpec(
                screen_id="deliberation",
                title="Deliberation",
                screen_factory=_factory,
                nav_section="EXTENSIONS",
                nav_icon="⚖",
                nav_order=20,
                key="e",
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level singleton for entry-point discovery
# ---------------------------------------------------------------------------

plugin = DeliberationTuiPlugin()
