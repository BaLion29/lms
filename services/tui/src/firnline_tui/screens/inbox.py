"""Inbox screen — captured documents with status filter and detail panel."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static
from textual import work

from firnline_tui.state.selection import SelectionController
from firnline_tui.ui.detail import JsonDetailPanel
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable
from firnline_tui.ui.typography import page_heading


class InboxScreen(ShellScreen):
    SCREEN_ID = "inbox"
    TITLE = "Inbox"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "filter_all", "All"),
        Binding("2", "filter_pending", "Pending"),
        Binding("3", "filter_captured", "Captured"),
        Binding("4", "filter_failed", "Failed"),
        Binding("escape", "clear_detail", "Clear"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_filter: str = "all"
        self._data: list[dict] = []
        self._selection: SelectionController | None = None

    def on_mount(self) -> None:
        self._selection = SelectionController(self.app.ctx)
        self.load()

    def compose_content(self) -> ComposeResult:
        yield page_heading("Inbox")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Static(
            "Filter: [1]all  [2]pending  [3]captured  [4]failed",
            classes="chip",
            id="filter-hint",
        )
        with Horizontal():
            yield DocTable(id="inbox-table")
            yield JsonDetailPanel(id="detail-panel")

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.inbox import load_inbox, filter_rows

            data = await load_inbox(self.app.ctx)
            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)
                self.query_one("#loading", LoadingIndicator).display = False
                return

            all_rows = list(data.rows)
            self._data = all_rows
            self._apply_filter(filter_rows, data)
        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def _apply_filter(self, filter_fn, data) -> None:
        from firnline_tui.state.inbox import InboxData

        filtered = filter_fn(data, self._current_filter)
        table = self.query_one("#inbox-table", DocTable)
        table.set_columns(["Status", "Captured At", "Content Type", "Preview"])
        table.populate(
            [
                {
                    "id": r.get("id", ""),
                    "Status": r.get("status", ""),
                    "Captured At": r.get("captured_at", ""),
                    "Content Type": r.get("content_type", ""),
                    "Preview": (r.get("preview", "") or "")[:80],
                }
                for r in filtered
            ]
        )

    def on_data_table_row_selected(self, event: DocTable.RowSelected) -> None:
        iri = str(event.row_key.value) if event.row_key.value else ""
        if iri:
            self._select_document(iri)

    @work
    async def _select_document(self, iri: str) -> None:
        try:
            json_str = await self._selection.select(iri)
            self.query_one("#detail-panel", JsonDetailPanel).show_document(iri, json_str)
        except Exception as exc:
            self.query_one("#detail-panel", JsonDetailPanel).show_error(str(exc))

    def action_filter_all(self) -> None:
        self._current_filter = "all"
        self._refresh_table()

    def action_filter_pending(self) -> None:
        self._current_filter = "pending"
        self._refresh_table()

    def action_filter_captured(self) -> None:
        self._current_filter = "captured"
        self._refresh_table()

    def action_filter_failed(self) -> None:
        self._current_filter = "failed"
        self._refresh_table()

    def action_clear_detail(self) -> None:
        self._selection.clear()
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def _refresh_table(self) -> None:
        from firnline_tui.state.inbox import InboxData, filter_rows

        data = InboxData(rows=tuple(self._data))
        self._apply_filter(filter_rows, data)

    def action_refresh(self) -> None:
        self.load()
