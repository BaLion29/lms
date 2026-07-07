"""Browse state — introspection-driven class browsing."""

from __future__ import annotations

import json

import reflex as rx

from firnline_webui.clients import TdbBrowser, WebuiClientError, class_display_fields, schema_classes
from firnline_webui.introspect import browsable_classes, group_classes_by_module, row_from_doc
from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

_settings = get_settings()


def _make_tdb() -> TdbBrowser:
    return TdbBrowser(
        _settings.tdb_url,
        _settings.tdb_org,
        _settings.tdb_db,
        _settings.tdb_user,
        _settings.tdb_password,
        branch=_settings.tdb_branch,
        timeout=_settings.request_timeout_seconds,
    )


class BrowseState(BaseState):
    """State for the /browse landing page."""

    groups: dict[str, list[str]] = {}  # module_name → [class_names]
    module_versions: dict[str, str] = {}  # module_name → version
    loading: bool = False
    error: str = ""

    @rx.event
    async def load(self):
        """Load schema + modules, group classes by module."""
        self.loading = True
        self.error = ""
        yield

        tdb = _make_tdb()
        try:
            schema = await tdb.get_schema()
            modules = await tdb.get_modules()
        except WebuiClientError as exc:
            self.error = f"Failed to load data: {exc.detail}"
        else:
            all_ids = browsable_classes(schema)
            self.groups = group_classes_by_module(all_ids, modules)

            versions: dict[str, str] = {}
            for mod in modules:
                name = mod.get("name", mod.get("@id", ""))
                ver = str(mod.get("version", ""))
                if name and ver:
                    versions[str(name)] = ver
            self.module_versions = versions
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    def refresh(self):
        """Alias for load."""
        return self.load()


class BrowseClassState(BaseState):
    """State for the /browse/[class_name] page.

    ``class_name`` is set automatically by the Reflex router from the
    dynamic route segment — access via ``self.router.page.params["class_name"]``.
    """

    # Display name (populated in load)
    current_class_name: str = ""

    # Document listing
    rows: list[dict[str, str]] = []
    display_fields: list[str] = []
    total_count: int = 0
    page_index: int = 0
    page_size: int = 25

    loading: bool = False
    error: str = ""
    not_found: bool = False

    # Detail drawer
    selected_doc: dict | None = None
    selected_json: str = ""

    @rx.var
    def total_pages(self) -> int:
        if self.page_size <= 0 or self.total_count <= 0:
            return 0
        return (self.total_count + self.page_size - 1) // self.page_size

    @rx.var
    def paged_rows(self) -> list[dict[str, str]]:
        start = self.page_index * self.page_size
        return self.rows[start : start + self.page_size]

    @rx.event
    async def load(self):
        """Load documents for the dynamic class_name."""
        self.loading = True
        self.error = ""
        self.not_found = False
        self.rows = []
        self.display_fields = []
        self.total_count = 0
        self.page_index = 0
        self.selected_doc = None
        self.selected_json = ""
        yield

        class_name = self.router.page.params.get("class_name", "")
        self.current_class_name = class_name
        if not class_name:
            self.error = "No class name provided."
            self.loading = False
            yield
            return

        tdb = _make_tdb()
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

            docs = await tdb.get_documents(class_name)
            self.total_count = len(docs)
            self.rows = [row_from_doc(d, self.display_fields) for d in docs]

        except WebuiClientError as exc:
            self.error = f"Failed to load: {exc.detail}"
        finally:
            await tdb.aclose()

        self.loading = False
        yield

    @rx.event
    async def next_page(self):
        """Go to next page."""
        if self.page_index + 1 < self.total_pages:
            self.page_index += 1
        yield

    @rx.event
    async def prev_page(self):
        """Go to previous page."""
        if self.page_index > 0:
            self.page_index -= 1
        yield

    @rx.event
    async def select(self, doc_id: str):
        """Fetch a single document by IRI and open the detail drawer."""
        tdb = _make_tdb()
        try:
            doc = await tdb.get_document(doc_id)
            self.selected_doc = doc
            self.selected_json = json.dumps(doc, indent=2, default=str)
        except WebuiClientError as exc:
            self.selected_doc = {"error": str(exc.detail)}
            self.selected_json = json.dumps(self.selected_doc, indent=2)
        finally:
            await tdb.aclose()
        yield

    @rx.event
    async def clear_selection(self):
        """Close the detail drawer."""
        self.selected_doc = None
        self.selected_json = ""
        yield
