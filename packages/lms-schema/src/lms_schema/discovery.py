"""Schema module discovery via ``lms.schema_modules`` entry points.

Each entry point in the ``lms.schema_modules`` group points to a directory
containing ``manifest.json`` + ``schema.json`` (+ optional ``migrations/``,
and ``context.json`` only for core).  The entry point value must resolve to:

(a) a ``str`` or ``os.PathLike`` attribute holding the module directory path, or
(b) a package/module object — ``importlib.resources.files(obj)`` is used.

The entry point **name** must equal the module's ``manifest.json`` ``name``.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import os
from dataclasses import dataclass
from pathlib import Path

from . import SchemaError
from .manifest import Manifest


# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------


class DiscoveryError(SchemaError):
    """Aggregated entry-point discovery errors (all collected before raising)."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleSource:
    """Resolved location of a schema module.

    Attributes:
        name: Module name (matches entry-point name and manifest name).
        path: Directory containing ``manifest.json`` + ``schema.json``.
        origin: ``repo:<relpath>`` or ``pkg:<dist-name>==<dist-version>``.
    """

    name: str
    path: Path
    origin: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_path(obj: object) -> Path:
    """Convert an entry-point loaded object to a directory path.

    (a) str/os.PathLike → Path(obj)
    (b) module/package  → importlib.resources.files(obj)
    """
    if isinstance(obj, (str, os.PathLike)):
        return Path(obj)
    # Fallback: treat as module/package
    return Path(importlib.resources.files(obj))  # type: ignore[arg-type]


def discover_module_dirs() -> dict[str, ModuleSource]:
    """Discover schema modules from installed ``lms.schema_modules`` entry points.

    Returns:
        Dict mapping module name → ``ModuleSource``.

    Raises:
        DiscoveryError: When any entry point cannot be resolved or validated.
        *All* errors are collected and reported together — a broken extension
        is never silently ignored.
    """
    errors: list[str] = []
    result: dict[str, ModuleSource] = {}

    eps = importlib.metadata.entry_points(group="lms.schema_modules")
    for ep in eps:
        # ── Load the entry point object ──────────────────────────
        try:
            obj = ep.load()
        except Exception as exc:
            errors.append(
                f"Failed to load entry point '{ep.name}': "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # ── Resolve to directory path ────────────────────────────
        try:
            path = _resolve_path(obj)
        except Exception as exc:
            errors.append(
                f"Failed to resolve path for entry point '{ep.name}': "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # ── Validate manifest matches entry-point name ───────────
        try:
            manifest = Manifest.load(path)
        except Exception as exc:
            errors.append(
                f"Failed to load manifest for entry point '{ep.name}' "
                f"({path}): {type(exc).__name__}: {exc}"
            )
            continue

        if manifest.name != ep.name:
            errors.append(
                f"Entry point name '{ep.name}' does not match "
                f"manifest name '{manifest.name}' ({path})"
            )
            continue

        # ── Build origin string ──────────────────────────────────
        dist = ep.dist
        if dist is not None and dist.version is not None:
            origin = f"pkg:{dist.name}=={dist.version}"
        elif dist is not None:
            origin = f"pkg:{dist.name}"
        else:
            origin = f"pkg:{ep.name}"

        result[ep.name] = ModuleSource(name=ep.name, path=path, origin=origin)

    if errors:
        raise DiscoveryError(
            "Schema module entry-point discovery failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return result
