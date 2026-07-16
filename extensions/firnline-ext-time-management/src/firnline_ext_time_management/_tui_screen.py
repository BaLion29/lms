"""Time Management TUI screen — Tasks, Projects, Goals, Routines, Activities, Calendar."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

from rich.table import Table as RichTable
from rich.text import Text as RichText
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static, TabbedContent, TabPane

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


def _normalize_routine(doc: dict) -> dict:
    steps = doc.get("steps") or []
    trigger = doc.get("trigger")
    contexts = doc.get("required_context") or []
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Steps": str(len(steps)),
        "Trigger": str(trigger) if trigger else "—",
        "Contexts": str(len(contexts)),
    }


def _irf_tail(iri: str) -> str:
    """Return the last segment of an IRI, e.g. 'Routine/morning' → 'morning'."""
    if not iri:
        return "—"
    return iri.rsplit("/", 1)[-1]


def _normalize_activity(doc: dict) -> dict:
    routine_iri = doc.get("routine")
    routine = _irf_tail(routine_iri) if routine_iri else "—"
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Start": _fmt_date(doc.get("start_datetime")),
        "End": _fmt_date(doc.get("end_datetime")),
        "Priority": f"P{doc.get('priority')}" if doc.get("priority") else "—",
        "Routine": routine,
    }


# ── Calendar helpers ──────────────────────────────────────────────────────────

_EVENT_PALETTE = [
    "cyan",
    "orange",
    "green",
    "purple",
    "pink",
    "blue",
    "amber",
    "teal",
]

_RICH_COLOR_MAP: dict[str, str] = {
    "cyan": "cyan",
    "orange": "dark_orange",
    "green": "green",
    "purple": "magenta",
    "pink": "pink1",
    "blue": "blue",
    "amber": "yellow",
    "teal": "turquoise2",
}


def _color_for_class(class_name: str) -> str:
    """Deterministic colour pick from the palette."""
    h = sum(ord(c) for c in class_name)
    return _EVENT_PALETTE[h % len(_EVENT_PALETTE)]


def _parse_date(iso_str: str) -> date | None:
    """Parse an ISO datetime string to a date. Returns None on failure."""
    if not iso_str:
        return None
    s = iso_str.strip()
    if "^^" in s:
        s = s.split("^^")[0]
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.date()
    except (ValueError, TypeError):
        return None


_WEEKDAY_ABBR = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _build_month_grid(
    year: int,
    month: int,
    events: list[dict],
) -> RichTable:
    """Build a Rich Table representing a month calendar grid.

    Each cell shows the day number and up to 4 event titles (abbreviated).
    Today's cell is highlighted. Days with events get a subtle background.
    """
    today = date.today()

    # Group events by day
    events_by_day: dict[int, list[dict]] = {}
    for ev in events:
        d = _parse_date(ev.get("start", ""))
        if d is not None and d.year == year and d.month == month:
            events_by_day.setdefault(d.day, []).append(ev)

    # Build table
    table = RichTable(
        expand=True,
        show_header=True,
        show_edge=False,
        padding=(0, 1),
        collapse_padding=True,
    )
    for abbr in _WEEKDAY_ABBR:
        table.add_column(abbr, justify="left", no_wrap=False, ratio=1)

    # Compute the calendar grid
    first_weekday, days_in_month = monthrange(year, month)
    # Adjust from Monday=0 (Python) to Monday=0 (our grid)
    # Python: Monday=0, Sunday=6

    weeks: list[list[tuple[int, list[dict]] | None]] = []
    current_week: list[tuple[int, list[dict]] | None] = [None] * first_weekday

    for day in range(1, days_in_month + 1):
        current_week.append((day, events_by_day.get(day, [])))
        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []

    # Pad last week
    if current_week:
        while len(current_week) < 7:
            current_week.append(None)
        weeks.append(current_week)

    for week in weeks:
        row_cells: list[RichText] = []
        for cell in week:
            if cell is None:
                row_cells.append(RichText(""))
                continue
            day_num, day_events = cell

            cell_text = RichText()
            # Day number
            day_style = ""
            if day_num == today.day and year == today.year and month == today.month:
                day_style = "bold reverse"
            cell_text.append(str(day_num), style=day_style)

            # Events
            for ev in day_events[:4]:  # limit to 4 events
                title = ev.get("title", "?")
                color = ev.get("color", "white")
                rich_color = _RICH_COLOR_MAP.get(color, "white")
                short_title = title[:16] + "…" if len(title) > 16 else title
                cell_text.append("\n")
                cell_text.append(f"▸{short_title}", style=rich_color)

            if len(day_events) > 4:
                cell_text.append("\n")
                cell_text.append(f"  +{len(day_events) - 4} more", style="dim")

            row_cells.append(cell_text)
        table.add_row(*row_cells)

    return table


# ═══════════════════════════════════════════════════════════════════════════════
# Screen
# ═══════════════════════════════════════════════════════════════════════════════


class TimeManagementScreen(ShellScreen):
    """Time Management screen — Tasks, Projects, Goals, Routines, Activities, Calendar."""

    SCREEN_ID = "time"
    TITLE = "Time Management"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_tasks", "Tasks"),
        Binding("2", "tab_projects", "Projects"),
        Binding("3", "tab_goals", "Goals"),
        Binding("4", "tab_routines", "Routines"),
        Binding("5", "tab_activities", "Activities"),
        Binding("6", "tab_calendar", "Calendar"),
        Binding("]", "cal_next_month", "Next Mth"),
        Binding("[", "cal_prev_month", "Prev Mth"),
        Binding("0", "cal_today", "Today"),
        Binding("escape", "clear_detail", "Clear"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tasks: list[dict] = []
        self._projects: list[dict] = []
        self._goals: list[dict] = []
        self._routines: list[dict] = []
        self._activities: list[dict] = []
        self._selection = None
        self._calendar_events: list[dict] = []
        today = date.today()
        self._calendar_year: int = today.year
        self._calendar_month: int = today.month

    def on_mount(self) -> None:
        from firnline_tui.state.selection import SelectionController

        self._selection = SelectionController(self.app.ctx)
        self.load()

    def compose_content(self) -> ComposeResult:
        yield page_heading("Time Management")
        yield Static(
            "Tabs: [1] Tasks  [2] Projects  [3] Goals  [4] Routines  [5] Activities  [6] Calendar  "
            "|  [r] Refresh  |  [Enter] Select  |  [Esc] Clear  "
            "|  [[]/[]] Month  [0] Today",
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
                    with TabPane("Routines", id="tab-routines"):
                        yield DocTable(id="routines-table")
                    with TabPane("Activities", id="tab-activities"):
                        yield DocTable(id="activities-table")
                    with TabPane("Calendar", id="tab-calendar"):
                        yield Static("", id="cal-header")
                        yield Static("", id="cal-grid")
            yield JsonDetailPanel(id="detail-panel")

    # ── Data loading ──────────────────────────────────────────────────────

    @work
    async def load(self) -> None:
        """Fetch all document types from TerminusDB."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            tdb = self.app.ctx.make_tdb()
            try:
                tasks_raw = await tdb.get_documents("Task")
                projects_raw = await tdb.get_documents("Project")
                goals_raw = await tdb.get_documents("Goal")
                routines_raw = await tdb.get_documents("Routine")
                activities_raw = await tdb.get_documents("Activity")
            finally:
                await tdb.aclose()

            self._tasks = [_normalize_task(d) for d in tasks_raw]
            self._projects = [_normalize_project(d) for d in projects_raw]
            self._goals = [_normalize_goal(d) for d in goals_raw]
            self._routines = [_normalize_routine(d) for d in routines_raw]
            self._activities = [_normalize_activity(d) for d in activities_raw]

            self._populate_table("tasks-table", ["Name", "Status", "Due Date", "Priority"], self._tasks)
            self._populate_table("projects-table", ["Name", "Status", "Target Date"], self._projects)
            self._populate_table("goals-table", ["Name", "Status", "Target Date"], self._goals)
            self._populate_table("routines-table", ["Name", "Steps", "Trigger", "Contexts"], self._routines)
            self._populate_table("activities-table", ["Name", "Start", "End", "Priority", "Routine"], self._activities)

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

        # Load calendar in parallel (uses its own TDB connection)
        self.load_calendar()

    def _populate_table(self, table_id: str, columns: list[str], rows: list[dict]) -> None:
        """Populate a DocTable with rows."""
        table = self.query_one(f"#{table_id}", DocTable)
        table.set_columns(columns)
        table.populate(rows, key_field="id")

    # ── Selection ─────────────────────────────────────────────────────────

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

    # ── Tab actions ───────────────────────────────────────────────────────

    def action_tab_tasks(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-tasks"

    def action_tab_projects(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-projects"

    def action_tab_goals(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-goals"

    def action_tab_routines(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-routines"

    def action_tab_activities(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-activities"

    def action_tab_calendar(self) -> None:
        self.query_one("#tm-tabs", TabbedContent).active = "tab-calendar"
        self._render_calendar()

    def action_clear_detail(self) -> None:
        self._selection.clear()
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_refresh(self) -> None:
        self.load()

    # ── Calendar ──────────────────────────────────────────────────────────

    @work
    async def load_calendar(self) -> None:
        """Load calendar events from all calendarable classes."""
        from firnline_core.calendar_introspect import calendarable_classes, parse_events

        try:
            tdb = self.app.ctx.make_tdb()
            try:
                schema = await tdb.get_schema()
                specs = calendarable_classes(schema)
                all_events: list[dict] = []
                for spec in specs:
                    try:
                        docs = await tdb.get_documents(spec["class_id"])
                        class_events = parse_events(docs, spec)
                        color = _color_for_class(spec["class_id"])
                        for ev in class_events:
                            ev["color"] = color
                        all_events.extend(class_events)
                    except Exception:
                        continue
            finally:
                await tdb.aclose()

            self._calendar_events = all_events
            self._render_calendar()
        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(f"Calendar: {exc}")

    def _render_calendar(self) -> None:
        """Render the calendar grid for the current month."""
        from calendar import month_name

        header_text = (
            f"[bold]{month_name[self._calendar_month]} {self._calendar_year}[/bold]"
            f"    [[]/[]] month  [0] today  [r] refresh"
        )
        self.query_one("#cal-header", Static).update(header_text)

        grid = _build_month_grid(self._calendar_year, self._calendar_month, self._calendar_events)
        self.query_one("#cal-grid", Static).update(grid)

    def _navigate_month(self, delta: int) -> None:
        """Navigate calendar by delta months."""
        self._calendar_month += delta
        while self._calendar_month > 12:
            self._calendar_month -= 12
            self._calendar_year += 1
        while self._calendar_month < 1:
            self._calendar_month += 12
            self._calendar_year -= 1
        self._render_calendar()

    def action_cal_next_month(self) -> None:
        self._navigate_month(1)

    def action_cal_prev_month(self) -> None:
        self._navigate_month(-1)

    def action_cal_today(self) -> None:
        today = date.today()
        self._calendar_year = today.year
        self._calendar_month = today.month
        self._render_calendar()
