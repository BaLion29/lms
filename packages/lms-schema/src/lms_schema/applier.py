"""Schema application logic: plan, apply, validate, and promote.

=== IMPORTANT: Migration idempotency requirement ===

Migrations are data migrations that run BEFORE the new schema is pushed
(they must be valid under the old/current schema).  If a migration fails,
the apply command stops and DOES NOT write SchemaMigration records.

This means a crash or failure after a migration has completed but before
the SchemaMigration record is written will cause that migration to be
seen as "pending" again on the next run.  Therefore:

    EVERY MIGRATION MUST BE IDEMPOTENT.

A re-run of a migration that has already been partially or fully applied
must succeed and produce the same end state.  Use existence checks,
upserts, or no-op-on-duplicate patterns.

Breaking changes that need new required fields require TWO-PHASE
releases:
  1. First release: make the field Optional, write a migration to
     backfill it.
  2. Second release: remove Optional wrapper.
This is because data migrations run BEFORE schema push, so the new
required field's schema wouldn't exist yet when the migration runs.
"""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .composer import ComposeResult, ModuleInfo, compose
from .differ import _by_id, _canonical

if TYPE_CHECKING:
    from lms_core.tdb import TdbClient


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PendingMigration:
    module: str
    filename: str
    checksum: str
    path: Path


@dataclass
class ActionPlan:
    schema_push_needed: bool
    pending_migrations: list[PendingMigration]
    registry_module_upserts: list[ModuleInfo]
    is_bootstrap: bool
    warnings: list[str]
    errors: list[str]

    @property
    def has_actions(self) -> bool:
        return self.schema_push_needed or bool(self.pending_migrations) or bool(self.registry_module_upserts)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# ---------------------------------------------------------------------------
# Plan builder (pure logic — testable without network)
# ---------------------------------------------------------------------------


