"""lms-schema CLI — schema module composition and lifecycle management.

Subcommands (extensible):

    compose   — compose modules into a single schema + lock file
    diff      — compute diff, classify changes, and check guardrails
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .composer import compose, ComposerError
from .differ import (
    Change,
    classify_module_changes,
    classify_manifest_changes,
    check_guardrails,
    diff_against_live,
    _by_id,
)
from .manifest import Manifest
from .migrations import list_migrations
from .semver import Version


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------


def _cmd_compose(args: argparse.Namespace) -> int:
    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        return 1

    try:
        result = compose(modules_dir)
    except ComposerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write composed schema
    schema_path = out_dir / "composed.schema.json"
    schema_path.write_text(
        json.dumps(result.composed_schema, indent=2) + "\n"
    )

    # Write lock file
    lock: dict[str, dict[str, dict[str, str]]] = {"modules": {}}
    for info in result.modules:
        lock["modules"][info.name] = {
            "version": info.version,
            "checksum": info.checksum,
        }
    lock_path = out_dir / "modules.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")

    print(f"Composed {len(result.modules)} modules → {schema_path}")
    print(f"Lock file written → {lock_path}")
    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _load_lock(path: Path) -> dict[str, dict[str, str]]:
    """Load a modules.lock.json and return its modules dict."""
    if not path.is_file():
        print(f"Error: lock file '{path}' not found", file=sys.stderr)
        sys.exit(2)
    lock_data = json.loads(path.read_text())
    return lock_data.get("modules", {})


def _load_fragment(module_dir: Path) -> list[dict]:
    """Load a module's schema fragment (as a JSON list)."""
    schema_path = module_dir / "schema.json"
    if not schema_path.is_file():
        return []
    return json.loads(schema_path.read_text())


def _print_changes(changes: list[Change]) -> None:
    """Print a human-readable change report grouped by module."""
    by_module: dict[str, list[Change]] = {}
    for c in changes:
        by_module.setdefault(c.module, []).append(c)

    for mod in sorted(by_module):
        print(f"\n[{mod}]")
        for c in by_module[mod]:
            marker = "!" if c.kind == "breaking" else "+"
            print(f"  {marker} {c.description}")

    if not changes:
        print("(no changes)")


def _diff_fragments(
    current_modules_dir: Path,
    baseline_modules_dir: Path | None,
    baseline_lock: dict[str, dict[str, str]] | None,
) -> tuple[list[Change], list[str], list[str]]:
    """Compare current fragments against a baseline modules dir and/or lock.

    Returns (changes, all_guardrail_violations, warnings).
    """
    all_changes: list[Change] = []
    all_violations: list[str] = []
    all_warnings: list[str] = []

    # Discover current modules
    current_modules: dict[str, Manifest] = {}
    for subdir in sorted(current_modules_dir.iterdir(), key=lambda p: p.name):
        manifest_path = subdir / "manifest.json"
        if subdir.is_dir() and manifest_path.is_file():
            m = Manifest.load(subdir)
            current_modules[m.name] = m

    # Load current fragments and compute current checksums via composer
    # (we use the composer to get canonical checksums)
    try:
        result = compose(current_modules_dir)
    except ComposerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    current_checksums: dict[str, str] = {}
    for info in result.modules:
        current_checksums[info.name] = info.checksum

    # Load baseline modules if provided
    baseline_modules: dict[str, Manifest] = {}
    if baseline_modules_dir and baseline_modules_dir.is_dir():
        for subdir in sorted(baseline_modules_dir.iterdir(), key=lambda p: p.name):
            manifest_path = subdir / "manifest.json"
            if subdir.is_dir() and manifest_path.is_file():
                m = Manifest.load(subdir)
                baseline_modules[m.name] = m

    for name in current_modules:
        cur_manifest = current_modules[name]
        cur_ver = cur_manifest.version_obj
        cur_fragment = _load_fragment(cur_manifest.module_dir)

        baseline_ver: Version | None = None
        baseline_fragment: list[dict] | None = None
        baseline_exports: list[str] | None = None
        baseline_migrations: set[str] = set()

        if name in baseline_modules:
            bm = baseline_modules[name]
            baseline_ver = bm.version_obj
            baseline_fragment = _load_fragment(bm.module_dir)
            baseline_exports = bm.exports
            baseline_migrations = {mf.name for mf in list_migrations(bm.module_dir)}
        elif baseline_lock and name in baseline_lock:
            baseline_ver = Version.parse(baseline_lock[name]["version"])
            # No baseline modules dir, but we have the lock — fragments not available
            # for diffing, but we can still do guardrail checks
            baseline_fragment = None

        cur_migrations = {mf.name for mf in list_migrations(cur_manifest.module_dir)}

        # Classify schema changes
        if baseline_fragment is not None:
            changes = classify_module_changes(name, baseline_fragment, cur_fragment)
        else:
            changes = []

        # Classify manifest/export changes
        if baseline_exports is not None:
            changes.extend(classify_manifest_changes(name, baseline_exports, cur_manifest.exports))

        if changes:
            all_changes.extend(changes)

        # Compute what checksum was expected
        old_checksum = None
        if baseline_lock and name in baseline_lock:
            old_checksum = baseline_lock[name]["checksum"]

        new_checksum = current_checksums.get(name, "")

        # Guardrail: checksum changed but version unchanged
        if old_checksum and old_checksum != new_checksum:
            if baseline_ver is not None and baseline_ver == cur_ver:
                all_violations.append(
                    f"Module '{name}': checksum changed but version not bumped "
                    f"(still {cur_ver})"
                )

        # Only run guardrails when we have a baseline version
        if baseline_ver is not None:
            module_violations = check_guardrails(
                name,
                changes,
                baseline_ver,
                cur_ver,
                baseline_migrations,
                cur_migrations,
            )
            all_violations.extend(module_violations)

            # Warning: version bumped but no changes
            if not changes and baseline_ver != cur_ver:
                all_warnings.append(
                    f"Module '{name}': version bumped {baseline_ver} → {cur_ver} "
                    f"but no schema/export changes detected"
                )

    return all_changes, all_violations, all_warnings


