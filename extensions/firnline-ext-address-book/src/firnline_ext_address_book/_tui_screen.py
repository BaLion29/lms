"""Address Book TUI screen — People, Organizations, Locations with tabs and detail panel."""

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


def _normalize_person(doc: dict) -> dict[str, Any]:
    contact = doc.get("contact") or {}
    affiliations = doc.get("affiliations") or []
    aff_str = str(len(affiliations)) if affiliations else "-"
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Email": contact.get("email") or "-",
        "Phone": contact.get("phone") or "-",
        "Affiliations": aff_str,
    }


def _normalize_organization(doc: dict, loc_map: dict[str, str]) -> dict[str, Any]:
    loc_iri: str = doc.get("location") or ""
    loc_name: str = loc_map.get(loc_iri, "")
    if not loc_name and loc_iri:
        loc_name = loc_iri.rsplit("/", 1)[-1] if "/" in loc_iri else loc_iri
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Location": loc_name or "—",
    }


def _normalize_location(doc: dict) -> dict[str, Any]:
    coords = doc.get("coordinates")
    if coords and isinstance(coords, (list, tuple)) and len(coords) == 2:
        try:
            coord_str = f"{float(coords[0]):.4f}, {float(coords[1]):.4f}"
        except (TypeError, ValueError):
            coord_str = "—"
    else:
        coord_str = "—"
    return {
        "id": doc.get("@id", ""),
        "Name": doc.get("name", ""),
        "Address": doc.get("address") or "—",
        "Coordinates": coord_str,
    }


class AddressBookScreen(ShellScreen):
    """Address Book screen — People, Organizations, Locations with tabs and detail."""

    SCREEN_ID = "address-book"
    TITLE = "Address Book"
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_people", "People"),
        Binding("2", "tab_organizations", "Organizations"),
        Binding("3", "tab_locations", "Locations"),
        Binding("escape", "clear_detail", "Clear"),
        Binding("/", "focus_search", "Search"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._people: list[dict[str, Any]] = []
        self._organizations: list[dict[str, Any]] = []
        self._locations: list[dict[str, Any]] = []
        self._selection: Any = None

    def on_mount(self) -> None:
        from firnline_tui.state.selection import SelectionController

        self._selection = SelectionController(self.app.ctx)
        self.load()

    def compose_content(self) -> ComposeResult:
        yield page_heading("Address Book")
        yield Static(
            "Tabs: [1] People  [2] Organizations  [3] Locations  |  [r] Refresh  |  [/] Search  |  [Esc] Clear",
            classes="chip",
        )
        yield ErrorBanner(id="error")
        yield LoadingIndicator(id="loading")
        yield Input(id="address-search", placeholder="Filter by name …")
        with Horizontal():
            with Vertical(id="ab-main"):
                with TabbedContent(id="ab-tabs"):
                    with TabPane("People", id="tab-people"):
                        yield DocTable(id="people-table")
                    with TabPane("Organizations", id="tab-organizations"):
                        yield DocTable(id="orgs-table")
                    with TabPane("Locations", id="tab-locations"):
                        yield DocTable(id="locs-table")
            yield JsonDetailPanel(id="detail-panel")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @work
    async def load(self) -> None:
        """Fetch People, Organizations, and Locations from TerminusDB."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#error", ErrorBanner).hide()
        try:
            tdb = self.app.ctx.make_tdb()
            try:
                people_raw = await tdb.get_documents("Person")
                orgs_raw = await tdb.get_documents("Organization")
                locs_raw = await tdb.get_documents("Location")
            finally:
                await tdb.aclose()

            # Build location name map for org location resolution
            loc_map: dict[str, str] = {}
            for loc in locs_raw:
                iri = loc.get("@id", "")
                name = loc.get("name", "")
                if iri and name:
                    loc_map[iri] = name

            self._people = [_normalize_person(d) for d in people_raw]
            self._organizations = [_normalize_organization(d, loc_map) for d in orgs_raw]
            self._locations = [_normalize_location(d) for d in locs_raw]

            self._populate_table(
                "people-table", ["Name", "Email", "Phone", "Affiliations"], self._people
            )
            self._populate_table("orgs-table", ["Name", "Location"], self._organizations)
            self._populate_table(
                "locs-table", ["Name", "Address", "Coordinates"], self._locations
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
        tabs = self.query_one("#ab-tabs", TabbedContent)
        tabs.active = tab_id
        self._apply_search_filter()

    def action_tab_people(self) -> None:
        self._switch_tab("tab-people")

    def action_tab_organizations(self) -> None:
        self._switch_tab("tab-organizations")

    def action_tab_locations(self) -> None:
        self._switch_tab("tab-locations")

    def action_clear_detail(self) -> None:
        self._selection.clear()
        self.query_one("#detail-panel", JsonDetailPanel).clear()

    def action_refresh(self) -> None:
        self.load()

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#address-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        del event  # unused
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        """Filter the currently active tab's table by the search input."""
        search = self.query_one("#address-search", Input)
        query = search.value.strip().casefold()

        tabs = self.query_one("#ab-tabs", TabbedContent)
        active = tabs.active

        if active == "tab-people":
            self._filter_table(
                "people-table", ["Name", "Email", "Phone", "Affiliations"],
                self._people, query,
            )
        elif active == "tab-organizations":
            self._filter_table(
                "orgs-table", ["Name", "Location"],
                self._organizations, query,
            )
        elif active == "tab-locations":
            self._filter_table(
                "locs-table", ["Name", "Address", "Coordinates"],
                self._locations, query,
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
            filtered = [r for r in rows if query in str(r.get("Name", "")).casefold()]
            self._populate_table(table_id, columns, filtered)
