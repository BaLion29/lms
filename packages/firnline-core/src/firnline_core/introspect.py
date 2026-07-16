"""Pure introspection helpers — unit-testable without Reflex.

These functions operate on schema, module, and document dicts returned by
:class:`firnline_webui.clients.TdbBrowser`.
"""

from __future__ import annotations

from typing import Any

from firnline_core.tdb import short_iri


def inbox_classes(schema: list[dict]) -> list[str]:
    """Return ``["Captured"]`` if the ``Captured`` class is present in *schema*.

    The capture page uses the ``Captured`` class — the kernel's
    unified capture abstraction.
    """
    for entry in schema:
        if entry.get("@type") != "Class":
            continue
        if entry.get("@abstract") or entry.get("@subdocument"):
            continue
        cid = entry.get("@id", "")
        if isinstance(cid, str) and cid == "Captured":
            return ["Captured"]
    return []


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


def class_label_field(class_def: dict) -> str | None:
    """Return the preferred label field for a class from ``@metadata.label_field``.

    Returns ``None`` when no metadata is present or the field doesn't exist.
    """
    meta = class_def.get("@metadata")
    if not isinstance(meta, dict):
        return None
    lf = meta.get("label_field")
    if isinstance(lf, str) and lf and lf in class_def:
        return lf
    return None


def doc_label(doc: dict, *, class_def: dict | None = None) -> str:
    """Return a human-readable label for *doc*.

    When *class_def* is provided, uses ``@metadata.label_field`` for the
    primary lookup.  Falls back to ``file_name``, then ``@id`` (last
    path segment), for null/empty values.  Without a class_def, prefers
    ``name``, ``title``, then ``@id``.
    """
    # Schema-driven label field
    if class_def is not None:
        lf = class_label_field(class_def)
        if lf is not None:
            val = doc.get(lf)
            if isinstance(val, str) and val.strip():
                return val
            # Null label — fall back to file_name, then @id
            fn = doc.get("file_name")
            if isinstance(fn, str) and fn.strip():
                return fn

    # Generic fallbacks (no class_def or label_field absent/null)
    for key in ("name", "title"):
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            return val

    # Last resort: @id last segment
    doc_id = doc.get("@id", "")
    if isinstance(doc_id, str):
        parts = doc_id.rstrip("/").rsplit("/", 1)
        return parts[-1]
    return str(doc_id)


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


def extract_edges(docs: list[dict], known_ids: set[str]) -> list[dict]:
    """Return deduplicated edge triples linking docs whose field values reference *known_ids*.

    For each doc (which must contain ``"@id"``) walk all non‑``"@"`` fields.
    An edge is created when a field value is:

    * A string present in *known_ids*.
    * A dict containing an ``"@id"`` key whose value is in *known_ids*.
    * A list of values of the above kinds — each matching element yields an edge.

    Self‑loops (``source == target``) and docs without ``"@id"`` are skipped.
    The result is deduplicated on ``(source, target, prop)``; order is
    insertion order of the first occurrence.
    """
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for doc in docs:
        doc_id = doc.get("@id")
        if not isinstance(doc_id, str) or not doc_id:
            continue

        for field, value in doc.items():
            if field.startswith("@"):
                continue
            _collect_edges(doc_id, field, value, known_ids, edges, seen)

    return edges


# ---------------------------------------------------------------------------
# Internal helpers for extract_edges
# ---------------------------------------------------------------------------


def _collect_edges(
    source: str,
    prop: str,
    value: object,
    known_ids: set[str],
    edges: list[dict],
    seen: set[tuple[str, str, str]],
) -> None:
    if isinstance(value, str):
        _maybe_add_edge(source, prop, value, known_ids, edges, seen)
    elif isinstance(value, dict):
        target = value.get("@id")
        if isinstance(target, str):
            _maybe_add_edge(source, prop, target, known_ids, edges, seen)
    elif isinstance(value, list):
        for item in value:
            _collect_edges(source, prop, item, known_ids, edges, seen)


def _maybe_add_edge(
    source: str,
    prop: str,
    target: str,
    known_ids: set[str],
    edges: list[dict],
    seen: set[tuple[str, str, str]],
) -> None:
    if target not in known_ids:
        return
    if source == target:
        return
    triple = (source, target, prop)
    if triple in seen:
        return
    seen.add(triple)
    edges.append({"source": source, "target": target, "prop": prop})


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