async def _diff_live(
    current_modules_dir: Path,
    tdb_url: str,
    tdb_org: str,
    tdb_db: str,
    tdb_user: str,
    tdb_password: str,
    branch: str,
) -> list[Change]:
    """Compare the composed schema against a live TerminusDB instance."""
    # Lazy import — only when networking is actually requested
    from lms_core.tdb import TdbClient

    # Build the composed schema and compute id-to-module mapping
    try:
        result = compose(current_modules_dir)
    except ComposerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    # Build current_by_id and id_to_module maps
    current_by_id = _by_id(result.composed_schema)
    id_to_module: dict[str, str] = {}

    for info in result.modules:
        # Reload each module's fragment to build the mapping
        mod_dir = current_modules_dir / info.name
        fragment = _load_fragment(mod_dir)
        for cls in fragment:
            cid = cls.get("@id")
            if isinstance(cid, str) and cls.get("@type") != "@context":
                id_to_module[cid] = info.name

    async with TdbClient(
        base_url=tdb_url,
        org=tdb_org,
        db=tdb_db,
        user=tdb_user,
        password=tdb_password,
    ) as client:
        fetched = await client.get_schema(branch=branch)

    return diff_against_live(current_by_id, id_to_module, fetched)


def _cmd_diff(args: argparse.Namespace) -> int:
    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        return 2

    all_guardrail_violations: list[str] = []
    all_warnings: list[str] = []
    had_any_changes = False

    # --- Fragment-based diff ---
    baseline_lock: dict[str, dict[str, str]] | None = None
    baseline_modules_dir: Path | None = None

    if args.baseline_lock:
        baseline_lock = _load_lock(Path(args.baseline_lock))

    if args.baseline_modules:
        baseline_modules_dir = Path(args.baseline_modules)

    if baseline_lock is not None or baseline_modules_dir is not None:
        print("=== Fragment diff (baseline comparison) ===")
        changes, violations, warnings = _diff_fragments(
            modules_dir, baseline_modules_dir, baseline_lock
        )
        _print_changes(changes)
        all_guardrail_violations.extend(violations)
        all_warnings.extend(warnings)
        if changes:
            had_any_changes = True

    # --- Live-instance diff ---
    if args.tdb_url:
        print("\n=== Live instance diff ===")
        try:
            live_changes = asyncio.run(_diff_live(
                modules_dir,
                args.tdb_url,
                args.tdb_org,
                args.tdb_db,
                args.tdb_user,
                args.tdb_password,
                args.branch,
            ))
        except Exception as exc:
            print(f"Error fetching live schema: {exc}", file=sys.stderr)
            return 2

        _print_changes(live_changes)
        if live_changes:
            had_any_changes = True

    # --- Warnings ---
    if all_warnings:
        print("\n--- Warnings ---")
        for w in all_warnings:
            print(f"  ⚠  {w}")

    # --- Guardrail violations ---
    if all_guardrail_violations:
        print("\n--- Guardrail violations ---")
        for v in all_guardrail_violations:
            print(f"  ✗  {v}")
        return 2

    if had_any_changes:
        print("\n✓  Changes detected, all guardrails satisfied.")
        return 1

    print("\n✓  No changes detected.")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lms-schema",
        description="LMS Schema Module System CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # compose
    p_compose = sub.add_parser("compose", help="Compose modules into a single schema")
    p_compose.add_argument(
        "--modules-dir",
        default="schema/modules",
        help="Directory containing module sub-directories (default: schema/modules)",
    )
    p_compose.add_argument(
        "--out-dir",
        default="build",
        help="Output directory for composed schema and lock file (default: build)",
    )

    # diff
    p_diff = sub.add_parser("diff", help="Diff modules and check guardrails")
    p_diff.add_argument(
        "--modules-dir",
        default="schema/modules",
        help="Directory containing module sub-directories (default: schema/modules)",
    )
    p_diff.add_argument(
        "--baseline-modules",
        default=None,
        help="Path to baseline modules directory (e.g., a git worktree / older checkout)",
    )
    p_diff.add_argument(
        "--baseline-lock",
        default=None,
        help="Path to baseline modules.lock.json (e.g., from git HEAD)",
    )
    # Live instance
    p_diff.add_argument("--tdb-url", default=None)
    p_diff.add_argument("--tdb-org", default=None)
    p_diff.add_argument("--tdb-db", default=None)
    p_diff.add_argument("--tdb-user", default=None)
    p_diff.add_argument("--tdb-password", default=None)
    p_diff.add_argument("--branch", default="main")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "compose":
        sys.exit(_cmd_compose(args))
    elif args.command == "diff":
        sys.exit(_cmd_diff(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
