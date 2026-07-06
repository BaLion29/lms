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
from typing import TYPE_CHECKING

from . import SchemaError
from .composer import compose
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

if TYPE_CHECKING:
    from .applier import ActionPlan


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------


def _cmd_compose(args: argparse.Namespace) -> int:
    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        return 1

    kwargs = {}
    if args.no_entry_points:
        kwargs["include_entry_points"] = False

    try:
        result = compose(modules_dir, **kwargs)
    except SchemaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write composed schema
    schema_path = out_dir / "composed.schema.json"
    schema_path.write_text(
        json.dumps(result.composed_schema, indent=2) + "\n"
    )

    # Write lock file (with optional source field)
    lock: dict[str, dict[str, dict[str, str]]] = {"modules": {}}
    for info in result.modules:
        entry: dict[str, str] = {
            "version": info.version,
            "checksum": info.checksum,
        }
        if info.source is not None:
            entry["source"] = info.source
        lock["modules"][info.name] = entry
    lock_path = out_dir / "modules.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")

    # Write meta file (class → module mapping, sorted for determinism)
    meta: dict[str, dict[str, str]] = {
        "classes": dict(sorted(result.class_id_to_module.items())),
    }
    meta_path = out_dir / "composed.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")

    print(f"Composed {len(result.modules)} modules → {schema_path}")
    print(f"Lock file written → {lock_path}")
    print(f"Meta file written → {meta_path}")
    return 0


# ---------------------------------------------------------------------------
# codegen
# ---------------------------------------------------------------------------


def _cmd_codegen(args: argparse.Namespace) -> int:
    composed_path = Path(args.composed)
    meta_path = Path(args.meta)

    if not composed_path.is_file():
        print(
            f"Error: composed schema not found at '{composed_path}'.\n"
            f"  Run 'lms-schema compose' first to generate it.",
            file=sys.stderr,
        )
        return 1

    if not meta_path.is_file():
        print(
            f"Error: composed meta not found at '{meta_path}'.\n"
            f"  Run 'lms-schema compose' first to generate it.",
            file=sys.stderr,
        )
        return 1

    composed_schema = json.loads(composed_path.read_text())
    meta = json.loads(meta_path.read_text())
    class_id_to_module = meta.get("classes", {})

    from .codegen import schema_checksum, write_generated

    checksum = schema_checksum(composed_schema)
    out_dir = Path(args.out)

    paths = write_generated(out_dir, composed_schema, class_id_to_module, checksum)

    print(f"Generated {len(paths)} files → {out_dir}")
    for p in paths:
        print(f"  {p.name}")
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
    *,
    include_entry_points: bool = True,
) -> tuple[list[Change], list[str], list[str]]:
    """Compare current fragments against a baseline modules dir and/or lock.

    Returns (changes, all_guardrail_violations, warnings).
    """
    all_changes: list[Change] = []
    all_violations: list[str] = []
    all_warnings: list[str] = []

    # Discover current modules (repo-tree)
    current_modules: dict[str, Manifest] = {}
    for subdir in sorted(current_modules_dir.iterdir(), key=lambda p: p.name):
        manifest_path = subdir / "manifest.json"
        if subdir.is_dir() and manifest_path.is_file():
            m = Manifest.load(subdir)
            current_modules[m.name] = m

    # Discover entry-point modules
    ep_module_paths: dict[str, Path] = {}
    if include_entry_points:
        try:
            from .discovery import discover_module_dirs
            for ms in discover_module_dirs().values():
                if ms.name not in current_modules:
                    m = Manifest.load(ms.path)
                    if m.name != ms.name:
                        all_warnings.append(
                            f"Entry-point module name mismatch: "
                            f"'{ms.name}' vs manifest '{m.name}' — skipping"
                        )
                        continue
                    current_modules[m.name] = m
                    ep_module_paths[m.name] = ms.path
        except SchemaError as exc:
            all_warnings.append(f"Entry-point discovery failed: {exc}")

    # Load current fragments and compute current checksums via composer
    # (we use the composer to get canonical checksums)
    try:
        result = compose(current_modules_dir, include_entry_points=include_entry_points)
    except SchemaError as exc:
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
            # Module is in the lock but no baseline-modules dir provided →
            # treat baseline fragment as empty so all current classes show
            # as additive new content.  Checksum/version guardrails still apply.
            baseline_fragment = []

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

    # --- Deleted modules (in baseline but not current) ---
    for name in sorted(baseline_modules):
        if name not in current_modules:
            all_changes.append(Change(
                module=name,
                kind="breaking",
                description=f"Module '{name}' deleted (present in baseline but missing in current)",
            ))
            all_violations.append(
                f"Module '{name}': DELETED — present in baseline but missing "
                f"in current modules directory"
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
    allow_extra_live_classes: bool = False,
    *,
    include_entry_points: bool = True,
) -> list[Change]:
    """Compare the composed schema against a live TerminusDB instance."""
    # Lazy import — only when networking is actually requested
    from lms_core.tdb import TdbClient

    # Build the composed schema and compute id-to-module mapping
    try:
        result = compose(current_modules_dir, include_entry_points=include_entry_points)
    except SchemaError as exc:
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

    return diff_against_live(current_by_id, id_to_module, fetched,
                             allow_extra_live_classes=allow_extra_live_classes)


