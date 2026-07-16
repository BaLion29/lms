"""FirnlineApp — the main Textual application."""
from __future__ import annotations

import logging

from textual.app import App
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider

from firnline_tui.screen_registry import ScreenRegistry
from firnline_tui.state.context import AppContext, default_context

log = logging.getLogger(__name__)


class FirnlineCaptureProvider(Provider):
    """Command palette provider for Quick Capture."""

    async def discover(self) -> Hits:
        """Show Quick Capture in the default command list."""
        yield DiscoveryHit(
            "Quick Capture",
            self._trigger_capture,
            text="Quick Capture",
            help="Capture a quick note",
        )

    async def search(self, query: str) -> Hits:
        """Match Quick Capture when user searches."""
        matcher = self.matcher(query)
        score = matcher.match("Quick Capture")
        if score > 0:
            yield Hit(
                score,
                matcher.highlight("Quick Capture"),
                self._trigger_capture,
                text="Quick Capture",
                help="Capture a quick note",
            )

    def _trigger_capture(self) -> None:
        """Push the CaptureModal onto the screen stack."""
        from firnline_tui.screens.capture import CaptureModal

        self.app.push_screen(CaptureModal())


class FirnlineApp(App):
    """The firnline terminal application."""

    CSS_PATH = "ui/theme.tcss"
    TITLE = "firnline"

    COMMANDS = App.COMMANDS | {FirnlineCaptureProvider}

    # Base bindings — screen hotkeys are added dynamically in on_mount
    BINDINGS = [
        Binding("f1", "help", "Help", show=True),
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

        # Register dynamic hotkeys for screens that have a key binding.
        # Non-priority bindings let focused Input widgets consume keys first.
        for spec in self.registry.specs:
            if spec.key and spec.nav_section is not None:
                self._bindings.bind(
                    spec.key,
                    f"switch_screen('{spec.screen_id}')",
                    description=spec.title,
                    show=False,
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
