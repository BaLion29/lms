"""ShellScreen — base class for all TUI screens with sidebar + content layout."""
from __future__ import annotations


from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from firnline_tui.ui.nav import NavSidebar
from firnline_tui.ui.typography import page_heading


class ShellScreen(Screen):
    """Base screen with sidebar + header + content area.

    Subclasses implement ``compose_content()`` and a ``load`` worker.
    """

    SCREEN_ID: str = ""
    TITLE: str = ""
    BINDINGS: list = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield NavSidebar(self.app.registry, self.SCREEN_ID)
            with Vertical(id="content"):
                yield from self.compose_content()
        yield Footer()

    def compose_content(self) -> ComposeResult:
        """Override to provide screen-specific content."""
        yield page_heading(self.TITLE)
