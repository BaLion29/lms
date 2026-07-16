"""BrowseClassState — load documents for a single class (framework-free)."""
from __future__ import annotations

from dataclasses import dataclass, field

from firnline_core.introspect import row_from_doc
from firnline_core.uiclients import UiClientError, class_display_fields, schema_classes

from firnline_tui.state.browse_helpers import _compute_references, _row_matches, _sort_key
from firnline_tui.state.context import AppContext

HYBRID_THRESHOLD = 1000


@dataclass(frozen=True)
class ClassPageData:
    class_name: str = ""
    display_fields: tuple[str, ...] = ()
    rows: tuple[dict[str, str], ...] = ()
    total_count: int = 0
    page_index: int = 0
    page_size: int = 25
    use_server_pagination: bool = False
    not_found: bool = False
    error: str = ""

    # Metadata for reference extraction
    known_class_ids: tuple[str, ...] = ()


async def load_class(
    ctx: AppContext,
    class_name: str,
    page_index: int = 0,
    page_size: int = 25,
    sort_field: str = "",
    sort_dir: str = "asc",
) -> ClassPageData:
    """Load documents for *class_name* with pagination strategy.

    Uses hybrid threshold: fetch all docs when total <= 1000 (client-side
    search/sort/pagination), otherwise server-side pagination.
    """
    if not class_name:
        return ClassPageData(error="No class name provided.")

    tdb = ctx.make_tdb()
    try:
        # Validate class exists in schema
        schema = await tdb.get_schema()
        classes = schema_classes(schema)
        by_id = {c.get("@id", ""): c for c in classes}
        class_def = by_id.get(class_name)

        if class_def is None:
            return ClassPageData(
                class_name=class_name, not_found=True,
                error=f"Class '{class_name}' not found in schema.",
            )

        fields = class_display_fields(class_def)
        known_ids = tuple(
            c["@id"] for c in classes
            if isinstance(c.get("@id"), str) and c["@id"]
        )

        # Decide pagination strategy
        total = await tdb.count_documents(class_name)

        if total <= HYBRID_THRESHOLD:
            # Hybrid: fetch all documents once
            docs = await tdb.get_documents(class_name)
            all_rows = [row_from_doc(d, fields) for d in docs]

            # Apply sort
            if sort_field:
                reverse = sort_dir == "desc"
                all_rows = sorted(
                    all_rows,
                    key=lambda r: _sort_key(r.get(sort_field, "")),
                    reverse=reverse,
                )

            # Apply pagination
            start = page_index * page_size
            page_rows = all_rows[start : start + page_size]

            return ClassPageData(
                class_name=class_name,
                display_fields=tuple(fields),
                rows=tuple(page_rows),
                total_count=total,
                page_index=page_index,
                page_size=page_size,
                use_server_pagination=False,
                known_class_ids=known_ids,
            )
        else:
            # Server path: fetch only the requested page
            skip = page_index * page_size
            docs = await tdb.get_documents(class_name, skip=skip, count=page_size)
            rows = [row_from_doc(d, fields) for d in docs]

            return ClassPageData(
                class_name=class_name,
                display_fields=tuple(fields),
                rows=tuple(rows),
                total_count=total,
                page_index=page_index,
                page_size=page_size,
                use_server_pagination=True,
                known_class_ids=known_ids,
            )

    except UiClientError as exc:
        return ClassPageData(
            class_name=class_name,
            error=f"Failed to load: {exc.detail}",
        )
    finally:
        await tdb.aclose()


async def load_class_with_search(
    ctx: AppContext,
    class_name: str,
    search_text: str = "",
    page_index: int = 0,
    page_size: int = 25,
    sort_field: str = "",
    sort_dir: str = "asc",
) -> ClassPageData:
    """Like load_class but with client-side search filtering.

    Only works in hybrid mode; server-pagination results are returned as-is
    (search not applicable for large datasets).
    """
    data = await load_class(ctx, class_name, page_index=0, page_size=0,
                            sort_field=sort_field, sort_dir=sort_dir)
    if data.error or data.not_found:
        return data
    if data.use_server_pagination:
        return data  # search not supported in server mode

    # Re-fetch with full data (page_size=0 triggers no pagination in hybrid)
    # Actually, we need a different approach: fetch all, filter, paginate
    return await _load_class_hybrid_search(
        ctx, class_name, data.display_fields, data.known_class_ids,
        search_text, page_index, page_size, sort_field, sort_dir,
    )


async def _load_class_hybrid_search(
    ctx: AppContext,
    class_name: str,
    fields: tuple[str, ...],
    known_ids: tuple[str, ...],
    search_text: str,
    page_index: int,
    page_size: int,
    sort_field: str,
    sort_dir: str,
) -> ClassPageData:
    """Fetch all documents and apply client-side search/sort/pagination."""
    tdb = ctx.make_tdb()
    try:
        total = await tdb.count_documents(class_name)
        docs = await tdb.get_documents(class_name)
        all_rows = [row_from_doc(d, list(fields)) for d in docs]

        # Filter
        q = search_text.strip().lower()
        if q:
            all_rows = [r for r in all_rows if _row_matches(r, q)]

        # Sort
        if sort_field:
            reverse = sort_dir == "desc"
            all_rows = sorted(
                all_rows,
                key=lambda r: _sort_key(r.get(sort_field, "")),
                reverse=reverse,
            )

        filtered_count = len(all_rows)
        start = page_index * page_size
        page_rows = all_rows[start : start + page_size]

        return ClassPageData(
            class_name=class_name,
            display_fields=fields,
            rows=tuple(page_rows),
            total_count=filtered_count,
            page_index=page_index,
            page_size=page_size,
            use_server_pagination=False,
            known_class_ids=known_ids,
        )
    except UiClientError as exc:
        return ClassPageData(class_name=class_name, error=f"Failed to load: {exc.detail}")
    finally:
        await tdb.aclose()


async def load_document(ctx: AppContext, doc_id: str, known_class_ids: tuple[str, ...] = ()) -> tuple[dict | None, str, list[dict]]:
    """Fetch a single document by IRI, returning (doc, pretty_json, references).

    Returns (None, "", []) on empty doc_id or error.
    """
    if not doc_id:
        return (None, "", [])
    import json

    tdb = ctx.make_tdb()
    try:
        doc = await tdb.get_document(doc_id)
        pretty = json.dumps(doc, indent=2, default=str)
        refs = _compute_references(doc, set(known_class_ids))
        return (doc, pretty, refs)
    except UiClientError:
        return (None, f'{{"error": "Failed to fetch {doc_id}"}}', [])
    finally:
        await tdb.aclose()
