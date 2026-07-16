"""DocTable — DataTable wrapper for document listings."""
from __future__ import annotations
from textual.app import ComposeResult
from textual.widgets import DataTable
from textual.containers import Horizontal
from textual.widgets import Label


class DocTable(DataTable):
    """A DataTable configured for document listings.

    Rows are keyed by their @id (IRI) for selection.
    Header click cycles sort direction.
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self.cursor_type = "row"
        self.zebra_stripes = True
        self._columns: list[str] = []

    def set_columns(self, columns: list[str]) -> None:
        """Set the table columns."""
        self.clear(columns=False)
        for col in columns:
            if col not in self._columns:
                self.add_column(col, key=col)
        self._columns = columns

    def populate(self, rows: list[dict], key_field: str = "id") -> None:
        """Populate the table with rows. Each row must have key_field."""
        self.clear()
        for row in rows:
            key = row.get(key_field, "")
            values = [str(row.get(col, "")) for col in self._columns]
            try:
                self.add_row(*values, key=key)
            except Exception:
                pass  # duplicate key or similar

    def get_selected_key(self) -> str | None:
        """Return the key of the currently selected row, or None."""
        try:
            if self.row_count == 0:
                return None
            return str(self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value)
        except Exception:
            return None


class PaginationBar(Horizontal):
    """Pagination controls — page X of Y, prev/next indicators."""

    def __init__(self, page_index: int = 0, total_pages: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._page_index = page_index
        self._total_pages = total_pages

    def compose(self) -> ComposeResult:
        if self._total_pages > 0:
            yield Label(f"Page {self._page_index + 1}/{self._total_pages}", classes="chip")
        else:
            yield Label("Page 1/1", classes="chip")
        yield Label("[ ←/→ ] navigate  [ s ] sort", classes="chip")

    def update_page(self, page_index: int, total_pages: int) -> None:
        """Update the displayed page info."""
        self._page_index = page_index
        self._total_pages = total_pages
        labels = list(self.query(Label))
        if labels:
            if total_pages > 0:
                labels[0].update(f"Page {page_index + 1}/{total_pages}")
            else:
                labels[0].update("Page 1/1")
