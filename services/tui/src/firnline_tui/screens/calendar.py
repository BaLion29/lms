"""Calendar screen — event list view."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Label, Static
from textual import work

from firnline_tui.ui.feedback import ErrorBanner, EmptyState, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.typography import page_heading


class CalendarScreen(ShellScreen):
    SCREEN_ID = "calendar"
    TITLE = "Calendar"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Calendar")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Static("All Events", id="period-label", classes="section-heading")
        yield VerticalScroll(id="event-list")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.calendar import load_calendar

            data = await load_calendar(self.app.ctx)

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)

            event_list = self.query_one("#event-list", VerticalScroll)
            await event_list.remove_children()

            if data.events:
                # Sort events by start date
                events = sorted(data.events, key=lambda e: e.get("start", ""))
                for ev in events:
                    title = ev.get("title", "Untitled")
                    start = ev.get("start", "")
                    end = ev.get("end", "")
                    cls = ev.get("class", "")
                    color = ev.get("color", "")
                    date_str = f"{start}"
                    if end and end != start:
                        date_str += f" \u2192 {end}"
                    label_text = f"[{color or 'white'}] {date_str}  {title}  ({cls})"
                    event_list.mount(Label(label_text, classes="chip"))
            else:
                event_list.mount(
                    Label("No events found.", classes="empty-state-msg")
                )

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def action_refresh(self) -> None:
        self.load()
