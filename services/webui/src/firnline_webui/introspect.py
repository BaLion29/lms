"""Pure introspection helpers — unit-testable without Reflex.

These functions operate on schema, module, and document dicts returned by
:class:`firnline_webui.clients.TdbBrowser`.
"""

from __future__ import annotations

from typing import Any

from firnline_core.tdb import short_iri


def inbox_classes(schema: list[dict]) -> list[str]:
    """Return sorted ``@id`` values of classes whose ``@id`` starts with ``"Inbox"``.

    Excludes abstract classes (``@abstract`` key) and subdocument classes
    (``@subdocument`` key).
    """
    result: list[str] = []
    for entry in schema:
        if entry.get("@type") != "Class":
            continue
        if entry.get("@abstract") or entry.get("@subdocument"):
            continue
        cid = entry.get("@id", "")
        if isinstance(cid, str) and cid.startswith("Inbox"):
            result.append(cid)
    result.sort()
    return result


def browsable_classes(schema: list[dict]) -> list[str]:
    """Return sorted ``@id`` values of non‑abstract, non‑subdocument classes.

    Excludes enums (already filtered by ``schema_classes`` — this is a
    convenience that also accepts the raw schema).
    """
    result: list[str] = []
    for entry in schema:
        if entry.get("@type") != "Class":
            continue
        if entry.get("@abstract") or entry.get("@subdocument"):
            continue
        cid = entry.get("@id", "")
        if isinstance(cid, str) and cid:
            result.append(cid)
    result.sort()
    return result


def group_classes_by_module(class_ids: list[str], modules: list[dict]) -> dict[str, list[str]]:
    """Group *class_ids* by owning module using each module doc's ``"exports"`` list.

    Returns ``{module_name: [sorted class_ids], ...}``.

    Classes present in no module's exports go into the ``"other"`` group.
    Empty groups are omitted.
    """
    claimed: set[str] = set()
    groups: dict[str, list[str]] = {}

    for mod in modules:
        name = mod.get("name", mod.get("@id", "?"))
        exports = mod.get("exports", []) or []
        if not isinstance(exports, list):
            exports = [exports]
        owned = [c for c in class_ids if c in exports]
        if owned:
            groups[str(name)] = sorted(owned)
            claimed.update(owned)

    other = [c for c in class_ids if c not in claimed]
    if other:
        groups["other"] = sorted(other)

    return groups


def doc_preview(doc: dict, limit: int = 120) -> str:
    """Return first *limit* characters of a human‑readable preview from *doc*.

    Prefers ``"text"``, then ``"transcription"``, then the value of the first
    string‑valued field (excluding ``@`` keys).
    """
    candidates = ["text", "transcription", "content"]
    for key in candidates:
        val = doc.get(key, "")
        if isinstance(val, str) and val:
            preview = val[:limit]
            if len(val) > limit:
                preview += "…"
            return preview

    # Fall back to first string field
    for key, val in doc.items():
        if key.startswith("@"):
            continue
        if isinstance(val, str) and val:
            preview = val[:limit]
            if len(val) > limit:
                preview += "…"
            return preview

    return ""


def row_from_doc(doc: dict[str, Any], fields: list[str]) -> dict[str, str]:
    """Build a display‑ready row dict from *doc*, stringifying *fields*."""
    result: dict[str, str] = {"@id": _stringify(doc.get("@id"))}
    for field in fields:
        raw = doc.get(field)
        result[field] = _stringify(raw)
    return result


def format_iri(iri: str) -> str:
    """Strip the ``terminusdb:///data/`` prefix (reuses :func:`firnline_core.tdb.short_iri`)."""
    return short_iri(iri)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    """Compact string representation for display."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return "{…}"
    if isinstance(value, list):
        return f"[{len(value)}]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