def _normalize_cls(cls: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *cls* with arrays sorted for comparison.

    TerminusDB may reorder ``@inherits`` and other array values, so
    we need an order-independent comparison.
    """
    result = {}
    for key, val in cls.items():
        if isinstance(val, list) and all(isinstance(item, str) for item in val):
            result[key] = sorted(val)
        else:
            result[key] = val
    return result


def _schema_eq(composed: list[dict[str, Any]], live: list[dict[str, Any]]) -> bool:
    """Return True if composed and live schemas are canonically equal.

    Arrays within class definitions (e.g. @inherits) are sorted before
    comparison to account for TerminusDB's reordering.
    """
    comp_by_id = {cid: _normalize_cls(cls) for cid, cls in _by_id(composed).items()}
    live_by_id = {cid: _normalize_cls(cls) for cid, cls in _by_id(live).items()}
    if set(comp_by_id) != set(live_by_id):
        return False
    for cid in comp_by_id:
        if _canonical(comp_by_id[cid]) != _canonical(live_by_id[cid]):
            return False
    return True


def build_action_plan(
    compose_result: ComposeResult,
    live_schema: list[dict[str, Any]],
    registry_modules: list[dict[str, Any]],    # SchemaModule docs from DB
    registry_migrations: list[dict[str, Any]],  # SchemaMigration docs from DB
    disk_migrations_by_module: dict[str, list[PendingMigration]],
    is_bootstrap: bool,
) -> ActionPlan:
    """Compute a pure action plan from all inputs (no I/O).

    Args:
        compose_result: Result of composing the current schema/modules.
        live_schema: Schema fetched from the target branch (list of class/enum/@context defs).
        registry_modules: SchemaModule documents from the target branch.
        registry_migrations: SchemaMigration documents from the target branch.
        disk_migrations_by_module: module_name → list of PendingMigration on disk.
        is_bootstrap: True if SchemaModule class does not exist on the target branch.

    Returns:
        ActionPlan with all pending actions, warnings, and errors.
    """
    warnings: list[str] = []
    errors: list[str] = []

    # --- Schema push needed? ---
    schema_push_needed = not _schema_eq(compose_result.composed_schema, live_schema)

    # --- Registry module upserts ---
    registry_module_upserts: list[ModuleInfo] = []
    existing_modules: dict[str, dict[str, str]] = {}
    for doc in registry_modules:
        name = doc.get("name")
        if isinstance(name, str):
            existing_modules[name] = {
                "version": doc.get("version", ""),
                "checksum": doc.get("checksum", ""),
            }

    for info in compose_result.modules:
        existing = existing_modules.get(info.name)
        if existing is None:
            registry_module_upserts.append(info)
        elif existing["version"] != info.version or existing["checksum"] != info.checksum:
            registry_module_upserts.append(info)

    # --- Pending migrations ---
    # Build set of (module, filename) already recorded
    recorded: set[tuple[str, str]] = set()
    recorded_checksums: dict[tuple[str, str], str] = {}
    for doc in registry_migrations:
        mod = doc.get("module")
        fn = doc.get("filename")
        cs = doc.get("checksum")
        if isinstance(mod, str) and isinstance(fn, str):
            key = (mod, fn)
            recorded.add(key)
            if isinstance(cs, str):
                recorded_checksums[key] = cs

    pending_migrations: list[PendingMigration] = []
    # Process modules in alphabetical order for determinism
    for mod_name in sorted(disk_migrations_by_module):
        for mig in disk_migrations_by_module[mod_name]:
            key = (mod_name, mig.filename)
            if key in recorded:
                # Already recorded — check checksum drift
                rec_cs = recorded_checksums.get(key, "")
                if rec_cs != mig.checksum:
                    errors.append(
                        f"Migration {mod_name}/{mig.filename}: checksum drift! "
                        f"Recorded checksum {rec_cs[:16]}..., "
                        f"disk checksum {mig.checksum[:16]}..."
                    )
                # else: already applied, skip
            else:
                pending_migrations.append(mig)

    if is_bootstrap:
        warnings.append(
            "Bootstrap: SchemaModule class not found on branch — "
            "registry writes will happen after schema push."
        )

    return ActionPlan(
        schema_push_needed=schema_push_needed,
        pending_migrations=pending_migrations,
        registry_module_upserts=registry_module_upserts,
        is_bootstrap=is_bootstrap,
        warnings=warnings,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Fetch helpers (thin I/O shell)
# ---------------------------------------------------------------------------


async def _fetch_live_schema(tdb: "TdbClient", branch: str) -> list[dict[str, Any]]:
    """Fetch live schema from branch. Returns [] on error (fresh DB)."""
    try:
        return await tdb.get_schema(branch=branch)
    except Exception:
        return []


async def _fetch_registry_docs(
    tdb: "TdbClient", branch: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Fetch SchemaModule and SchemaMigration docs from branch.

    Returns (modules, migrations, is_bootstrap).
    is_bootstrap is True if the SchemaModule class does not exist on the branch.
    """
    modules: list[dict[str, Any]] = []
    migrations: list[dict[str, Any]] = []
    is_bootstrap = False

    try:
        modules = await tdb.get_documents("SchemaModule", branch=branch)
    except Exception:
        is_bootstrap = True

    if not is_bootstrap:
        try:
            migrations = await tdb.get_documents("SchemaMigration", branch=branch)
        except Exception:
            pass

    return modules, migrations, is_bootstrap


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def _load_migration_module(file_path: Path) -> Any:
    """Load a migration .py file as a Python module via importlib."""
    name = f"lms_migration_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load migration: {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "up", None)):
        raise AttributeError(f"Migration {file_path.name} missing 'async def up(tdb, branch)'")
    return mod


async def run_migrations(
    tdb: "TdbClient",
    branch: str,
    migrations: list[PendingMigration],
) -> list[PendingMigration]:
    """Run pending migrations in order. Returns the list of successfully executed migrations.

    Raises on first failure — caller should not record partial results.
    """
    executed: list[PendingMigration] = []
    for mig in migrations:
        try:
            mod = _load_migration_module(mig.path)
            await mod.up(tdb, branch)
            executed.append(mig)
        except Exception:
            raise RuntimeError(
                f"Migration failed: {mig.module}/{mig.filename}"
            ) from None
    return executed


# ---------------------------------------------------------------------------
# Plan command (dry-run description)
# ---------------------------------------------------------------------------


def _format_plan(plan: ActionPlan) -> str:
    """Format an ActionPlan as a human-readable string."""
    lines: list[str] = []

    if plan.has_errors:
        lines.append("ERRORS:")
        for e in plan.errors:
            lines.append(f"  ! {e}")
        lines.append("")

    if plan.warnings:
        for w in plan.warnings:
            lines.append(f"  ⚠  {w}")
        lines.append("")

    if not plan.has_actions and not plan.has_errors:
        lines.append("Nothing to do — schema, registry, and migrations are all up to date.")
        return "\n".join(lines)

    if plan.schema_push_needed:
        lines.append("Schema push needed: composed schema differs from live instance.")
    else:
        lines.append("Schema: up to date (no push needed).")

    lines.append("")
    lines.append(f"Registry updates needed: {len(plan.registry_module_upserts)} module(s)")
    for info in plan.registry_module_upserts:
        lines.append(f"  • {info.name} @ {info.version} (checksum: {info.checksum[:12]}...)")

    lines.append("")
    lines.append(f"Pending migrations: {len(plan.pending_migrations)}")
    for mig in plan.pending_migrations:
        lines.append(f"  • {mig.module}/{mig.filename}")

    return "\n".join(lines)


async def plan_branch(
    tdb: "TdbClient",
    branch: str,
    compose_result: ComposeResult,
    modules_dir: Path,
) -> ActionPlan:
    """Fetch live state and build an action plan."""
    live_schema = await _fetch_live_schema(tdb, branch)
    registry_modules, registry_migrations, is_bootstrap = await _fetch_registry_docs(tdb, branch)

    # Build disk migrations by module
    from .migrations import list_migrations

    disk_migrations: dict[str, list[PendingMigration]] = {}
    for info in compose_result.modules:
        mod_dir = modules_dir / info.name
        mig_files = list_migrations(mod_dir)
        if mig_files:
            disk_migrations[info.name] = [
                PendingMigration(
                    module=info.name,
                    filename=mf.name,
                    checksum=mf.checksum,
                    path=mf.path,
                )
                for mf in mig_files
            ]

    return build_action_plan(
        compose_result=compose_result,
        live_schema=live_schema,
        registry_modules=registry_modules,
        registry_migrations=registry_migrations,
        disk_migrations_by_module=disk_migrations,
        is_bootstrap=is_bootstrap,
    )


# ---------------------------------------------------------------------------
# Apply logic
# ---------------------------------------------------------------------------


async def apply_plan(
    tdb: "TdbClient",
    branch: str,
    compose_result: ComposeResult,
    modules_dir: Path,
) -> ActionPlan:
    """Execute the action plan against the target branch.

    Order (per docs/terminusdb-notes.md):
      1. Run pending data migrations FIRST (valid under old schema).
      2. Push composed schema with full_replace=true.
      3. Upsert SchemaModule docs (deterministic @id via Lexical key).
      4. Insert SchemaMigration records for migrations run.

    Idempotent: re-running after a successful apply produces "nothing to do".
    """
    plan = await plan_branch(tdb, branch, compose_result, modules_dir)
    if plan.has_errors:
        print("Errors in plan — aborting apply:")
        for e in plan.errors:
            print(f"  ! {e}")
        return plan

    if not plan.has_actions:
        print("Nothing to do.")
        return plan

    # 1. Run pending data migrations
    if plan.pending_migrations:
        print(f"Running {len(plan.pending_migrations)} pending migration(s)...")
        executed = await run_migrations(tdb, branch, plan.pending_migrations)
        print(f"  {len(executed)} migration(s) succeeded.")
    else:
        executed = []

    # 2. Push composed schema (with full_replace=true)
    if plan.schema_push_needed or plan.is_bootstrap:
        print("Pushing composed schema...")
        await tdb.push_schema(
            compose_result.composed_schema,
            branch=branch,
            full_replace=True,
            author="lms-schema",
            message=f"lms-schema apply: schema update ({len(compose_result.modules)} modules)",
        )
        print("  Schema pushed.")
    else:
        print("Schema up to date — skipping push.")

    # 3. Upsert SchemaModule docs
    now_iso = _now_iso()
    for info in plan.registry_module_upserts:
        doc: dict[str, Any] = {
            "@type": "SchemaModule",
            "name": info.name,
            "version": info.version,
            "checksum": info.checksum,
            "installed_at": now_iso,
        }
        # Use deterministic @id from Lexical key
        doc["@id"] = f"SchemaModule/{info.name}"
        await _upsert_registry_doc(tdb, branch, doc)

    if plan.registry_module_upserts:
        print(f"  {len(plan.registry_module_upserts)} registry module(s) upserted.")

    # 4. Insert SchemaMigration records
    if executed:
        migration_docs: list[dict[str, Any]] = []
        for mig in executed:
            migration_docs.append({
                "@type": "SchemaMigration",
                "module": mig.module,
                "filename": mig.filename,
                "checksum": mig.checksum,
                "applied_at": now_iso,
            })
        await tdb.insert_documents(
            migration_docs,
            branch=branch,
            author="lms-schema",
            message=f"lms-schema apply: {len(executed)} migration(s) recorded",
        )
        print(f"  {len(executed)} migration record(s) inserted.")

    print("Apply complete.")
    return plan


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _upsert_registry_doc(
    tdb: "TdbClient", branch: str, doc: dict[str, Any],
) -> None:
    """Upsert a SchemaModule/SchemaMigration doc — check existence first.

    - If the document exists: PUT (replace).
    - If the document does not exist: POST (insert).

    This is needed because PUT with @id on a non-existent document returns
    404 DocumentNotFound rather than creating it.
    """
    from lms_core.tdb import TdbError

    iri = doc["@id"]
    try:
        await tdb.get_document(iri, branch=branch)
        # Exists → replace
        await tdb.replace_document(
            doc,
            branch=branch,
            author="lms-schema",
            message="lms-schema apply: registry upsert",
        )
    except TdbError as exc:
        if exc.status == 404:
            # New → insert
            await tdb.insert_documents(
                [doc],
                branch=branch,
                author="lms-schema",
                message="lms-schema apply: registry upsert",
            )
        else:
            raise


# ---------------------------------------------------------------------------
# Validate logic
# ---------------------------------------------------------------------------


async def validate_branch(
    tdb: "TdbClient",
    branch: str,
    compose_result: ComposeResult,
) -> tuple[bool, list[str]]:
    """Validate that the branch schema and registry match the compose result.

    Returns (ok, errors).  ok=True means validation passed.
    """
    errors: list[str] = []

    # 1. GraphQL smoke test: every concrete (non-abstract) class
    all_classes: dict[str, dict[str, Any]] = {}
    for obj in compose_result.composed_schema:
        cid = obj.get("@id")
        if isinstance(cid, str) and obj.get("@type") != "@context":
            all_classes[cid] = obj

    for cid in sorted(all_classes):
        cls_def = all_classes[cid]
        if cls_def.get("@type") != "Class":
            continue
        if "@abstract" in cls_def:
            continue  # skip abstract classes

        query = f"{{ {cid}(limit:1) {{ _id }} }}"
        try:
            await tdb.graphql(query, branch=branch)
        except Exception as exc:
            errors.append(f"GraphQL smoke test failed for class '{cid}': {exc}")

    # 2. SchemaModule docs match compose result
    try:
        registry_modules = await tdb.get_documents("SchemaModule", branch=branch)
    except Exception:
        errors.append("Cannot fetch SchemaModule documents — registry class may not exist")
        return False, errors

    existing: dict[str, dict[str, str]] = {}
    for doc in registry_modules:
        name = doc.get("name")
        if isinstance(name, str):
            existing[name] = {
                "version": doc.get("version", ""),
                "checksum": doc.get("checksum", ""),
            }

    for info in compose_result.modules:
        ex = existing.get(info.name)
        if ex is None:
            errors.append(
                f"Module '{info.name}' not found in SchemaModule registry"
            )
        elif ex["version"] != info.version or ex["checksum"] != info.checksum:
            errors.append(
                f"Module '{info.name}': registry version/checksum mismatch "
                f"(registry: {ex['version']}/{ex['checksum'][:12]}..., "
                f"composed: {info.version}/{info.checksum[:12]}...)"
            )

    # Check for extra registry entries not in compose result
    composed_names = {info.name for info in compose_result.modules}
    for name in existing:
        if name not in composed_names:
            errors.append(
                f"Extra SchemaModule registry entry '{name}' not in composed modules"
            )

    return (len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# Promote logic
# ---------------------------------------------------------------------------


async def promote_branch(
    tdb: "TdbClient",
    branch: str,
    compose_result: ComposeResult,
) -> str:
    """Promote *branch* to main by fast-forwarding main to the branch head.

    Returns a status message. Raises on failure.
    """
    # Preflight: branch must exist
    if not await tdb.branch_exists(branch):
        raise ValueError(f"Branch '{branch}' does not exist")

    # Get branch head and main head
    branch_head = await tdb.get_branch_head(branch)
    main_head = await tdb.get_branch_head("main")

    if branch_head == main_head:
        return f"Branch '{branch}' head is the same as main — nothing to promote."

    # Build commit descriptor
    commit_desc = f"{tdb.org}/{tdb.db}/local/commit/{branch_head}"

    # Reset main to branch head
    await tdb.reset_branch("main", commit_desc)

    # Verify: main's schema == composed
    main_schema = await tdb.get_schema(branch="main")
    if not _schema_eq(compose_result.composed_schema, main_schema):
        raise RuntimeError(
            "Post-promote verification failed: main schema does not match composed schema"
        )

    return (
        f"Promoted '{branch}' → main.\n"
        f"  Main is now at commit: {branch_head}\n"
        f"  ⚠  WARNING: promote fast-forwards main to the branch head, "
        f"including any other commits on that branch."
    )


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def file_checksum(path: Path) -> str:
    """SHA-256 of file content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compose_for_branch(
    modules_dir: Path,
) -> "ComposeResult":
    """Compose modules from disk (synchronous wrapper for CLI use)."""
    return compose(modules_dir)
