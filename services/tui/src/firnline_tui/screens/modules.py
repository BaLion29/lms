"""Modules screen — schema module registry + per-service plugin lists."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Label
from textual import work

from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable
from firnline_tui.ui.typography import page_heading, section_heading


class ModulesScreen(ShellScreen):
    SCREEN_ID = "modules"
    TITLE = "Modules"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Modules")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield section_heading("Schema Modules")
        yield DocTable(id="modules-table")
        yield section_heading("Captured Plugins")
        yield VerticalScroll(id="captured-plugins")
        yield section_heading("Queryd Plugins")
        yield VerticalScroll(id="queryd-plugins")
        yield section_heading("Indexed Plugins")
        yield VerticalScroll(id="indexed-plugins")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.modules import load_modules

            data = await load_modules(self.app.ctx)

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)

            # Modules table
            table = self.query_one("#modules-table", DocTable)
            table.set_columns(["Name", "Version", "Description", "Exports", "Depends On"])
            table.populate(
                [
                    {
                        "id": m.name,
                        "Name": m.name,
                        "Version": m.version,
                        "Description": m.description,
                        "Exports": m.exports_str,
                        "Depends On": m.depends_on_str,
                    }
                    for m in data.modules
                ]
            )

            # Captured plugins
            cap_container = self.query_one("#captured-plugins", VerticalScroll)
            await cap_container.remove_children()
            for p in data.captured_plugins:
                cap_container.mount(Label(p, classes="chip"))

            # Queryd plugins
            qry_container = self.query_one("#queryd-plugins", VerticalScroll)
            await qry_container.remove_children()
            for p in data.queryd_plugins:
                qry_container.mount(Label(p, classes="chip"))

            # Indexed plugins
            idx_container = self.query_one("#indexed-plugins", VerticalScroll)
            await idx_container.remove_children()
            for p in data.indexed_plugins:
                idx_container.mount(Label(p, classes="chip"))

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def action_refresh(self) -> None:
        self.load()