def _cmd_diff(args: argparse.Namespace) -> int:
    import os
    import traceback

    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        return 2

    # --- Validate TDB args (all-or-nothing) ---
    tdb_password = args.tdb_password or os.environ.get("LMS_SCHEMA_TDB_PASSWORD", "")
    tdb_args_provided = any([
        args.tdb_url, args.tdb_org, args.tdb_db, args.tdb_user, args.tdb_password,
    ])

    if tdb_args_provided:
        missing = []
        if not args.tdb_url:
            missing.append("--tdb-url")
        if not args.tdb_org:
            missing.append("--tdb-org")
        if not args.tdb_db:
            missing.append("--tdb-db")
        if not args.tdb_user:
            missing.append("--tdb-user")
        if not tdb_password:
            missing.append("--tdb-password (or LMS_SCHEMA_TDB_PASSWORD env var)")
        if missing:
            print(
                f"Error: live-diff requested but missing required arguments: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2

    has_fragment_baseline = args.baseline_lock or args.baseline_modules
    has_live_baseline = bool(args.tdb_url)

    if not has_fragment_baseline and not has_live_baseline:
        print(
            "Error: no baseline source provided. "
            "Specify at least one of --baseline-lock, --baseline-modules, or --tdb-url.",
            file=sys.stderr,
        )
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
        try:
            changes, violations, warnings = _diff_fragments(
                modules_dir, baseline_modules_dir, baseline_lock,
                include_entry_points=not args.no_entry_points,
            )
        except SchemaError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
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
                tdb_password,
                args.branch,
                allow_extra_live_classes=args.allow_extra_live_classes,
                include_entry_points=not args.no_entry_points,
            ))
        except Exception as exc:
            from lms_core.tdb import TdbError  # delayed import
            if isinstance(exc, TdbError):
                print(f"Error fetching live schema: {exc}", file=sys.stderr)
            else:
                traceback.print_exc()
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
# TDB arg validation helper
# ---------------------------------------------------------------------------


