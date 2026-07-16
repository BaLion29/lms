"""Browse screen — class browser + class detail with pagination."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Tree
from textual import work

from firnline_tui.ui.detail import JsonDetailPanel
from firnline_tui.ui.feedback import ErrorBanner, LoadingIndicator
from firnline_tui.ui.shell import ShellScreen
from firnline_tui.ui.tables import DocTable, PaginationBar
from firnline_tui.ui.typography import page_heading


class BrowseScreen(ShellScreen):
    """Class browser — tree view of modules and their classes."""

    SCREEN_ID = "browse"
    TITLE = "Browse"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("escape", "clear_search", "Clear search", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._browse_data = None

    def compose_content(self) -> ComposeResult:
        yield page_heading("Browse")
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Input(
            placeholder="Search classes… (Esc to clear, / to focus)",
            id="browse-search"
        )
        yield Tree("Classes", id="browse-tree")

    def on_mount(self) -> None:
        # Auto-focus the search input so the user can start typing immediately.
        self.query_one("#browse-search", Input).focus()
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.browse import load_browse

            data = await load_browse(self.app.ctx)
            self._browse_data = data

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)
                self.query_one("#loading", LoadingIndicator).display = False
                return

            tree = self.query_one("#browse-tree", Tree)
            tree.clear()
            tree.root.expand()

            for module_name, class_ids in data.groups:
                mod_node = tree.root.add(module_name, expand=True)
                for cid in class_ids:
                    cnt = data.class_counts.get(cid, "")
                    label = f"{cid} ({cnt})" if cnt else cid
                    mod_node.add_leaf(label)

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """When a leaf node (class name) is selected, open BrowseClassScreen."""
        node = event.node
        if node is None or node.is_root:
            return
        # Leaf nodes have no children; their label is the full class display
        if not node.children:
            # The label may include a count suffix like "ClassName (42)"
            label = str(node.label)
            # Strip the count suffix if present
            if " (" in label and label.endswith(")"):
                class_name = label[: label.rindex(" (")]
            else:
                class_name = label
            self._open_class(class_name)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "browse-search":
            return
        query = event.value.strip().lower()
        tree = self.query_one("#browse-tree", Tree)
        for child in tree.root.children:
            module_match = query in str(child.label).lower() if query else True
            child.expand()
            for leaf in child.children:
                leaf_match = query in str(leaf.label).lower() if query else True
                leaf.display = bool(leaf_match) if query else True
            any_visible = any(
                leaf.display for leaf in child.children
            ) if child.children else True
            child.display = bool(module_match or any_visible) if query else True

    def _open_class(self, class_name: str) -> None:
        self.app.push_screen(BrowseClassScreen(class_name=class_name))

    def action_refresh(self) -> None:
        self.load()

    def action_focus_search(self) -> None:
        """Focus the search input (vim-style / binding)."""
        self.query_one("#browse-search", Input).focus()

    def action_clear_search(self) -> None:
        """Clear the search input and refocus the tree."""
        inp = self.query_one("#browse-search", Input)
        if inp.value:
            inp.value = ""
            # Restore all nodes visibility
            tree = self.query_one("#browse-tree", Tree)
            for child in tree.root.children:
                child.display = True
                for leaf in child.children:
                    leaf.display = True
        else:
            # No search active; just move focus to the tree
            self.query_one("#browse-tree", Tree).focus()


class BrowseClassScreen(ShellScreen):
    """Class detail — document table with pagination and detail panel."""

    SCREEN_ID = "browse-class"
    TITLE = "Browse Class"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "clear_detail", "Clear"),
        Binding("left", "prev_page", "Prev Page"),
        Binding("right", "next_page", "Next Page"),
        Binding("backspace", "go_back", "Back"),
    ]

    def __init__(self, class_name: str = "") -> None:
        super().__init__()
        self._class_name = class_name
        self._page_index = 0
        self._page_size = 25
        self._total_count = 0
        self._sort_field = ""
        self._sort_dir = "asc"
        self._known_class_ids: tuple[str, ...] = ()

    @property
    def _page_title(self) -> str:
        return self._class_name or "Browse Class"

    def compose_content(self) -> ComposeResult:
        yield page_heading(self._page_title)
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        with Horizontal():
            yield DocTable(id="browse-table")
            yield JsonDetailPanel(id="detail-panel")
        yield PaginationBar(id="pagination")

    def on_mount(self) -> None:
        self.load()

    @work
    async def load(self) -> None:
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            from firnline_tui.state.browse_class import load_class

            data = await load_class(
                self.app.ctx,
                self._class_name,
                page_index=self._page_index,
                page_size=self._page_size,
                sort_field=self._sort_field,
                sort_dir=self._sort_dir,
            )

            if data.not_found:
                self.query_one("#error", ErrorBanner).show(
                    f"Class '{self._class_name}' not found."
                )
                self.query_one("#loading", LoadingIndicator).display = False
                return

            if data.error:
                self.query_one("#error", ErrorBanner).show(data.error)
                self.query_one("#loading", LoadingIndicator).display = False
                return

            self._total_count = data.total_count
            self._known_class_ids = data.known_class_ids

            # Update page heading
            heading = self.query_one(".page-heading")
            heading.update(f"{self._class_name}")

            # Populate table
            table = self.query_one("#browse-table", DocTable)
            fields = list(data.display_fields)
            table.set_columns(fields)
            table.populate([dict(r) for r in data.rows])

            # Update pagination
            total_pages = (
                (data.total_count + data.page_size - 1) // data.page_size
                if data.total_count > 0
                else 1
            )
            self.query_one("#pagination", PaginationBar).update_page(
                data.page_index, total_pages
            )

        except Exception as exc:
            self.query_one("#error", ErrorBanner).show(str(exc))
        finally:
            self.query_one("#loading", LoadingIndicator).display = False

    def on_data_table_row_selected(self, event: DocTable.RowSelected) -> None:
        iri = str(event.row_key.value) if event.row_key.value else ""
        if iri:
            self._select_document(iri)

    @work
    async def _select_document(self, iri: str) -> None:
        try:
            from firnline_tui.state.browse_class import load_document

            doc, pretty_json, refs = await load_document(
                self.app.ctx, iri, self._known_class_ids
            )
            self.query_one("#detail-panel", JsonDetailPanel).show_document(
                iri, pretty_json
            )
        except Exception as exc:
            self.query_one("#detail-panel", JsonDetailPanel).show_error(str(exc))

    def action_clear_detail(self) -> None:
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self.load()

    def action_next_page(self) -> None:
        total_pages = (
            (self._total_count + self._page_size - 1) // self._page_size
            if self._total_count > 0
            else 1
        )
        if self._page_index + 1 < total_pages:
            self._page_index += 1
            self.load()

    def action_refresh(self) -> None:
        self.load()
