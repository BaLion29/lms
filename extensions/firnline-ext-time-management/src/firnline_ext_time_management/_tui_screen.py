"""Time Management TUI screen — Tasks, Projects, Goals with tabs and detail panel."""

from __future__ import annotations

import asyncio
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, Static, TabbedContent, TabPane

from firnline_tui.ui.detail import JsonDetailPanel
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable
from firnline_tui.ui.typography import page_heading


_STATUS_DOTS: dict[str, str] = {
    "open": "🔵",
    "planned": "🟡",
    "active": "🔵",
    "on_hold": "🟡",
    "done": "🟢",
    "completed": "🟢",
    "achieved": "🟢",
    "abandoned": "⚫",
}


def _status_dot(status: str) -> str:
    return _STATUS_DOTS.get(str(status).lower(), "⚪")


def _fmt_date(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw)
    if "^^" in s:
        s = s.split("^^")[0]
    return s[:10] if s else ""


def _normalize_task(doc: dict) -> dict:
    priority = doc.get("priority") or 0
    try:
        priority = int(priority)
    except (ValueError, TypeError):
        priority = 0
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Status": f"{_status_dot(doc.get('status', ''))} {doc.get('status', '')}",
        "Due Date": _fmt_date(doc.get("due_date")),
        "Priority": f"P{priority}" if priority else "-",
    }


def _normalize_project(doc: dict) -> dict:
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Status": f"{_status_dot(doc.get('status', ''))} {doc.get('status', '')}",
        "Target Date": _fmt_date(doc.get("target_date")),
    }


def _normalize_goal(doc: dict) -> dict:
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Status": f"{_status_dot(doc.get('status', ''))} {doc.get('status', '')}",
        "Target Date": _fmt_date(doc.get("target_date")),
    }


class TimeManagementScreen(ShellScreen):
    """Time Management screen — Tasks, Projects, Goals with tabs and detail."""

    SCREEN_ID = "time"
    TITLE = "Time Management"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_tasks", "Tasks"),
        Binding("2", "tab_projects", "Projects"),
        Binding("3", "tab_goals", "Goals"),
        Binding("escape", "clear_detail", "Clear"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tasks: list[dict] = []
        self._projects: list[dict] = []
        self._goals: list[dict] = []
        self._selection = None

    def on_mount(self) -> None:
        from firnline_tui.state.selection import SelectionController

        self._selection = SelectionController(self.app.ctx)
        self.load()

    def compose_content(self) -> ComposeResult:
        yield page_heading("Time Management")
        yield Static(
            "Tabs: [1] Tasks  [2] Projects  [3] Goals  |  [r] Refresh  |  [Enter] Select  |  [Esc] Clear",
            classes="chip",
        )
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        with Horizontal():
            with Vertical(id="tm-main"):
                with TabbedContent(id="tm-tabs"):
                    with TabPane("Tasks", id="tab-tasks"):
                        yield DocTable(id="tasks-table")
                    with TabPane("Projects", id="tab-projects"):
                        yield DocTable(id="projects-table")
                    with TabPane("Goals", id="tab-goals"):
                        yield DocTable(id="goals-table")
            yield JsonDetailPanel(id="detail-panel")

    @work
    async def load(self) -> None:
        """Fetch Tasks, Projects, and Goals from TerminusDB."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            tdb = self.app.ctx.make_tdb()
            try:
                tasks_raw = await tdb.get_documents("Task")
                projects_raw = await tdb.get_documents("Project")
                goals_raw = await tdb.get_documents("Goal")
            finally:
                await tdb.aclose()

            self._tasks = [_normalize_task(d) for d in tasks_raw]
            self._projects = [_normalize_project(d) for d in projects_raw]
            self._goals = [_normalize_goal(d) for d in goals_raw]

            self._populate_table("tasks-table", ["Name", "Status", "Due Date", "Priority"], self._tasks)
            self._populate_table("projects-table", ["Name", "Status", "Target Date"], self._projects)
            self._populate_table("goals-table", ["Name", "Status", "Target Date"], self._goals)

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def _populate_table(self, table_id: str, columns: list[str], rows: list[dict]) -> None:
        """Populate a DocTable with rows."""
        table = self.query_one(f"#{table_id}", DocTable)
        table.set_columns(columns)
        table.populate(rows, key_field="id")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection — load document detail."""
        iri = str(event.row_key.value) if event.row_key.value else ""
        if iri:
            self._select_document(iri)

    @work
    async def _select_document(self, iri: str) -> None:
        """Load document JSON into the detail panel."""
        try:
            json_str = await self._selection.select(iri)
            self.query_one("#detail-panel", JsonDetailPanel).show_document(iri, json_str)
        except Exception as exc:
            self.query_one("#detail-panel", JsonDetailPanel).show_error(str(exc))

    def action_tab_tasks(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-tasks"

    def action_tab_projects(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-projects"

    def action_tab_goals(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-goals"

    def action_clear_detail(self) -> None:
        self._selection.clear()
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_refresh(self) -> None:
        self.load()
