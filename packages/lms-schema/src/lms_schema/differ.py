"""Semver change classification and diff computation for schema module fragments.

Given two versions of a module's fragment (list of class/enum defs), classify
every change as ADDITIVE (MINOR ok) or BREAKING (MAJOR required).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .semver import Version


# ---------------------------------------------------------------------------
# Change record
# ---------------------------------------------------------------------------


@dataclass
class Change:
    module: str
    kind: Literal["additive", "breaking"]
    description: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_id(classes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index class/enum definitions by @id, skipping @context entries."""
    result: dict[str, dict[str, Any]] = {}
    for cls in classes:
        if cls.get("@type") == "@context":
            continue
        cid = cls.get("@id")
        if isinstance(cid, str):
            result[cid] = cls
    return result


def _canonical(val: Any) -> str:
    """Deterministic JSON representation of *val*."""
    import json
    return json.dumps(val, sort_keys=True, separators=(",", ":"))


def _is_wrapper(prop_val: Any, wrapper: str) -> bool:
    """Check if a property value dict has @type == *wrapper*."""
    if isinstance(prop_val, dict) and prop_val.get("@type") == wrapper:
        return True
    return False


_WRAPPERS = {"Optional", "Set", "List"}


def _has_nonequivocal_wrapper(prop_val: Any) -> bool:
    """True if the property value is a wrapper that makes the field non-required.

    An Optional, Set, or List wrapper means absence/empty is valid for existing docs.
    """
    return isinstance(prop_val, dict) and prop_val.get("@type") in _WRAPPERS


def _class_meta_keys() -> set[str]:
    """@-keys that are class-level metadata (not properties)."""
    return {
        "@id", "@type", "@inherits", "@abstract", "@subdocument",
        "@key", "@oneOf", "@value",
    }


def _prop_keys(cls: dict[str, Any]) -> set[str]:
    """Return the set of property keys (non-@-meta keys)."""
    meta = _class_meta_keys()
    return {k for k in cls if k not in meta}


def _enum_values(cls: dict[str, Any]) -> list[str]:
    """Return the ordered list of @values for an enum class.

    Enum @values are stored in ordinal position by TerminusDB; reordering
    is therefore breaking.
    """
    vals = cls.get("@value")
    if isinstance(vals, list):
        return [v for v in vals if isinstance(v, str)]
    if isinstance(vals, str):
        return [vals]
    return []


# ---------------------------------------------------------------------------
# Per-property classification
# ---------------------------------------------------------------------------


def _classify_property_changes(
    cid: str,
    old_cls: dict[str, Any],
    new_cls: dict[str, Any],
) -> list[Change]:
    """Classify changes to the property slots of a class definition."""
    changes: list[Change] = []

    old_props = _prop_keys(old_cls)
    new_props = _prop_keys(new_cls)

    # Added properties
    for key in new_props - old_props:
        new_val = new_cls[key]
        if _has_nonequivocal_wrapper(new_val):
            changes.append(Change(
                module="",  # filled by caller
                kind="additive",
                description=f"Class '{cid}': new property '{key}' (wrapped in {new_val.get('@type', '?')})",
            ))
        else:
            changes.append(Change(
                module="",
                kind="breaking",
                description=f"Class '{cid}': new REQUIRED property '{key}'",
            ))

    # Removed properties
    for key in old_props - new_props:
        changes.append(Change(
            module="",
            kind="breaking",
            description=f"Class '{cid}': removed property '{key}'",
        ))

    # Changed properties
    for key in old_props & new_props:
        old_val = old_cls[key]
        new_val = new_cls[key]
        if _canonical(old_val) != _canonical(new_val):
            # required → Optional is still breaking but the range *widened*
            was_required = not _has_nonequivocal_wrapper(old_val)
            became_optional = _is_wrapper(new_val, "Optional")
            if was_required and became_optional:
                desc = f"Class '{cid}': property '{key}' range widened (required → Optional)"
            else:
                desc = f"Class '{cid}': property '{key}' range/type changed"
            changes.append(Change(
                module="",
                kind="breaking",
                description=desc,
            ))

    return changes