def _validate_tdb_args(args: argparse.Namespace) -> str:
    """Validate TDB connection args (all-or-nothing + env fallback for password).

    Returns the resolved password. Exits with code 2 on validation failure.
    """
    import os

    tdb_password = args.tdb_password or os.environ.get("LMS_SCHEMA_TDB_PASSWORD", "")
    tdb_args_provided = any([
        args.tdb_url, args.tdb_org, args.tdb_db, args.tdb_user, args.tdb_password,
    ])

    if not tdb_args_provided:
        print(
            "Error: TDB connection arguments required. Provide --tdb-url, --tdb-org, "
            "--tdb-db, --tdb-user, and --tdb-password (or LMS_SCHEMA_TDB_PASSWORD env var).",
            file=sys.stderr,
        )
        sys.exit(2)

    missing = []
    if not args.tdb_url:
        missing.append("--tdb-url")
    if not args.tdb_org:
        missing.append("--tdb-org")
    if not args.tdb_db:
        missing.append("--tdb-db")
    if not args.tdb_user:
        missing.append("--tdb-user")
    if not tdb_password:
        missing.append("--tdb-password (or LMS_SCHEMA_TDB_PASSWORD env var)")
    if missing:
        print(
            f"Error: missing required TDB arguments: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)

    return tdb_password


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


async def _plan_branch(args: argparse.Namespace, tdb_password: str):
    from lms_core.tdb import TdbClient
    from .applier import plan_branch, _compose_for_branch

    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        sys.exit(2)

    compose_result = _compose_for_branch(modules_dir)

    async with TdbClient(
        base_url=args.tdb_url,
        org=args.tdb_org,
        db=args.tdb_db,
        user=args.tdb_user,
        password=tdb_password,
    ) as client:
        return await plan_branch(client, args.branch, compose_result, modules_dir)


def _cmd_plan(args: argparse.Namespace) -> int:
    import traceback

    from .applier import _format_plan

    tdb_password = _validate_tdb_args(args)

    try:
        plan = asyncio.run(_plan_branch(args, tdb_password))
    except Exception as exc:
        from lms_core.tdb import TdbError
        if isinstance(exc, TdbError):
            print(f"Error connecting to TerminusDB: {exc}", file=sys.stderr)
        else:
            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(_format_plan(plan))

    if plan.has_errors:
        return 2
    if plan.has_actions:
        return 1
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _cmd_apply(args: argparse.Namespace) -> int:
    import traceback

    tdb_password = _validate_tdb_args(args)

    try:
        plan = asyncio.run(_apply_branch(args, tdb_password))
    except Exception as exc:
        from lms_core.tdb import TdbError
        if isinstance(exc, TdbError):
            print(f"Error: {exc}", file=sys.stderr)
        else:
            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    if plan.has_errors:
        return 2
    return 0


async def _apply_branch(args: argparse.Namespace, tdb_password: str) -> ActionPlan:
    from lms_core.tdb import TdbClient
    from .applier import apply_plan, _compose_for_branch

    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        sys.exit(2)

    compose_result = _compose_for_branch(modules_dir)

    async with TdbClient(
        base_url=args.tdb_url,
        org=args.tdb_org,
        db=args.tdb_db,
        user=args.tdb_user,
        password=tdb_password,
    ) as client:
        # Ensure branch exists; if not, create from main
        if not await client.branch_exists(args.branch):
            print(f"Branch '{args.branch}' does not exist — creating from main.")
            await client.create_branch(args.branch, origin="main")

        return await apply_plan(client, args.branch, compose_result, modules_dir)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace) -> int:
    import traceback

    tdb_password = _validate_tdb_args(args)

    try:
        ok = asyncio.run(_validate_branch(args, tdb_password))
    except Exception as exc:
        from lms_core.tdb import TdbError
        if isinstance(exc, TdbError):
            print(f"Error: {exc}", file=sys.stderr)
        else:
            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    return 0 if ok else 2


async def _validate_branch(args: argparse.Namespace, tdb_password: str) -> bool:
    from lms_core.tdb import TdbClient
    from .applier import validate_branch, _compose_for_branch

    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        sys.exit(2)

    compose_result = _compose_for_branch(modules_dir)

    async with TdbClient(
        base_url=args.tdb_url,
        org=args.tdb_org,
        db=args.tdb_db,
        user=args.tdb_user,
        password=tdb_password,
    ) as client:
        ok, errors = await validate_branch(client, args.branch, compose_result)

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  ✗ {e}")
    if ok:
        print("✓ Validation passed.")
    return ok


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


