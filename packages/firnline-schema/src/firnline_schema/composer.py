"""Schema module composer: topo-sort, validate, assemble.

Modules are discovered from two sources (merged):

1. **Repo tree** — sub-directories under *modules_dir* that contain a
   ``manifest.json``.  Origin = ``repo:<name>``.

2. **Entry points** — the ``firnline.schema_modules`` group (see
   :mod:`firnline_schema.discovery`).  Each entry-point value resolves to a
   directory containing ``manifest.json`` + ``schema.json``.  Origin =
   ``pkg:<dist-name>==<dist-version>``.

Duplicate module names across sources produce a hard error naming both
origins.  All validation (L1/L2, exports, duplicate @id, topo, checksums)
applies uniformly to every module regardless of source.

Checksums use the canonical form:

    sha256(json.dumps(fragment_array, sort_keys=True, separators=(",", ":")))

which is deterministic for a given fragment.
"""

from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from . import SchemaError
from .manifest import Manifest, ManifestError
from .semver import Range

if TYPE_CHECKING:
    from .discovery import ModuleSource


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class ComposerError(SchemaError):
    """Base for all composition errors."""


class CycleError(ComposerError):
    """A dependency cycle was detected."""


class L1Error(ComposerError):
    """L1 law violation — only @context is core-exclusive."""


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
    source: str | None = None  # "repo:<name>" or "pkg:<dist>==<version>"


@dataclass
class ComposeResult:
    modules: list[ModuleInfo]
    composed_schema: list[dict[str, Any]]
    class_id_to_module: dict[str, str]  # @id → module name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fragment_checksum(fragment_array: list[dict[str, Any]]) -> str:
    """Return the canonical checksum for a schema fragment.

    Canonical form: sha256(json.dumps(array, sort_keys=True, separators=(",", ":")))
    """
    return _sha256(fragment_array)


def compose(
    modules_dir: Path,
    *,
    include_entry_points: bool = True,
    entry_point_modules: dict[str, ModuleSource] | None = None,
) -> ComposeResult:
    """Compose all schema modules (repo + entry points) into a single schema.

    Args:
        modules_dir: Root directory of repo-tree modules.
        include_entry_points: When ``True`` (default), also discover modules
            from installed ``firnline.schema_modules`` entry points.
        entry_point_modules: Injection seam for tests.  When ``None``,
            :func:`~firnline_schema.discovery.discover_module_dirs` is called;
            pass ``{}`` to bypass discovery without disabling the flag.

    Steps:

    1.  Load repo sub-directories; discover entry-point modules.
    2.  Merge sources — duplicate NAME → hard error naming both origins.
    3.  Validate manifests and inject implicit ``core`` dependency.
    4.  Resolve dependency graph; range-check declared dep ranges;
        topological sort (deterministic tie-break: alphabetical);
        cycle detection.
    5.  Run L1 and L2 validations; check for duplicate ``@id``.
    6.  Assemble the composed schema and compute per-module checksums.
    """
    modules: dict[str, Manifest] = {}
    module_sources: dict[str, str] = {}

    # ── 1a. Load repo-tree modules ──────────────────────────────────
    for subdir in sorted(modules_dir.iterdir(), key=lambda p: p.name):
        manifest_path = subdir / "manifest.json"
        if subdir.is_dir() and manifest_path.is_file():
            manifest = Manifest.load(subdir)
            if manifest.name in modules:
                raise ManifestError(f"Duplicate module name: {manifest.name}")
            modules[manifest.name] = manifest
            module_sources[manifest.name] = f"repo:{manifest.name}"

    # ── 1b. Load entry-point modules ────────────────────────────────
    if include_entry_points:
        if entry_point_modules is None:
            from .discovery import discover_module_dirs
            ep_modules = discover_module_dirs()
        else:
            ep_modules = entry_point_modules

        for ms in ep_modules.values():
            if ms.name in modules:
                raise ComposerError(
                    f"Duplicate module name '{ms.name}' across sources: "
                    f"{module_sources[ms.name]} and {ms.origin}"
                )
            manifest = Manifest.load(ms.path)
            if manifest.name != ms.name:
                raise ComposerError(
                    f"Entry-point module name mismatch: "
                    f"entry point '{ms.name}', manifest '{manifest.name}'"
                )
            modules[ms.name] = manifest
            module_sources[ms.name] = ms.origin

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
    all_classes, class_to_module = _validate_all(modules, order)

    # ── 6. Assemble composed schema + checksums ──────────────────────
    return _assemble(modules, order, all_classes, class_to_module, module_sources)


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
    """Find one cycle among *nodes* using DFS.

    Uses ``stack`` to track the current DFS path: when we encounter a neighbour
    that is already on the stack we have found a back-edge, which identifies a
    cycle.  ``visited`` prevents re-exploring subtrees that are already known
    to be cycle-free (or whose cycles have already been reported).
    """
    visited: set[str] = set()
    stack: list[str] = []  # current DFS path (node is on the path iff it is in stack)

    def dfs(v: str) -> list[str] | None:
        visited.add(v)
        stack.append(v)               # enter node
        for nxt in edges.get(v, []):
            if nxt not in nodes:
                continue
            if nxt in stack:
                # Back-edge found — extract the cycle slice from stack
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if nxt not in visited:
                result = dfs(nxt)
                if result:
                    return result
        stack.pop()                    # exit node — no cycle reachable through v
        return None

    for node in sorted(nodes):
        if node not in visited:
            result = dfs(node)
            if result:
                return result
    return list(nodes)  # fallback (should not be reached)


