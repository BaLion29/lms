"""Health screen — detailed service health status."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Label
from textual import work

from firnline_tui.ui.cards import InfoRow, StatusCard, status_dot
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.typography import page_heading, section_heading


class HealthScreen(ShellScreen):
    SCREEN_ID = "health"
    TITLE = "Health"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Health")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Vertical(id="service-details")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.health import load_health

            data = await load_health(self.app.ctx)

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)

            container = self.query_one("#service-details", Vertical)
            await container.remove_children()

            # Captured
            cap = data.captured
            container.mount(section_heading("Captured Service"))
            container.mount(
                StatusCard(
                    title="captured",
                    status=cap.status,
                    version=cap.version,
                    error="",
                )
            )
            container.mount(InfoRow("TerminusDB", cap.terminusdb))
            if cap.handlers:
                container.mount(InfoRow("Handlers", ", ".join(cap.handlers)))
            if cap.blob_root_writable_available:
                container.mount(
                    InfoRow(
                        "Blob Root Writable",
                        f"{status_dot('ok' if cap.blob_root_writable else 'err')} "
                        f"{'Yes' if cap.blob_root_writable else 'No'}",
                    )
                )

            # Queryd
            qry = data.queryd
            container.mount(section_heading("Queryd Service"))
            container.mount(
                StatusCard(
                    title="queryd",
                    status=qry.status,
                    version=qry.version,
                    error="",
                )
            )
            container.mount(InfoRow("TerminusDB", qry.terminusdb))
            if qry.plugins:
                container.mount(InfoRow("Plugins", ", ".join(qry.plugins)))

            # Indexed
            idx = data.indexed
            container.mount(section_heading("Indexed Service"))
            container.mount(
                StatusCard(
                    title="indexed",
                    status=idx.status,
                    version=idx.version,
                    error="",
                )
            )
            container.mount(InfoRow("TerminusDB", idx.terminusdb))
            container.mount(InfoRow("Store", idx.store))
            container.mount(InfoRow("Poller", idx.poller))

            # MCPd
            container.mount(section_heading("MCPd Service"))
            container.mount(
                StatusCard(
                    title="mcpd",
                    status=data.mcpd_status,
                    version="",
                    error="",
                )
            )

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def action_refresh(self) -> None:
        self.load()
