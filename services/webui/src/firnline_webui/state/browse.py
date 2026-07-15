"""Browse state — introspection-driven class browsing."""

from __future__ import annotations

import asyncio

import reflex as rx

from firnline_webui.clients import WebuiClientError, make_tdb_browser
from firnline_webui.introspect import (
    browsable_classes,
    group_classes_by_module,
)
from firnline_webui.state.base import BaseState
from firnline_webui.state.browse_class import BrowseClassState  # noqa: F401 — re-exported

__all__ = ["BrowseState", "BrowseClassState"]


class BrowseState(BaseState):
    """State for the /browse landing page."""

    groups: dict[str, list[str]] = {}  # module_name → [class_names]
    module_versions: dict[str, str] = {}  # module_name → version
    loading: bool = False
    error: str = ""

    # Tab selection
    tab: str = "classes"  # "classes" | "graph" | "relationships"

    # Search
    search_query: str = ""

    # Per-class document counts (background-fetched)
    class_counts: dict[str, str] = {}  # class_name → count_or_empty
    counts_loading: bool = False

    # ── Computed vars ───────────────────────────────────────────────

    @rx.var
    def filtered_groups(self) -> dict[str, list[str]]:
        """Groups filtered by case-insensitive substring search on class names."""
        q = self.search_query.strip().lower()
        if not q:
            return self.groups
        result: dict[str, list[str]] = {}
        for mod_name, class_ids in self.groups.items():
            filtered = [cid for cid in class_ids if q in cid.lower()]
            if filtered:
                result[mod_name] = filtered
        return result

    @rx.var
    def filtered_module_keys(self) -> list[str]:
        """Sorted module keys — alphabetically with 'other' last."""
        keys = list(self.filtered_groups.keys())
        if "other" in keys:
            keys.remove("other")
            keys.sort()
            keys.append("other")
        else:
            keys.sort()
        return keys

    @rx.var
    def has_any_class(self) -> bool:
        """True when the schema has at least one browsable class."""
        return any(len(v) > 0 for v in self.groups.values())

    @rx.var
    def search_active(self) -> bool:
        """True when search would filter anything."""
        return bool(self.search_query.strip())

    # ── Event handlers ───────────────────────────────────────────────

    @rx.event
    async def load(self):
        """Load schema + modules, group classes by module. Triggers counts after."""
        self.loading = True
        self.error = ""
        yield

        tdb = make_tdb_browser()
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
        # Kick off background count fetching
        yield BrowseState.load_counts

    @rx.event
    def refresh(self):
        """Alias for load."""
        return self.load()

    @rx.event
    async def set_tab(self, value: str):
        """Switch tab and lazily trigger graph/relationships load when their tab is selected."""
        self.tab = value
        if value == "graph":
            from firnline_webui.state.graph import GraphState  # noqa: PLC0415 — lazy, avoids circular init

            yield
            yield GraphState.load_if_needed
        elif value == "relationships":
            from firnline_webui.state.relationships import RelationshipsState  # noqa: PLC0415

            yield
            yield RelationshipsState.load_if_needed

    @rx.event
    def set_search(self, value: str):
        """Update the search query."""
        self.search_query = value

    @rx.event
    async def load_counts(self):
        """Background handler — fetch document counts for all browsable classes."""
        if self.counts_loading:
            return
        all_class_ids: list[str] = []
        for class_ids in self.groups.values():
            all_class_ids.extend(class_ids)

        if not all_class_ids:
            return

        self.counts_loading = True
        yield

        tdb = make_tdb_browser()
        counts: dict[str, str] = {}
        sem = asyncio.Semaphore(10)
        try:

            async def _fetch_one(cid: str) -> tuple[str, str]:
                async with sem:
                    try:
                        cnt = await tdb.count_documents(cid)
                        return (cid, str(cnt))
                    except WebuiClientError:
                        return (cid, "")

            tasks = [_fetch_one(cid) for cid in all_class_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and len(result) == 2:
                    cid, cnt = result
                    counts[cid] = cnt
        finally:
            await tdb.aclose()

        self.class_counts = counts
        self.counts_loading = False
        yield