def _cmd_promote(args: argparse.Namespace) -> int:
    import traceback

    tdb_password = _validate_tdb_args(args)

    try:
        msg = asyncio.run(_promote_branch(args, tdb_password))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        from lms_core.tdb import TdbError
        if isinstance(exc, TdbError):
            print(f"Error: {exc}", file=sys.stderr)
        else:
            traceback.print_exc()
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(msg)
    return 0


async def _promote_branch(args: argparse.Namespace, tdb_password: str) -> str:
    from lms_core.tdb import TdbClient
    from .applier import promote_branch, _compose_for_branch

    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        sys.exit(2)

    compose_result = _compose_for_branch(modules_dir)

    async with TdbClient(
        base_url=args.tdb_url,
        org=args.tdb_org,
        db=args.tdb_db,
        user=args.tdb_user,
        password=tdb_password,
    ) as client:
        return await promote_branch(client, args.branch, compose_result, force=args.force)


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
    p_compose.add_argument(
        "--no-entry-points",
        action="store_true",
        default=False,
        help="Skip discovery of installed lms.schema_modules entry points",
    )

    # codegen
    p_codegen = sub.add_parser("codegen", help="Generate Pydantic models from composed schema")
    p_codegen.add_argument(
        "--composed",
        default="build/composed.schema.json",
        help="Path to composed schema (default: build/composed.schema.json)",
    )
    p_codegen.add_argument(
        "--meta",
        default="build/composed.meta.json",
        help="Path to composed meta mapping (default: build/composed.meta.json)",
    )
    p_codegen.add_argument(
        "--out",
        default="packages/lms-core/src/lms_core/generated",
        help="Output directory for generated models (default: packages/lms-core/src/lms_core/generated)",
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
    p_diff.add_argument(
        "--tdb-password",
        default=None,
        help="TerminusDB password (falls back to LMS_SCHEMA_TDB_PASSWORD env var)",
    )
    p_diff.add_argument("--branch", default="main")
    p_diff.add_argument(
        "--no-entry-points",
        action="store_true",
        default=False,
        help="Skip discovery of installed lms.schema_modules entry points",
    )
    p_diff.add_argument(
        "--allow-extra-live-classes",
        action="store_true",
        default=False,
        help="Downgrade live-only classes from breaking to warnings",
    )

    # Helper to add common TDB + modules-dir arguments to a subparser
    def _add_tdb_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--modules-dir",
            default="schema/modules",
            help="Directory containing module sub-directories (default: schema/modules)",
        )
        p.add_argument("--tdb-url", default=None)
        p.add_argument("--tdb-org", default=None)
        p.add_argument("--tdb-db", default=None)
        p.add_argument("--tdb-user", default=None)
        p.add_argument(
            "--tdb-password",
            default=None,
            help="TerminusDB password (falls back to LMS_SCHEMA_TDB_PASSWORD env var)",
        )
        p.add_argument("--branch", default="main")

    # plan
    p_plan = sub.add_parser("plan", help="Show pending actions (dry-run)")
    _add_tdb_args(p_plan)

    # apply
    p_apply = sub.add_parser("apply", help="Apply schema, migrations, and registry updates")
    _add_tdb_args(p_apply)

    # validate
    p_validate = sub.add_parser("validate", help="Validate schema and registry on a branch")
    _add_tdb_args(p_validate)

    # promote
    p_promote = sub.add_parser("promote", help="Promote a branch to main")
    _add_tdb_args(p_promote)
    p_promote.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Promote even if main has diverged (main head is not an ancestor of the branch)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "compose":
        sys.exit(_cmd_compose(args))
    elif args.command == "codegen":
        sys.exit(_cmd_codegen(args))
    elif args.command == "diff":
        sys.exit(_cmd_diff(args))
    elif args.command == "plan":
        sys.exit(_cmd_plan(args))
    elif args.command == "apply":
        sys.exit(_cmd_apply(args))
    elif args.command == "validate":
        sys.exit(_cmd_validate(args))
    elif args.command == "promote":
        sys.exit(_cmd_promote(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
