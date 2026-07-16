"""Inbox state — introspection-driven inbox view."""
from __future__ import annotations

from dataclasses import dataclass

from firnline_core.introspect import doc_preview, inbox_classes
from firnline_core.uiclients import TdbBrowser, UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class InboxData:
    rows: tuple[dict, ...] = ()
    statuses: tuple[str, ...] = ()
    error: str = ""


async def load_inbox(ctx: AppContext) -> InboxData:
    """Fetch schema, find Captured class, fetch all documents."""
    tdb = ctx.make_tdb()
    try:
        rows, statuses = await _load_inbox_rows(tdb)
    except UiClientError as exc:
        return InboxData(error=f"Failed to load schema: {exc.detail}")
    finally:
        await tdb.aclose()
    return InboxData(rows=tuple(rows), statuses=tuple(sorted(statuses)))


async def _load_inbox_rows(tdb: TdbBrowser) -> tuple[list[dict], set[str]]:
    """Fetch schema, find Captured class, fetch all Captured documents."""
    schema = await tdb.get_schema()
    class_ids = inbox_classes(schema)
    if not class_ids:
        return [], set()

    all_rows: list[dict] = []
    statuses: set[str] = set()

    for cid in class_ids:
        try:
            docs = await tdb.get_documents(cid)
        except UiClientError:
            continue
        for doc in docs:
            iri = doc.get("@id", "")
            status = str(doc.get("status", ""))
            captured_at = str(doc.get("captured_at", ""))
            content_type = str(doc.get("content_type", ""))
            preview = doc_preview(doc)
            all_rows.append(
                {
                    "class": cid,
                    "id": iri,
                    "status": status,
                    "captured_at": captured_at,
                    "content_type": content_type,
                    "preview": preview,
                }
            )
            if status:
                statuses.add(status)

    all_rows.sort(key=lambda r: r.get("captured_at") or "", reverse=True)
    return all_rows, statuses


def filter_rows(data: InboxData, status: str) -> list[dict]:
    """Pure filter — analog of InboxState.filtered_rows."""
    if status == "all":
        return list(data.rows)
    return [r for r in data.rows if r.get("status") == status]
