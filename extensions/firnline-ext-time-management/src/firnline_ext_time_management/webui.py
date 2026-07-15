"""WebUI page plugin for the time-management extension.

Registered via the ``firnline.webui.pages`` entry point.  Provides a
read-only overview page at ``/time`` with tab-separated tables for
Tasks, Projects, and Goals.

All ``reflex`` and ``firnline_webui`` imports are confined to this
module, which is only loaded inside the WebUI process (other services
discover different entry-point groups).  The extension's
``[project] dependencies`` do NOT include reflex or firnline_webui.
"""

from __future__ import annotations

import reflex as rx

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import ModuleRequirement

from firnline_webui.clients import make_tdb_browser
from firnline_webui.state.auth import AuthState
from firnline_webui.state.base import BaseState
from firnline_webui.state.selection import SelectionMixin
from firnline_webui.ui.cards import status_badge
from firnline_webui.ui.detail import iri_var, json_detail_drawer
from firnline_webui.ui.feedback import empty_state, error_callout
from firnline_webui.ui.nav import shell
from firnline_webui.ui.theme import TABLE_ROW_STYLE

# ---------------------------------------------------------------------------
# Status-colour mapping (shared across Task, Project, Goal statuses)
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[str, str] = {
    "open": "blue",
    "planned": "amber",
    "done": "green",
    "active": "blue",
    "on_hold": "amber",
    "completed": "green",
    "achieved": "green",
    "abandoned": "gray",
}

# ---------------------------------------------------------------------------
# Row normalisation helpers
# ---------------------------------------------------------------------------


def _fmt_date(raw: object) -> str:
    """Return a display string for a TDB datetime value."""
    if raw is None:
        return ""
    s = str(raw)
    # Strip TDB ^^xsd:dateTime suffix if present
    if "^^" in s:
        s = s.split("^^")[0]
    return s[:10] if s else ""


def _normalize_task(doc: dict) -> dict:
    priority = doc.get("priority") or 0
    return {
        "@id": doc.get("@id", ""),
        "name": doc.get("name", ""),
        "status": doc.get("status", ""),
        "due_date": _fmt_date(doc.get("due_date")),
        "priority": priority,
        "priority_display": f"P{priority}" if priority else "-",
    }


def _normalize_project(doc: dict) -> dict:
    return {
        "@id": doc.get("@id", ""),
        "name": doc.get("name", ""),
        "status": doc.get("status", ""),
        "target_date": _fmt_date(doc.get("target_date")),
    }


def _normalize_goal(doc: dict) -> dict:
    return {
        "@id": doc.get("@id", ""),
        "name": doc.get("name", ""),
        "status": doc.get("status", ""),
        "target_date": _fmt_date(doc.get("target_date")),
    }


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TimeManagementState(BaseState, SelectionMixin):
    """State for the /time page.

    Fetches all Tasks, Projects, and Goals on load and exposes them
    as tab-filtered table rows.  Row click opens the shared JSON detail
    drawer via ``SelectionMixin``.
    """

    tasks: list[dict] = []
    projects: list[dict] = []
    goals: list[dict] = []
    loading: bool = False
    error: str = ""
    tab: str = "tasks"  # "tasks" | "projects" | "goals"

    # ── Computed vars ───────────────────────────────────────────────

    @rx.var
    def current_rows(self) -> list[dict]:
        """Rows for the currently active tab."""
        if self.tab == "tasks":
            return self.tasks
        if self.tab == "projects":
            return self.projects
        return self.goals

    @rx.var
    def current_class_name(self) -> str:
        """Class name for the currently active tab."""
        if self.tab == "tasks":
            return "Task"
        if self.tab == "projects":
            return "Project"
        return "Goal"

    # ── Event handlers ──────────────────────────────────────────────

    @rx.event
    async def load(self):
        """Fetch Tasks, Projects, and Goals from TerminusDB."""
        self.loading = True
        self.error = ""
        self.selected_doc = None
        self.selected_json = ""
        yield

        tdb = make_tdb_browser()
        try:
            self.tasks = [_normalize_task(d) for d in await tdb.get_documents("Task")]
            self.projects = [_normalize_project(d) for d in await tdb.get_documents("Project")]
            self.goals = [_normalize_goal(d) for d in await tdb.get_documents("Goal")]
        except Exception as exc:
            self.error = f"Failed to load data: {exc}"
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def set_tab(self, value: str):
        """Switch the active tab."""
        self.tab = value
        yield


# ---------------------------------------------------------------------------
# Page components
# ---------------------------------------------------------------------------


def _date_cell(date_val: rx.Var[str]) -> rx.Component:
    """Render a date string or a dash."""
    return rx.cond(
        date_val != "",
        rx.text(date_val, size="2", color_scheme="gray"),
        rx.text("-", size="2", color_scheme="gray"),
    )


