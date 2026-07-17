"""Deliberation TUI screen — Decisions, Problems, Questions with tabs and detail panel."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane

from firnline_tui.ui.detail import JsonDetailPanel
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable
from firnline_tui.ui.typography import page_heading


def _normalize_decision(doc: dict) -> dict[str, Any]:
    return {
        "id": doc.get("@id", ""),
        "Title": doc.get("title", ""),
        "Status": doc.get("status", ""),
        "Decision": doc.get("decision", ""),
    }


def _normalize_problem(doc: dict) -> dict[str, Any]:
    return {
        "id": doc.get("@id", ""),
        "Title": doc.get("title", ""),
        "Status": doc.get("status", ""),
        "Impact": doc.get("impact") or "—",
    }


def _normalize_question(doc: dict) -> dict[str, Any]:
    return {
        "id": doc.get("@id", ""),
        "Question": doc.get("question", ""),
        "Status": doc.get("status", ""),
        "Answer": doc.get("answer") or "—",
    }


class DeliberationScreen(ShellScreen):
    """Deliberation screen — Decisions, Problems, Questions with tabs and detail."""

    SCREEN_ID = "deliberation"
    TITLE = "Deliberation"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_decisions", "Decisions"),
        Binding("2", "tab_problems", "Problems"),
        Binding("3", "tab_questions", "Questions"),
        Binding("escape", "clear_detail", "Clear"),
        Binding("/", "focus_search", "Search"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._decisions: list[dict[str, Any]] = []
        self._problems: list[dict[str, Any]] = []
        self._questions: list[dict[str, Any]] = []
        self._selection: Any = None

    def on_mount(self) -> None:
        from firnline_tui.state.selection import SelectionController

        self._selection = SelectionController(self.app.ctx)
        self.load()

    def compose_content(self) -> ComposeResult:
        yield page_heading("Deliberation")
        yield Static(
            "Tabs: [1] Decisions  [2] Problems  [3] Questions  |  [r] Refresh  |  [/] Search  |  [Esc] Clear",
            classes="chip",
        )
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Input(id="deliberation-search", placeholder="Filter …")
        with Horizontal():
            with Vertical(id="del-main"):
                with TabbedContent(id="del-tabs"):
                    with TabPane("Decisions", id="tab-decisions"):
                        yield DocTable(id="decisions-table")
                    with TabPane("Problems", id="tab-problems"):
                        yield DocTable(id="problems-table")
                    with TabPane("Questions", id="tab-questions"):
                        yield DocTable(id="questions-table")
            yield JsonDetailPanel(id="detail-panel")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @work
    async def load(self) -> None:
        """Fetch Decisions, Problems, and Questions from TerminusDB."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            tdb = self.app.ctx.make_tdb()
            try:
                decisions_raw = await tdb.get_documents("Decision")
                problems_raw = await tdb.get_documents("Problem")
                questions_raw = await tdb.get_documents("Question")
            finally:
                await tdb.aclose()

            self._decisions = [_normalize_decision(d) for d in decisions_raw]
            self._problems = [_normalize_problem(d) for d in problems_raw]
            self._questions = [_normalize_question(d) for d in questions_raw]

            self._populate_table(
                "decisions-table", ["Title", "Status", "Decision"], self._decisions
            )
            self._populate_table(
                "problems-table", ["Title", "Status", "Impact"], self._problems
            )
            self._populate_table(
                "questions-table", ["Question", "Status", "Answer"], self._questions
            )

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def _populate_table(
        self, table_id: str, columns: list[str], rows: list[dict[str, Any]]
    ) -> None:
        """Populate a DocTable with rows."""
        table = self.query_one(f"#{table_id}", DocTable)
        table.set_columns(columns)
        table.populate(rows, key_field="id")

    # ------------------------------------------------------------------
    # Row selection → detail panel
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def _switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#del-tabs", TabbedContent)
        tabs.active = tab_id
        self._apply_search_filter()

    def action_tab_decisions(self) -> None:
        self._switch_tab("tab-decisions")

    def action_tab_problems(self) -> None:
        self._switch_tab("tab-problems")

    def action_tab_questions(self) -> None:
        self._switch_tab("tab-questions")

    def action_clear_detail(self) -> None:
        self._selection.clear()
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_refresh(self) -> None:
        self.load()

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#deliberation-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        del event  # unused
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        """Filter the currently active tab's table by the search input."""
        search = self.query_one("#deliberation-search", Input)
        query = search.value.strip().casefold()

        tabs = self.query_one("#del-tabs", TabbedContent)
        active = tabs.active

        if active == "tab-decisions":
            self._filter_table(
                "decisions-table", ["Title", "Status", "Decision"],
                self._decisions, query,
            )
        elif active == "tab-problems":
            self._filter_table(
                "problems-table", ["Title", "Status", "Impact"],
                self._problems, query,
            )
        elif active == "tab-questions":
            self._filter_table(
                "questions-table", ["Question", "Status", "Answer"],
                self._questions, query,
            )

    def _filter_table(
        self,
        table_id: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        query: str,
    ) -> None:
        if not query:
            self._populate_table(table_id, columns, rows)
        else:
            key = columns[0]
            filtered = [r for r in rows if query in str(r.get(key, "")).casefold()]
            self._populate_table(table_id, columns, filtered)
