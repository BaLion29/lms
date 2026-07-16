"""Browse helpers — reference extraction, row matching, sorting."""
from __future__ import annotations

from firnline_core.introspect import format_iri


def _compute_references(doc: dict, known_ids: set[str]) -> list[dict]:
    """Compute outgoing references from *doc* to *known_ids* (class @ids).

    Inspects all non-``@`` fields of *doc* for strings or dicts whose
    ``@id`` starts with a known class ID followed by ``/`` (or equals a
    known class ID exactly).  Returns a list of dicts with keys ``prop``,
    ``target``, ``target_label`` suitable for rendering as clickable links.
    """
    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for field, value in doc.items():
        if field.startswith("@"):
            continue
        _collect_refs(field, value, known_ids, refs, seen)
    return refs


def _row_matches(row: dict[str, str], query: str) -> bool:
    """Return True when *query* matches any display field of *row* case-insensitively."""
    q = query.strip().lower()
    if not q:
        return True
    for v in row.values():
        if q in v.lower():
            return True
    return False


def _sort_key(value: str) -> str:
    """Normalize string for case-insensitive sorting."""
    return value.lower()


def _is_known_ref(value: str, known_ids: set[str]) -> bool:
    """Return True if *value* references a known class (exact or prefix match).

    Only values that contain ``/`` (i.e. look like ``Class/instance-id``)
    are considered references.  Bare class-name strings are ignored.
    """
    if "/" not in value:
        return False
    if value in known_ids:
        return True
    for cid in known_ids:
        if value.startswith(cid + "/"):
            return True
    return False


def _collect_refs(
    prop: str,
    value: object,
    known_ids: set[str],
    refs: list[dict],
    seen: set[tuple[str, str]],
) -> None:
    if isinstance(value, str):
        if _is_known_ref(value, known_ids):
            key = (value, prop)
            if key not in seen:
                seen.add(key)
                refs.append(
                    {"prop": prop, "target": value, "target_label": format_iri(value)}
                )
    elif isinstance(value, dict):
        target = value.get("@id")
        if isinstance(target, str) and _is_known_ref(target, known_ids):
            key = (target, prop)
            if key not in seen:
                seen.add(key)
                refs.append(
                    {"prop": prop, "target": target, "target_label": format_iri(target)}
                )
    elif isinstance(value, list):
        for item in value:
            _collect_refs(prop, item, known_ids, refs, seen)
