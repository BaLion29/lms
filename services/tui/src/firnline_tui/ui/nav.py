"""NavSidebar — dynamic navigation built from ScreenRegistry."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from firnline_core.screenspec import ScreenSpec
from firnline_tui.screen_registry import ScreenRegistry


class NavItem(Static):
    """A single navigation item — clickable to switch screens."""

    def __init__(self, spec: ScreenSpec, active: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.spec = spec
        self.active = active
        icon = spec.nav_icon or ""
        key_hint = f" [{spec.key}]" if spec.key else ""
        self.update(f"{icon} {spec.title}{key_hint}")
        if active:
            self.add_class("nav-item--active")
        else:
            self.add_class("nav-item")

    async def on_click(self, event) -> None:
        """Switch to this screen on click."""
        self.app.action_switch_screen(self.spec.screen_id)


class NavSectionLabel(Static):
    """Section heading in the sidebar."""

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.add_class("nav-section-label")


class NavSidebar(Vertical):
    """Navigation sidebar — built from the screen registry."""

    def __init__(self, registry: ScreenRegistry, active_id: str = "") -> None:
        super().__init__()
        self.registry = registry
        self.active_id = active_id

    def compose(self) -> ComposeResult:
        # Wordmark
        yield Static("▲ firnline", id="nav-wordmark")
        for section_name, specs in self.registry.nav_sections():
            yield NavSectionLabel(section_name)
            for spec in specs:
                yield NavItem(spec, active=(spec.screen_id == self.active_id))
