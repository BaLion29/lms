"""BrowseClassState — state for the /browse/[class_name] class-detail page."""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import WebuiClientError, class_display_fields, make_tdb_browser, schema_classes
from firnline_webui.introspect import row_from_doc
from firnline_webui.state.base import BaseState
from firnline_webui.state.browse_helpers import _compute_references, _row_matches, _sort_key
from firnline_webui.state.selection import SelectionMixin


class BrowseClassState(BaseState, SelectionMixin):
    """State for the /browse/[class_name] page.

    ``class_name`` is set automatically by the Reflex router from the
    dynamic route segment — access via ``self.router.page.params["class_name"]``.

    **Pagination strategy**: if the total document count is ≤ *HYBRID_THRESHOLD*
    (1000), all documents are loaded once and search/sort/pagination are handled
    client‑side for best UX.  When the count exceeds the threshold,
    server‑side pagination is used: each page is fetched individually and
    client‑side search is disabled (a hint is shown).
    """

    HYBRID_THRESHOLD: int = 1000  # noqa: S105 — class constant, not a secret

    # Display name (populated in load)
    current_class_name: str = ""

    # Document listing
    rows: list[dict[str, str]] = []  # current page (server path) or unused (hybrid)
    all_rows: list[dict[str, str]] = []  # full dataset (hybrid path only)
    display_fields: list[str] = []
    total_count: int = 0
    page_index: int = 0
    page_size: int = 25
    use_server_pagination: bool = False

    loading: bool = False
    error: str = ""
    not_found: bool = False

    # Search / sort
    search_text: str = ""
    sort_field: str = ""
    sort_dir: str = "asc"

    # Detail drawer extras
    references: list[dict] = []  # [{prop, target, target_label}, …]
    _known_class_ids: list[str] = []  # cached schema class @ids

    # ── Computed vars ───────────────────────────────────────────────

    @rx.var
    def total_pages(self) -> int:
        effective = self.effective_count
        if self.page_size <= 0 or effective <= 0:
            return 0
        return (effective + self.page_size - 1) // self.page_size

    @rx.var
    def effective_count(self) -> int:
        """Item count after filtering (hybrid) or raw total (server)."""
        if self.use_server_pagination:
            return self.total_count
        q = self.search_text.strip().lower()
        if not q:
            return self.total_count
        return sum(1 for row in self.all_rows if _row_matches(row, q))

    @rx.var
    def paged_rows(self) -> list[dict[str, str]]:
        """Current page of rows after optional search, sort, and pagination."""
        if self.use_server_pagination:
            source = self.rows
        else:
            q = self.search_text.strip().lower()
            if q:
                source = [r for r in self.all_rows if _row_matches(r, q)]
            else:
                source = list(self.all_rows)

        # Apply sort
        if self.sort_field:
            reverse = self.sort_dir == "desc"
            source = sorted(
                source,
                key=lambda r: _sort_key(r.get(self.sort_field, "")),
                reverse=reverse,
            )

        # Apply pagination
        start = self.page_index * self.page_size
        return source[start : start + self.page_size]

    # ── Event handlers ───────────────────────────────────────────────

    @rx.event
    async def load(self):
        """Load documents for the dynamic class_name.

        Uses the hybrid threshold strategy: fetch all docs when total ≤ 1000,
        otherwise use server-side pagination with per-page sorting and disabled
        client-side search.
        """
        self.loading = True
        self.error = ""
        self.not_found = False
        self.rows = []
        self.all_rows = []
        self.display_fields = []
        self.total_count = 0
        self.page_index = 0
        self.page_size = 25
        self.selected_doc = None
        self.selected_json = ""
        self.references = []
        self.search_text = ""
        self.sort_field = ""
        self.sort_dir = "asc"
        self.use_server_pagination = False
        yield

        class_name = self.router.page.params.get("class_name", "")
        self.current_class_name = class_name
        if not class_name:
            self.error = "No class name provided."
            self.loading = False
            yield
            return

        tdb = make_tdb_browser()
        try:
            # Validate class exists in schema
            schema = await tdb.get_schema()
            classes = schema_classes(schema)
            by_id = {c.get("@id", ""): c for c in classes}
            class_def = by_id.get(class_name)

            if class_def is None:
                self.not_found = True
                self.error = f"Class '{class_name}' not found in schema."
                self.loading = False
                await tdb.aclose()
                yield
                return

            self.display_fields = class_display_fields(class_def)
            # Cache known class IDs for reference extraction
            self._known_class_ids = [
                c["@id"]
                for c in classes
                if isinstance(c.get("@id"), str) and c["@id"]
            ]

            # Decide pagination strategy
            total = await tdb.count_documents(class_name)
            self.total_count = total

            if total <= self.HYBRID_THRESHOLD:
                # Hybrid: fetch all documents once
                docs = await tdb.get_documents(class_name)
                self.all_rows = [row_from_doc(d, self.display_fields) for d in docs]
                self.rows = []  # not used in hybrid mode
                self.use_server_pagination = False
            else:
                # Server path: fetch only the first page
                docs = await tdb.get_documents(class_name, skip=0, count=self.page_size)
                self.rows = [row_from_doc(d, self.display_fields) for d in docs]
                self.all_rows = []  # not used in server mode
                self.use_server_pagination = True

        except WebuiClientError as exc:
            self.error = f"Failed to load: {exc.detail}"
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def fetch_page(self):
        """Fetch the current page from the server (server-pagination path only)."""
        async for _ in self._do_fetch_page():
            yield _

    @rx.event
    async def refresh_page(self):
        """Reload the current page (re-reads count + data)."""
        yield BrowseClassState.load

    @rx.event
    async def next_page(self):
        """Go to next page."""
        if self.page_index + 1 < self.total_pages:
            self.page_index += 1
            yield
            if self.use_server_pagination:
                async for _ in self._do_fetch_page():
                    yield _
        else:
            yield

    @rx.event
    async def prev_page(self):
        """Go to previous page."""
        if self.page_index > 0:
            self.page_index -= 1
            yield
            if self.use_server_pagination:
                async for _ in self._do_fetch_page():
                    yield _
        else:
            yield

    @rx.event
    async def set_page_size(self, value: str):
        """Update page size and reset to page 0."""
        try:
            new_size = int(value)
        except (ValueError, TypeError):
            return
        if new_size <= 0:
            return
        self.page_size = new_size
        self.page_index = 0
        yield
        if self.use_server_pagination:
            async for _ in self._do_fetch_page():
                yield _

    async def _do_fetch_page(self):
        """Internal async generator: fetch the current page from the server.

        Not decorated with @rx.event — yields are merged by callers
        that are @rx.event handlers.
        """
        if not self.use_server_pagination:
            return
        class_name = self.router.page.params.get("class_name", "")
        if not class_name:
            return
        self.loading = True
        yield

        tdb = make_tdb_browser()
        try:
            skip = self.page_index * self.page_size
            docs = await tdb.get_documents(class_name, skip=skip, count=self.page_size)
            self.rows = [row_from_doc(d, self.display_fields) for d in docs]
            self.error = ""
        except WebuiClientError as exc:
            self.error = f"Failed to load page: {exc.detail}"
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def set_search(self, value: str):
        """Filter rows by case-insensitive substring (hybrid path only).

        Server-pagination mode ignores search (dataset too large).
        """
        self.search_text = value
        self.page_index = 0  # reset to first page on search
        yield

    @rx.event
    async def set_sort(self, field: str):
        """Toggle sort direction or change sort field.

        Sorting is always applied client-side (current page in server mode,
        full dataset in hybrid mode).
        """
        if self.sort_field == field:
            self.sort_dir = "desc" if self.sort_dir == "asc" else "asc"
        else:
            self.sort_field = field
            self.sort_dir = "asc"
        self.page_index = 0
        yield

    @rx.event
    async def select(self, doc_id: str):
        """Fetch a single document by IRI, compute references, and open the drawer."""
        if not doc_id:
            return
        tdb = make_tdb_browser()
        try:
            doc = await tdb.get_document(doc_id)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)

            # Compute outgoing references to known classes
            self.references = _compute_references(
                doc, set(self._known_class_ids)
            )
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
            self.references = []
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def navigate_to_reference(self, target_iri: str):
        """Fetch a referenced document by IRI and display it in the drawer."""
        if not target_iri:
            return
        yield BrowseClassState.select(target_iri)

    @rx.event
    async def clear_selection(self):
        """Close the detail drawer."""
        self.selected_doc = None
        self.selected_json = ""
        self.references = []
        yield