# ---------------------------------------------------------------------------
# Per-class classification
# ---------------------------------------------------------------------------


def _classify_class_changes(
    cid: str,
    old_cls: dict[str, Any],
    new_cls: dict[str, Any],
) -> list[Change]:
    """Classify changes between old and new versions of the same class."""
    changes: list[Change] = []

    # --- Meta-field changes (all breaking) ---
    for meta in ("@inherits", "@key", "@abstract", "@subdocument", "@oneOf"):
        old_val = old_cls.get(meta)
        new_val = new_cls.get(meta)
        if _canonical(old_val) != _canonical(new_val):
            changes.append(Change(
                module="",
                kind="breaking",
                description=f"Class '{cid}': {meta} changed",
            ))

    # --- Enum @value changes ---
    if old_cls.get("@type") == "Enum" or old_cls.get("@type") == "enum":
        old_vals = _enum_values(old_cls)
        new_vals = _enum_values(new_cls)
        old_set = set(old_vals)
        new_set = set(new_vals)
        added = [v for v in new_vals if v not in old_set]
        removed = [v for v in old_vals if v not in new_set]
        for v in added:
            changes.append(Change(
                module="",
                kind="additive",
                description=f"Enum '{cid}': new @value '{v}'",
            ))
        for v in removed:
            changes.append(Change(
                module="",
                kind="breaking",
                description=f"Enum '{cid}': removed @value '{v}'",
            ))
        # Reordering is breaking (TerminusDB ordinal storage)
        if old_vals != new_vals:
            # Build the old→new mapping ignoring additions/removals
            common = [v for v in old_vals if v in new_set]
            common_new = [v for v in new_vals if v in old_set]
            if common != common_new:
                changes.append(Change(
                    module="",
                    kind="breaking",
                    description=f"Enum '{cid}': @value list reordered",
                ))

    # --- Property changes ---
    changes.extend(_classify_property_changes(cid, old_cls, new_cls))

    return changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_module_changes(
    module_name: str,
    old_fragment: list[dict[str, Any]],
    new_fragment: list[dict[str, Any]],
) -> list[Change]:
    """Classify all changes between two versions of a module's schema fragment.

    Args:
        module_name: Name of the module (for attribution in results).
        old_fragment: The old fragment (list of class/enum defs).
        new_fragment: The new fragment (list of class/enum defs).

    Returns:
        List of Change objects describing every detected change.
    """
    changes: list[Change] = []

    old_by_id = _by_id(old_fragment)
    new_by_id = _by_id(new_fragment)

    old_ids = set(old_by_id)
    new_ids = set(new_by_id)

    # Added classes
    for cid in sorted(new_ids - old_ids):
        changes.append(Change(
            module=module_name,
            kind="additive",
            description=f"New class '{cid}'",
        ))

    # Removed classes
    for cid in sorted(old_ids - new_ids):
        changes.append(Change(
            module=module_name,
            kind="breaking",
            description=f"Removed class '{cid}'",
        ))

    # Changed classes
    for cid in sorted(old_ids & new_ids):
        cls_changes = _classify_class_changes(cid, old_by_id[cid], new_by_id[cid])
        for c in cls_changes:
            c.module = module_name
        changes.extend(cls_changes)

    return changes


# ---------------------------------------------------------------------------
# Manifest-level change classification
# ---------------------------------------------------------------------------


def classify_manifest_changes(
    module_name: str,
    old_exports: list[str],
    new_exports: list[str],
) -> list[Change]:
    """Classify changes in the exports list (and other manifest metadata)."""
    changes: list[Change] = []

    added = set(new_exports) - set(old_exports)
    removed = set(old_exports) - set(new_exports)

    for name in sorted(added):
        changes.append(Change(
            module=module_name,
            kind="additive",
            description=f"Exports: added '{name}'",
        ))
    for name in sorted(removed):
        changes.append(Change(
            module=module_name,
            kind="breaking",
            description=f"Exports: removed '{name}'",
        ))

    return changes


