"""Browse state — introspection-driven class browsing."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from firnline_core.introspect import browsable_classes, group_classes_by_module
from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class BrowseData:
    groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    module_versions: dict[str, str] = field(default_factory=dict)
    class_counts: dict[str, str] = field(default_factory=dict)
    error: str = ""


async def load_browse(ctx: AppContext) -> BrowseData:
    """Load schema + modules, group classes by module, fetch counts."""
    tdb = ctx.make_tdb()
    try:
        schema = await tdb.get_schema()
        modules = await tdb.get_modules()
    except UiClientError as exc:
        await tdb.aclose()
        return BrowseData(error=f"Failed to load data: {exc.detail}")

    all_ids = browsable_classes(schema)
    groups_dict = group_classes_by_module(all_ids, modules)

    # Convert to sorted tuple of (module_name, tuple(class_names))
    sorted_modules = sorted(groups_dict.keys())
    if "other" in sorted_modules:
        sorted_modules.remove("other")
        sorted_modules.sort()
        sorted_modules.append("other")
    groups: list[tuple[str, tuple[str, ...]]] = [
        (m, tuple(groups_dict[m])) for m in sorted_modules
    ]

    # Extract module versions
    versions: dict[str, str] = {}
    for mod in modules:
        name = mod.get("name", mod.get("@id", ""))
        ver = str(mod.get("version", ""))
        if name and ver:
            versions[str(name)] = ver

    await tdb.aclose()

    # Fetch counts with semaphore
    all_class_ids = [cid for _, ids in groups for cid in ids]
    counts = await _fetch_counts(ctx, all_class_ids)

    return BrowseData(
        groups=tuple(groups),
        module_versions=versions,
        class_counts=counts,
    )


async def _fetch_counts(ctx: AppContext, class_ids: list[str]) -> dict[str, str]:
    """Fetch document counts for all browsable classes concurrently (semaphore=10)."""
    if not class_ids:
        return {}

    tdb = ctx.make_tdb()
    counts: dict[str, str] = {}
    sem = asyncio.Semaphore(10)
    try:

        async def _fetch_one(cid: str) -> tuple[str, str]:
            async with sem:
                try:
                    cnt = await tdb.count_documents(cid)
                    return (cid, str(cnt))
                except UiClientError:
                    return (cid, "")

        tasks = [_fetch_one(cid) for cid in class_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                cid, cnt = result
                counts[cid] = cnt
    finally:
        await tdb.aclose()

    return counts
