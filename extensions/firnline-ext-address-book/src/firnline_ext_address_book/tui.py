"""TUI screen plugin for the address-book extension.

Registered via the ``firnline.tui.screens`` entry point.  Provides a
read-only browser screen with tabs for People, Organizations, and Locations.

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


class AddressBookTuiPlugin:
    """TUI screen plugin providing the Address Book browser.

    Conforms to :class:`~firnline_core.plugins.TuiScreenPlugin`.
    """

    name: str = "address_book_tui"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="address_book", range=">=0.1.0 <0.2.0"),
    ]

    def screens(self) -> list[ScreenSpec]:
        def _factory():
            from firnline_ext_address_book._tui_screen import AddressBookScreen

            return AddressBookScreen()

        return [
            ScreenSpec(
                screen_id="address-book",
                title="Address Book",
                screen_factory=_factory,
                nav_section="EXTENSIONS",
                nav_icon="👥",
                nav_order=10,
                key="p",
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level singleton for entry-point discovery
# ---------------------------------------------------------------------------

plugin = AddressBookTuiPlugin()