def _tab_table() -> rx.Component:
    """Shared table that renders ``TimeManagementState.current_rows``."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Name"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell(
                    rx.cond(
                        TimeManagementState.tab == "tasks",
                        "Due Date",
                        "Target Date",
                    ),
                ),
                rx.table.column_header_cell(
                    rx.cond(
                        TimeManagementState.tab == "tasks",
                        "Priority",
                        "",
                    ),
                ),
            ),
        ),
        rx.table.body(
            rx.foreach(
                TimeManagementState.current_rows,
                lambda row: rx.table.row(
                    rx.table.cell(rx.text(row["name"], size="2")),
                    rx.table.cell(status_badge(row["status"], _STATUS_COLORS)),
                    rx.table.cell(
                        rx.cond(
                            TimeManagementState.tab == "tasks",
                            _date_cell(row["due_date"]),
                            _date_cell(row["target_date"]),
                        ),
                    ),
                    rx.table.cell(
                        rx.cond(
                            TimeManagementState.tab == "tasks",
                            rx.text(row["priority_display"], size="2"),
                            rx.text("", size="2"),
                        ),
                    ),
                    cursor="pointer",
                    **TABLE_ROW_STYLE,
                    tab_index=0,
                    role="button",
                    on_click=TimeManagementState.select(row["@id"]),
                ),
            ),
        ),
        variant="surface",
        size="3",
        width="100%",
    )


def time_page() -> rx.Component:
    """Read-only overview page for Tasks, Projects, and Goals."""
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                rx.heading("Time Management", size="6"),
                rx.spacer(),
                rx.cond(TimeManagementState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=TimeManagementState.load,
                    size="2",
                    variant="outline",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error callout
            rx.cond(
                TimeManagementState.error != "",
                error_callout(TimeManagementState.error),
            ),
            # Tabs + table
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Tasks", value="tasks"),
                    rx.tabs.trigger("Projects", value="projects"),
                    rx.tabs.trigger("Goals", value="goals"),
                    size="2",
                ),
                # Tasks tab
                rx.tabs.content(
                    rx.cond(
                        (~TimeManagementState.loading)
                        & (TimeManagementState.error == ""),
                        rx.cond(
                            TimeManagementState.tasks.length() > 0,
                            _tab_table(),
                            rx.cond(
                                TimeManagementState.tab == "tasks",
                                empty_state(
                                    "list_todo",
                                    "No tasks found.",
                                    hint="Tasks from the time-management module appear here.",
                                    show_card=True,
                                ),
                            ),
                        ),
                    ),
                    value="tasks",
                ),
                # Projects tab
                rx.tabs.content(
                    rx.cond(
                        (~TimeManagementState.loading)
                        & (TimeManagementState.error == ""),
                        rx.cond(
                            TimeManagementState.projects.length() > 0,
                            _tab_table(),
                            rx.cond(
                                TimeManagementState.tab == "projects",
                                empty_state(
                                    "folders",
                                    "No projects found.",
                                    hint="Projects from the time-management module appear here.",
                                    show_card=True,
                                ),
                            ),
                        ),
                    ),
                    value="projects",
                ),
                # Goals tab
                rx.tabs.content(
                    rx.cond(
                        (~TimeManagementState.loading)
                        & (TimeManagementState.error == ""),
                        rx.cond(
                            TimeManagementState.goals.length() > 0,
                            _tab_table(),
                            rx.cond(
                                TimeManagementState.tab == "goals",
                                empty_state(
                                    "target",
                                    "No goals found.",
                                    hint="Goals from the time-management module appear here.",
                                    show_card=True,
                                ),
                            ),
                        ),
                    ),
                    value="goals",
                ),
                value=TimeManagementState.tab,
                on_change=TimeManagementState.set_tab,
                width="100%",
            ),
            # Detail drawer
            json_detail_drawer(
                doc_var=TimeManagementState.selected_doc,
                json_var=TimeManagementState.selected_json,
                iri_var=iri_var(TimeManagementState.selected_doc),
                on_close=TimeManagementState.clear_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="time",
    )


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class TimeManagementWebUIPlugin:
    """WebUI page plugin providing the Time Management overview.

    Conforms to :class:`~firnline_core.plugins.WebUIPagePlugin`.
    """

    name: str = "time_management_webui"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="time_management", range=">=0.2.0 <0.3.0"),
    ]

    def pages(self) -> list[PageSpec]:
        return [
            PageSpec(
                route="/time",
                title="Time Management",
                component=time_page,
                nav_section="MAIN",
                nav_icon="clock",
                nav_order=45,
                on_load=[AuthState.check, TimeManagementState.load],
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level singleton for entry-point discovery
# ---------------------------------------------------------------------------

plugin = TimeManagementWebUIPlugin()
