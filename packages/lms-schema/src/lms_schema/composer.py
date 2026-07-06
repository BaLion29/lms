"""Schema module composer: topo-sort, validate, assemble.

Checksums use the canonical form:

    sha256(json.dumps(fragment_array, sort_keys=True, separators=(",", ":")))

which is deterministic for a given fragment.
"""

from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import Manifest, ManifestError
from .semver import Range


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class ComposerError(Exception):
    """Base for all composition errors."""


class CycleError(ComposerError):
    """A dependency cycle was detected."""


class L1Error(ComposerError):
    """L1 law violation — only core defines abstracts / @context."""


class L2Error(ComposerError):
    """L2 law violation — reference to an unreachable class."""


class DuplicateIdError(ComposerError):
    """Duplicate @id across modules."""


class DepMismatchError(ComposerError):
    """A dependency version does not satisfy the declared range."""


# ---------------------------------------------------------------------------
# Canonical serialization helpers
# ---------------------------------------------------------------------------


def _canonical_json(obj: Any) -> str:
    """Return the canonical (deterministic) JSON string for *obj*."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _canonical_json_bytes(obj: Any) -> bytes:
    return _canonical_json(obj).encode()


def _sha256(obj: Any) -> str:
    """Return the sha256 hex digest of the canonical JSON serialization of *obj*."""
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ModuleInfo:
    name: str
    version: str
    checksum: str


@dataclass
class ComposeResult:
    modules: list[ModuleInfo]
    composed_schema: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compose(modules_dir: Path) -> ComposeResult:
    """Compose all schema modules under *modules_dir* into a single schema.

    Steps:

    1.  Load every sub-directory that contains a ``manifest.json``.
    2.  Validate manifests and inject implicit ``core`` dependency.
    3.  Resolve dependency graph; range-check declared dep ranges;
        topological sort (deterministic tie-break: alphabetical);
        cycle detection.
    4.  Run L1 and L2 validations; check for duplicate ``@id``.
    5.  Assemble the composed schema and compute per-module checksums.
    """
    # ── 1. Load modules ──────────────────────────────────────────────
    modules: dict[str, Manifest] = {}
    for subdir in sorted(modules_dir.iterdir(), key=lambda p: p.name):
        manifest_path = subdir / "manifest.json"
        if subdir.is_dir() and manifest_path.is_file():
            manifest = Manifest.load(subdir)
            if manifest.name in modules:
                raise ManifestError(f"Duplicate module name: {manifest.name}")
            modules[manifest.name] = manifest

    if not modules:
        raise ComposerError(f"No modules found in {modules_dir}")

    # ── 2. Inject implicit core dependency ───────────────────────────
    for m in modules.values():
        m._inject_core_dep()

    # ── 3. Dependency range checks ───────────────────────────────────
    for name, m in modules.items():
        for dep in m.depends_on:
            dname = dep["name"]
            if dname not in modules:
                raise DepMismatchError(
                    f"Module '{name}' depends on unknown module '{dname}'"
                )
            dep_ver = modules[dname].version_obj
            rng = Range(dep["range"])
            if not rng.contains(dep_ver):
                raise DepMismatchError(
                    f"Module '{name}' requires {dname} {dep['range']} "
                    f"but found version {dep_ver}"
                )

    # ── 4. Topological sort (Kahn's algorithm, alphabetical tie-break)
    order = _topo_sort(modules)

    # ── 5. Load definitions & validate ───────────────────────────────
    _validate_all(modules, order)

    # ── 6. Assemble composed schema + checksums ──────────────────────
    return _assemble(modules, order)


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def _topo_sort(modules: dict[str, Manifest]) -> list[str]:
    """Return module names in topological order.

    Detects cycles and raises ``CycleError`` naming the cycle.
    Tie-breaks alphabetically when multiple nodes are ready.
    """
    in_degree: dict[str, int] = {name: 0 for name in modules}
    edges: dict[str, list[str]] = {name: [] for name in modules}

    for name, m in modules.items():
        for dep in m.depends_on:
            dname = dep["name"]
            edges[dname].append(name)
            in_degree[name] += 1

    # Queue of ready nodes, kept sorted for determinism
    ready: list[str] = sorted(name for name, deg in in_degree.items() if deg == 0)
    order: list[str] = []

    while ready:
        # Pop deterministically: sorted list → first element
        node = ready.pop(0)
        order.append(node)
        for nxt in sorted(edges[node]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                ready.append(nxt)
                ready.sort()

    if len(order) != len(modules):
        # Find remaining nodes → cycle
        remaining = set(modules) - set(order)
        cycle = _find_cycle(remaining, edges)
        raise CycleError(f"Cycle detected: {' → '.join(cycle)}")

    return order


def _find_cycle(nodes: set[str], edges: dict[str, list[str]]) -> list[str]:
    """Find one cycle among *nodes* using DFS."""
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(v: str) -> list[str] | None:
        visited.add(v)
        stack.append(v)
        for nxt in edges.get(v, []):
            if nxt not in nodes:
                continue
            if nxt in stack:
                # Found a cycle
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if nxt not in visited:
                result = dfs(nxt)
                if result:
                    return result
        stack.pop()
        return None

    for node in sorted(nodes):
        if node not in visited:
            result = dfs(node)
            if result:
                return result
    return list(nodes)  # fallback


# ---------------------------------------------------------------------------
# Validation (L1 + L2 + duplicate @id)
# ---------------------------------------------------------------------------


def _validate_all(modules: dict[str, Manifest], order: list[str]) -> None:
    """Run all validations on the loaded modules."""
    # Build class → defining-module-name map
    class_to_module: dict[str, str] = {}
    all_classes_per_module: dict[str, list[dict[str, Any]]] = {}

    for name in order:
        m = modules[name]
        schema_path = m.module_dir / "schema.json"
        if not schema_path.is_file():
            raise ComposerError(f"Missing schema.json in {m.module_dir}")
        classes: list[dict[str, Any]] = json.loads(schema_path.read_text())
        if not isinstance(classes, list):
            raise ComposerError(f"{schema_path}: must be a JSON array")
        all_classes_per_module[name] = classes

        for cls in classes:
            # @context items are not class definitions and have no @id
            if cls.get("@type") == "@context":
                continue
            cid = cls.get("@id")
            if not isinstance(cid, str):
                raise ComposerError(f"Class without @id in module '{name}'")
            if cid in class_to_module:
                raise DuplicateIdError(
                    f"Duplicate @id '{cid}' in modules '{class_to_module[cid]}' and '{name}'"
                )
            class_to_module[cid] = name

    # L1: only core may have @abstract classes or @context
    _validate_l1(modules, all_classes_per_module)

    # L2: reference traversal
    _validate_l2(modules, all_classes_per_module, class_to_module)


def _validate_l1(
    modules: dict[str, Manifest],
    all_classes: dict[str, list[dict[str, Any]]],
) -> None:
    """L1: Only core may define @abstract classes or @context."""
    for name, classes in all_classes.items():
        if name == "core":
            continue
        for cls in classes:
            if "@abstract" in cls:
                raise L1Error(
                    f"Module '{name}' defines abstract class '{cls.get('@id')}'. "
                    "Only 'core' may define abstract classes (L1)."
                )
            if cls.get("@type") == "@context":
                raise L1Error(
                    f"Module '{name}' provides a @context block. "
                    "Only 'core' may provide @context (L1)."
                )


_XSD_XDD = {"xsd", "xdd"}


def _is_builtin(name: str) -> bool:
    """Return True if *name* is an xsd: or xdd: primitive or a plain type keyword."""
    if ":" in name:
        prefix = name.split(":", 1)[0]
        return prefix in _XSD_XDD
    return False


def _extract_refs(cls: dict[str, Any]) -> list[str]:
    """Return every class/enum name referenced by *cls*.

    Walks ``@inherits``, ``@oneOf``, and every property value
    (string-typed properties and ``{"@class": ..., "@type": ...}`` wrappers).
    """
    refs: list[str] = []

    # @inherits → string or list of strings
    inherits = cls.get("@inherits")
    if inherits is not None:
        if isinstance(inherits, str):
            refs.append(inherits)
        elif isinstance(inherits, list):
            for item in inherits:
                if isinstance(item, str):
                    refs.append(item)

    # @oneOf → dict of class refs
    oneof = cls.get("@oneOf")
    if isinstance(oneof, dict):
        for v in oneof.values():
            if isinstance(v, str):
                refs.append(v)

    # Regular properties (non-@ keys, skip known meta keys)
    META_KEYS = {
        "@id", "@type", "@inherits", "@abstract", "@subdocument",
        "@key", "@oneOf", "@value",
    }
    for key, val in cls.items():
        if key in META_KEYS:
            continue
        if isinstance(val, str):
            refs.append(val)
        elif isinstance(val, dict):
            class_val = val.get("@class")
            if isinstance(class_val, str):
                refs.append(class_val)

    return refs


def _validate_l2(
    modules: dict[str, Manifest],
    all_classes: dict[str, list[dict[str, Any]]],
    class_to_module: dict[str, str],
) -> None:
    """L2: every reference must be to a reachable class."""
    # Precompute export + own-class sets per module
    module_exports: dict[str, set[str]] = {}
    module_own: dict[str, set[str]] = {}
    for name, classes in all_classes.items():
        owns = {cls["@id"] for cls in classes if "@id" in cls and cls.get("@type") != "@context"}
        module_own[name] = owns
        module_exports[name] = set(modules[name].exports)

    for name, classes in all_classes.items():
        deps = modules[name].depends_on
        dep_names = {d["name"] for d in deps}

        # Set of class names reachable via declared dependencies
        reachable: set[str] = set()
        reachable |= module_own.get(name, set())

        # Core is always reachable (explicitly listed in depends_on after injection)
        if "core" in dep_names:
            reachable |= module_own.get("core", set())

        for dep in deps:
            dname = dep["name"]
            reachable |= module_exports.get(dname, set())

        for cls in classes:
            cid = cls.get("@id", "?")
            for ref in _extract_refs(cls):
                if _is_builtin(ref):
                    continue
                if ref in reachable:
                    continue
                # Determine why it failed
                if ref in class_to_module:
                    ref_mod = class_to_module[ref]
                    raise L2Error(
                        f"Module '{name}' class '{cid}' references '{ref}' "
                        f"(defined in module '{ref_mod}'), but '{ref_mod}' "
                        f"is not a dependency of '{name}' and does not export '{ref}'"
                    )
                raise L2Error(
                    f"Module '{name}' class '{cid}' references unknown class '{ref}'"
                )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _assemble(
    modules: dict[str, Manifest],
    order: list[str],
) -> ComposeResult:
    """Build the composed schema and compute checksums."""
    # Load @context from core
    core_dir = modules["core"].module_dir
    context_path = core_dir / "context.json"
    if not context_path.is_file():
        raise ComposerError("core module is missing context.json")
    context: dict[str, Any] = json.loads(context_path.read_text())

    # Collect classes in order
    composed: list[dict[str, Any]] = [context]
    infos: list[ModuleInfo] = []

    for name in order:
        m = modules[name]
        schema_path = m.module_dir / "schema.json"
        classes: list[dict[str, Any]] = json.loads(schema_path.read_text())

        # Checksum over the canonical fragment (the raw array, not re-sorted)
        checksum = _sha256(classes)
        infos.append(ModuleInfo(name=name, version=m.version, checksum=checksum))

        # Sort classes by @id for deterministic composed output
        classes_sorted = sorted(classes, key=lambda c: c.get("@id", ""))
        composed.extend(classes_sorted)

    return ComposeResult(modules=infos, composed_schema=composed)
