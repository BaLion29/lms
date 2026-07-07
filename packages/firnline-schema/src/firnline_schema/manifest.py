"""Manifest loading and validation for schema modules.

A manifest.json describes a schema module: its name, version, what it
depends on, what classes it exports, a human-readable description, and
where generated models should be written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import SchemaError
from .semver import Version, Range, VersionError, RangeError

# Must be a non-empty dotted Python module path like "a.b.c" —
# not "a", not "a..b".
_MODELS_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


class ManifestError(SchemaError):
    """Raised when a manifest is malformed or references are broken."""


class Manifest:
    """Parsed representation of a module's manifest.json."""

    __slots__ = ("name", "version", "version_obj", "depends_on", "exports", "description", "models_target", "models_import", "module_dir")

    def __init__(
        self,
        name: str,
        version: str,
        depends_on: list[dict[str, str]],
        exports: list[str],
        description: str,
        models_target: str,
        module_dir: Path,
        models_import: str | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.version_obj = Version.parse(version)
        self.depends_on = depends_on
        self.exports = exports
        self.description = description
        self.models_target = models_target
        self.models_import = models_import if models_import is not None else models_target
        self.module_dir = module_dir

    @classmethod
    def load(cls, module_dir: Path) -> "Manifest":
        """Load and validate a manifest from *module_dir*/manifest.json."""
        manifest_path = module_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ManifestError(f"Missing manifest.json in {module_dir}")
        try:
            raw = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Invalid JSON in {manifest_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ManifestError(f"{manifest_path}: manifest must be a JSON object")

        # name (required, string)
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError(f"{manifest_path}: 'name' must be a non-empty string")

        # version (required, semver string)
        version = raw.get("version")
        if not isinstance(version, str):
            raise ManifestError(f"{manifest_path}: 'version' must be a string")
        try:
            Version.parse(version)
        except VersionError as exc:
            raise ManifestError(f"{manifest_path}: {exc}") from exc

        # depends_on (required, list of {name, range})
        depends_on = raw.get("depends_on")
        if not isinstance(depends_on, list):
            raise ManifestError(f"{manifest_path}: 'depends_on' must be a list")
        for i, dep in enumerate(depends_on):
            if not isinstance(dep, dict):
                raise ManifestError(f"{manifest_path}: depends_on[{i}] must be an object")
            dname = dep.get("name")
            if not isinstance(dname, str) or not dname:
                raise ManifestError(f"{manifest_path}: depends_on[{i}].name must be a non-empty string")
            drange = dep.get("range")
            if not isinstance(drange, str):
                raise ManifestError(f"{manifest_path}: depends_on[{i}].range must be a string")
            try:
                Range(drange)
            except RangeError as exc:
                raise ManifestError(f"{manifest_path}: depends_on[{i}].range invalid: {exc}") from exc

        # exports (required, list of strings)
        exports = raw.get("exports")
        if not isinstance(exports, list):
            raise ManifestError(f"{manifest_path}: 'exports' must be a list")
        for i, ex in enumerate(exports):
            if not isinstance(ex, str):
                raise ManifestError(f"{manifest_path}: exports[{i}] must be a string")

        # description (required, string)
        description = raw.get("description")
        if not isinstance(description, str):
            raise ManifestError(f"{manifest_path}: 'description' must be a string")

        # models_target (required, non-empty dotted Python module path)
        models_target = raw.get("models_target")
        if not isinstance(models_target, str) or not _MODELS_TARGET_RE.match(models_target):
            raise ManifestError(
                f"{manifest_path}: 'models_target' must be a non-empty dotted Python "
                f"module path (e.g. 'firnline_core.generated.core')"
            )

        # models_import (optional, defaults to models_target)
        # The module path OTHER packages use to import this module's generated classes.
        models_import = raw.get("models_import")
        if models_import is not None:
            if not isinstance(models_import, str) or not _MODELS_TARGET_RE.match(models_import):
                raise ManifestError(
                    f"{manifest_path}: 'models_import' must be a non-empty dotted Python "
                    f"module path (e.g. 'firnline_core.models')"
                )

        return cls(
            name=name,
            version=version,
            depends_on=depends_on,
            exports=exports,
            description=description,
            models_target=models_target,
            module_dir=module_dir,
            models_import=models_import,
        )

    def _inject_core_dep(self) -> None:
        """Ensure core is an implicit dependency (if not already listed).

        Core is never added to depends_on for core itself.
        """
        if self.name == "core":
            return
        names = {d["name"] for d in self.depends_on}
        if "core" not in names:
            self.depends_on = [{"name": "core", "range": ">=0.1.0"}] + self.depends_on

    @property
    def dep_names(self) -> set[str]:
        """Set of dependency module names."""
        return {d["name"] for d in self.depends_on}

    def __repr__(self) -> str:
        return f"Manifest(name={self.name!r}, version={self.version!r})"