# ---------------------------------------------------------------------------
# Diff composition: diff against a live instance
# ---------------------------------------------------------------------------


def diff_against_live(
    current_by_id: dict[str, dict[str, Any]],
    current_id_to_module: dict[str, str],
    fetched_schema: list[dict[str, Any]],
    default_module: str = "unknown",
    *,
    allow_extra_live_classes: bool = False,
) -> list[Change]:
    """Compare the current composed schema against a live-instance schema.

    This function assumes the database is exclusively managed by lms-schema
    (no external schema modifications).  Classes present in the live instance
    but absent in the composed schema are treated as BREAKING removals.

    When *allow_extra_live_classes* is True, live-only classes are downgraded
    to additive warnings ("extra live class") instead of breaking changes.
    This is useful when other tools may have created classes on the DB.

    Returns a list of Changes attributed to module names based on which module
    defines each @id in the current fragments. Removed classes (present in
    live, absent in current) get *default_module*.
    """
    fetched_by_id = _by_id(fetched_schema)
    changes: list[Change] = []

    current_ids = set(current_by_id)
    fetched_ids = set(fetched_by_id)

    for cid in sorted(current_ids - fetched_ids):
        mod = current_id_to_module.get(cid, default_module)
        changes.append(Change(module=mod, kind="additive", description=f"Class '{cid}' added (not in live instance)"))

    for cid in sorted(fetched_ids - current_ids):
        kind: Literal["additive", "breaking"] = "additive" if allow_extra_live_classes else "breaking"
        desc = (
            f"Class '{cid}' unexpected in live instance (not in composed schema)"
            if allow_extra_live_classes
            else f"Class '{cid}' removed (in live instance but not composed)"
        )
        changes.append(Change(module=default_module, kind=kind, description=desc))

    for cid in sorted(current_ids & fetched_ids):
        cls_changes = _classify_class_changes(cid, fetched_by_id[cid], current_by_id[cid])
        for c in cls_changes:
            mod = current_id_to_module.get(cid, default_module)
            c.module = mod
        changes.extend(cls_changes)

    return changes


# ---------------------------------------------------------------------------
# Guardrail check
# ---------------------------------------------------------------------------


def check_guardrails(
    module_name: str,
    changes: list[Change],
    old_version: Version,
    new_version: Version,
    baseline_migration_names: set[str],
    current_migration_names: set[str],
) -> list[str]:
    """Check semver and migration guardrails for a module.

    Returns a list of human-readable violation messages (empty = ok).
    """
    violations: list[str] = []

    has_breaking = any(c.kind == "breaking" for c in changes)

    major_bumped = new_version.major > old_version.major

    new_migrations = current_migration_names - baseline_migration_names

    # Version DOWNGRADE (new < old) — always a guardrail violation
    if new_version < old_version:
        violations.append(
            f"Module '{module_name}': version DOWNGRADE "
            f"{old_version} → {new_version} — not allowed"
        )
        # Downgrade subsumes other checks; return immediately
        return violations

    # Fragment changed but version not bumped at all
    if new_version == old_version and changes:
        violations.append(
            f"Module '{module_name}': fragment changed but version "
            f"not bumped (still {old_version})"
        )

    # Breaking changes without a MAJOR bump
    if has_breaking and not major_bumped:
        violations.append(
            f"Module '{module_name}': has BREAKING changes but version "
            f"only bumped {old_version} → {new_version} (MAJOR required)"
        )

    # Breaking changes + MAJOR bump but no migration
    if has_breaking and major_bumped and not new_migrations:
        violations.append(
            f"Module '{module_name}': has BREAKING changes and MAJOR bump "
            f"({old_version} → {new_version}) but no new migration file "
            f"(at least one new migration required)"
        )

    return violations
