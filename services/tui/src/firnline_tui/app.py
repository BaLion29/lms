"""FirnlineApp — the main Textual application."""
from __future__ import annotations

import logging
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

from firnline_tui.screen_registry import ScreenRegistry
from firnline_tui.state.context import AppContext, default_context

log = logging.getLogger(__name__)


class FirnlineApp(App):
    """The firnline terminal application."""

    CSS_PATH = "ui/theme.tcss"
    TITLE = "firnline"

    # Base bindings — screen hotkeys are added dynamically in on_mount
    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Toggle sidebar", show=False),
        Binding("ctrl+p", "command_palette", "Command palette", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        registry: ScreenRegistry,
        ctx: AppContext | None = None,
    ) -> None:
        super().__init__()
        self.registry = registry
        self.ctx = ctx or default_context()
        self._sidebar_visible = True

    def on_mount(self) -> None:
        """Install all screens, register hotkeys, and push the start screen."""
        from firnline_tui.settings import get_settings

        start = get_settings().start_screen

        # Install all screens
        for spec in self.registry.specs:
            try:
                self.install_screen(spec.screen_factory, name=spec.screen_id)
            except Exception as exc:
                log.warning("screen_install_failed screen_id=%s error=%s", spec.screen_id, exc)

        # Register dynamic hotkeys for screens that have a key binding
        for spec in self.registry.specs:
            if spec.key and spec.nav_section is not None:
                self._bindings.bind(
                    spec.key,
                    f"switch_screen('{spec.screen_id}')",
                    description=spec.title,
                    show=False,
                    priority=True,
                )

        # Push start screen
        if self.registry.by_id(start) is None:
            start = "dashboard"
        self.push_screen(start)

    def action_switch_screen(self, screen_id: str) -> None:
        """Switch to a screen by ID, replacing the current screen stack."""
        if self.screen.name == screen_id:
            return  # Already on this screen
        try:
            self.pop_screen()
        except Exception:
            pass  # No screen to pop
        self.push_screen(screen_id)

    def action_toggle_sidebar(self) -> None:
        """Toggle the navigation sidebar visibility."""
        self._sidebar_visible = not self._sidebar_visible
        try:
            sidebar = self.query_one("NavSidebar")
            sidebar.display = self._sidebar_visible
        except Exception:
            pass  # No sidebar on screen yet
