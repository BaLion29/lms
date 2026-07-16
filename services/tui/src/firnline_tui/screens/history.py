"""History screen — commit log table + commit diff detail."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Label, Static
from textual import work

from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable, PaginationBar
from firnline_tui.ui.typography import page_heading, section_heading


_HISTORY_PAGE_SIZE = 50


class HistoryScreen(ShellScreen):
    SCREEN_ID = "history"
    TITLE = "History"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("left", "prev_page", "Prev Page"),
        Binding("right", "next_page", "Next Page"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._page_index = 0
        self._all_commits: list[dict] = []

    def compose_content(self) -> ComposeResult:
        yield page_heading("History")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield DocTable(id="commits-table")
        yield PaginationBar(id="pagination")
        yield section_heading("Commit Diff")
        yield VerticalScroll(id="commit-detail")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.history import load_history

            data = await load_history(self.app.ctx)

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)
                self.query_one("#loading", LoadingIndicator).display = False
                return

            self._all_commits = list(data.commits)
            self._render_page()

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def _render_page(self) -> None:
        total = len(self._all_commits)
        total_pages = max(1, (total + _HISTORY_PAGE_SIZE - 1) // _HISTORY_PAGE_SIZE)
        start = self._page_index * _HISTORY_PAGE_SIZE
        page = self._all_commits[start : start + _HISTORY_PAGE_SIZE]

        table = self.query_one("#commits-table", DocTable)
        table.set_columns(["Short ID", "Author", "Message", "Date"])
        table.populate(
            [
                {
                    "id": c.get("id", ""),
                    "Short ID": c.get("short_id", ""),
                    "Author": c.get("author", ""),
                    "Message": (
                        c.get("message", "")[:100]
                        if c.get("message")
                        else ""
                    ),
                    "Date": c.get("timestamp_fmt", ""),
                }
                for c in page
            ]
        )

        self.query_one("#pagination", PaginationBar).update_page(
            self._page_index, total_pages
        )

    def on_data_table_row_selected(self, event: DocTable.RowSelected) -> None:
        iri = str(event.row_key.value) if event.row_key.value else ""
        if iri:
            self._select_commit(iri)

    @work
    async def _select_commit(self, commit_id: str) -> None:
        from firnline_tui.state.history import load_commit

        detail = self.query_one("#commit-detail", VerticalScroll)
        await detail.remove_children()
        detail.mount(Label(f"Loading diff for {commit_id[:8]}…", classes="chip"))

        try:
            data = await load_commit(self.app.ctx, commit_id)
            await detail.remove_children()

            if data.error:
                detail.mount(
                    Label(f"Error: {data.error}", classes="error-banner")
                )
                return

            if data.inserted:
                detail.mount(Label("+ Inserted:", classes="status-ok"))
                for iri in data.inserted[:50]:
                    detail.mount(Label(f"  + {iri}", classes="chip"))
                if len(data.inserted) > 50:
                    detail.mount(
                        Label(f"  … and {len(data.inserted) - 50} more", classes="chip")
                    )

            if data.updated:
                detail.mount(Label("~ Updated:", classes="status-warn"))
                for iri in data.updated[:50]:
                    detail.mount(Label(f"  ~ {iri}", classes="chip"))
                if len(data.updated) > 50:
                    detail.mount(
                        Label(f"  … and {len(data.updated) - 50} more", classes="chip")
                    )

            if data.deleted:
                detail.mount(Label("- Deleted:", classes="status-err"))
                for iri in data.deleted[:50]:
                    detail.mount(Label(f"  - {iri}", classes="chip"))
                if len(data.deleted) > 50:
                    detail.mount(
                        Label(f"  … and {len(data.deleted) - 50} more", classes="chip")
                    )

            if not data.inserted and not data.updated and not data.deleted:
                detail.mount(Label("(no changes)", classes="chip"))

        except Exception as exc:
            await detail.remove_children()
            detail.mount(Label(f"Error: {exc!s}", classes="error-banner"))

    def action_prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._render_page()

    def action_next_page(self) -> None:
        total = len(self._all_commits)
        total_pages = max(1, (total + _HISTORY_PAGE_SIZE - 1) // _HISTORY_PAGE_SIZE)
        if self._page_index + 1 < total_pages:
            self._page_index += 1
            self._render_page()

    def action_refresh(self) -> None:
        self._page_index = 0
        self.load()
