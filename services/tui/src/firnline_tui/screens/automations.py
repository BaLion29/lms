"""Automations screen — trigger firings + action executions tables."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Label
from textual import work

from firnline_tui.ui.detail import JsonDetailPanel
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable
from firnline_tui.ui.typography import page_heading, section_heading


class AutomationsScreen(ShellScreen):
    SCREEN_ID = "automations"
    TITLE = "Automations"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "clear_detail", "Clear"),
    ]

    def compose_content(self) -> ComposeResult:
        yield page_heading("Automations")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield section_heading("Trigger Firings")
        with Horizontal():
            yield DocTable(id="firing-table")
            yield JsonDetailPanel(id="detail-panel")
        yield section_heading("Action Executions")
        yield DocTable(id="execution-table")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.automations import load_automations

            data = await load_automations(self.app.ctx)

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)

            # Trigger firings table
            firing_table = self.query_one("#firing-table", DocTable)
            firing_cols = [
                "Trigger", "Status", "Scheduled", "Fired", "Subject",
            ]
            firing_table.set_columns(firing_cols)
            firing_table.populate(
                [
                    {
                        "id": r.get("id", ""),
                        "Trigger": r.get("trigger_name", ""),
                        "Status": r.get("status", ""),
                        "Scheduled": r.get("scheduled_for", ""),
                        "Fired": r.get("fired_at", ""),
                        "Subject": r.get("subject", ""),
                    }
                    for r in data.firing_rows
                ]
            )

            # Action executions table
            exec_table = self.query_one("#execution-table", DocTable)
            exec_cols = [
                "Action", "Status", "Attempt", "Executed", "Next", "Approved By",
            ]
            exec_table.set_columns(exec_cols)
            exec_table.populate(
                [
                    {
                        "id": r.get("id", ""),
                        "Action": r.get("action_name", ""),
                        "Status": r.get("status", ""),
                        "Attempt": str(r.get("attempt", "")),
                        "Executed": r.get("executed_at", ""),
                        "Next": r.get("next_attempt_at", ""),
                        "Approved By": r.get("approved_by", ""),
                    }
                    for r in data.execution_rows
                ]
            )

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def on_data_table_row_selected(self, event: DocTable.RowSelected) -> None:
        iri = str(event.row_key.value) if event.row_key.value else ""
        if iri and event.control.id in ("firing-table", "execution-table"):
            self._select_document(iri)

    @work
    async def _select_document(self, iri: str) -> None:
        from firnline_tui.state.selection import SelectionController

        sel = SelectionController(self.app.ctx)
        try:
            json_str = await sel.select(iri)
            self.query_one("#detail-panel", JsonDetailPanel).show_document(iri, json_str)
        except Exception as exc:
            self.query_one("#detail-panel", JsonDetailPanel).show_error(str(exc))

    def action_clear_detail(self) -> None:
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_refresh(self) -> None:
        self.load()
