"""Dashboard screen — service health cards + recent captures list."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Label
from textual import work

from firnline_tui.ui.cards import StatusCard
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.typography import page_heading, section_heading


class DashboardScreen(ShellScreen):
    SCREEN_ID = "dashboard"
    TITLE = "Dashboard"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Dashboard")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Horizontal(id="service-cards")
        yield section_heading("Recent Captures")
        yield Vertical(id="recent-captures", classes="scroll-container")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.dashboard import load_dashboard

            data = await load_dashboard(self.app.ctx)

            # Service health cards
            cards = self.query_one("#service-cards", Horizontal)
            await cards.remove_children()
            for svc in data.services:
                cards.mount(StatusCard(
                    title=svc.name,
                    status=svc.status,
                    version=svc.version,
                    error=svc.error,
                ))

            # Recent captures
            recent_container = self.query_one("#recent-captures", Vertical)
            await recent_container.remove_children()
            if data.recent_captures:
                for cap in data.recent_captures[:10]:
                    status = cap.get("status", "")
                    preview = cap.get("preview", "")
                    doc_id = cap.get("id", "")
                    label = Label(f"[{status}] {preview[:120]}", classes="chip")
                    recent_container.mount(label)
            else:
                recent_container.mount(Label("No recent captures.", classes="chip"))

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)
        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def action_refresh(self) -> None:
        self.load()
