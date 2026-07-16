"""Search state — full-text entity search via IndexedClient."""
from __future__ import annotations

from firnline_core.indexed_client import IndexedError

from firnline_tui.state.context import AppContext


async def search_documents(
    ctx: AppContext, query: str, *, limit: int = 50
) -> list[dict[str, str]]:
    """Search for documents matching *query* via the indexed service.

    Returns a list of dicts with keys ``id``, ``Name``, ``Class``, ``Score``.
    Returns an empty list on error or when the query is empty.
    """
    q = query.strip()
    if not q:
        return []

    client = ctx.make_indexed()
    try:
        async with client:
            candidates = await client.find_entity(q, k=limit)
    except (IndexedError, OSError, RuntimeError) as exc:
        # RuntimeError: client not opened; OSError: connection failure
        # These are logged in tests but ignored gracefully here.
        _ = exc
        return []

    return [
        {
            "id": c.iri,
            "Name": c.name or c.iri,
            "Class": c.class_name,
            "Score": f"{c.score:.2f}",
        }
        for c in candidates
    ]