# ---------------------------------------------------------------------------
# Validation (L1 + L2 + duplicate @id)
# ---------------------------------------------------------------------------


def _validate_all(
    modules: dict[str, Manifest], order: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Run all validations on the loaded modules.

    Returns (per_module_classes, class_id_to_module_name).
    """
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

    # Validate exports: every exported @id must be defined in that module
    for name in order:
        m = modules[name]
        classes = all_classes_per_module[name]
        own_ids: set[str] = {
            cls["@id"]
            for cls in classes
            if "@id" in cls and cls.get("@type") != "@context"
        }
        for export_id in m.exports:
            if export_id not in own_ids:
                raise ComposerError(
                    f"Module '{name}' exports '@id' '{export_id}' "
                    f"which is not defined in its schema.json"
                )

    # L1: only core may have @abstract classes or @context
    _validate_l1(modules, all_classes_per_module)

    # L2: reference traversal
    _validate_l2(modules, all_classes_per_module, class_to_module)

    return all_classes_per_module, class_to_module


def _validate_l1(
    modules: dict[str, Manifest],
    all_classes: dict[str, list[dict[str, Any]]],
) -> None:
    """L1: core owns @context, registry classes, and contentless universal markers.

    Other modules MAY define abstract classes (the spec permits it for e.g.
    the triggers module owning the abstract ``Trigger`` class).
    """
    for name, classes in all_classes.items():
        for cls in classes:
            # @context: forbidden in ALL modules (core's context lives in context.json)
            if cls.get("@type") == "@context":
                raise L1Error(
                    f"Module '{name}' contains a @context block in schema.json. "
                    "@context must live only in core's context.json (L1)."
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

    # @oneOf → dict mapping prop-name → class-ref, list of wrapper-dicts, or a wrapper-dict
    oneof = cls.get("@oneOf")
    if isinstance(oneof, dict):
        for v in oneof.values():
            if isinstance(v, str):
                refs.append(v)
            elif isinstance(v, dict):
                # wrapper-dict value: walk with same logic
                refs.extend(_extract_refs(v))
    elif isinstance(oneof, list):
        for item in oneof:
            if isinstance(item, str):
                refs.append(item)
            elif isinstance(item, dict):
                refs.extend(_extract_refs(item))

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
            elif isinstance(class_val, dict):
                # Nested wrapper (e.g. Set → Optional → X):
                # recurse into the inner dict to find its @class
                refs.extend(_extract_refs(class_val))

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
    all_classes: dict[str, list[dict[str, Any]]],
    class_to_module: dict[str, str],
    module_sources: dict[str, str] | None = None,
) -> ComposeResult:
    """Build the composed schema and compute checksums.

    *all_classes* is the per-module parsed schema.json arrays (already
    loaded and validated) to avoid re-reading files.

    *module_sources* maps module name → origin string (``repo:...`` or
    ``pkg:...``).  When ``None``, ``ModuleInfo.source`` is left as ``None``.
    """
    # Load @context from core
    core_dir = modules["core"].module_dir
    context_path = core_dir / "context.json"
    if not context_path.is_file():
        raise ComposerError("core module is missing context.json")
    context: dict[str, Any] = json.loads(context_path.read_text())

    # Collect classes in order
    composed: list[dict[str, Any]] = [context]
    infos: list[ModuleInfo] = []

    sources = module_sources or {}

    for name in order:
        m = modules[name]
        classes = all_classes[name]

        # Checksum over the canonical fragment (the raw array, not re-sorted)
        checksum = fragment_checksum(classes)
        infos.append(ModuleInfo(
            name=name,
            version=m.version,
            checksum=checksum,
            source=sources.get(name),
        ))

        # Sort classes by @id for deterministic composed output
        classes_sorted = sorted(classes, key=lambda c: c.get("@id", ""))
        composed.extend(classes_sorted)

    return ComposeResult(modules=infos, composed_schema=composed, class_id_to_module=class_to_module)
