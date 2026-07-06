"""Migration file listing, validation, and runner for schema modules.

Migrations live under ``schema/modules/<name>/migrations/`` as
``NNNN_description.py`` files.

Gaps in NNNN numbering are permitted (e.g., 0001 → 0005 is fine).

=== IMPORTANT: Migration idempotency ===

Migrations are data migrations that run BEFORE the new schema is pushed.
If a migration fails, the apply command stops and does NOT write the
corresponding SchemaMigration record.  A crash or failure after a
migration has already completed but before its SchemaMigration record is
written will cause the migration to be seen as "pending" again on the
next run.

THEREFORE: EVERY MIGRATION MUST BE IDEMPOTENT.

A re-run of a migration that has already been partially or fully applied
must succeed and produce the same end state.  Use existence checks,
upserts, or no-op-on-duplicate patterns in migration code.

=== Two-phase releases for breaking changes ===

Because data migrations run BEFORE the new schema is pushed, a migration
cannot use types or fields that only exist in the new schema.  Breaking
changes that introduce new required fields need TWO releases:

  1. First release: make the field Optional (additive in the schema),
     write a migration to backfill existing documents with the new field.
  2. Second release: remove the Optional wrapper (which is breaking but
     no migration needed since all documents already have the field).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MigrationFile:
    order: int          # NNNN index
    name: str           # full filename (e.g. "0001_initial.py")
    path: Path
    checksum: str       # sha256 of file content


_MIGRATION_RE = re.compile(r"^(\d{4})_(.+)\.py$")


class MigrationError(Exception):
    """Raised for invalid migration structure."""


def list_migrations(module_dir: Path) -> list[MigrationFile]:
    """List and validate migration files under ``module_dir / "migrations"``.

    Rules:
        - Only ``.py`` files matching ``NNNN_description.py`` are migrations.
        - Non-``.py`` files in the directory are silently ignored.
        - ``.py`` files that do NOT match the pattern raise ``MigrationError``.
        - Duplicate NNNN order numbers raise ``MigrationError``.

    Returns:
        Sorted list of ``MigrationFile`` (by order).
    """
    mig_dir = module_dir / "migrations"
    if not mig_dir.is_dir():
        return []

    result: list[MigrationFile] = []
    seen: set[int] = set()

    for entry in sorted(mig_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue

        if entry.suffix != ".py":
            # Non-.py files ignored
            continue

        m = _MIGRATION_RE.fullmatch(entry.name)
        if not m:
            raise MigrationError(
                f"Migration file '{entry.name}' in {mig_dir} does not match "
                f"the required pattern NNNN_description.py"
            )

        order = int(m.group(1))
        if order in seen:
            raise MigrationError(
                f"Duplicate migration order {order:04d} in {mig_dir} "
                f"(file: {entry.name})"
            )
        seen.add(order)

        content = entry.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()

        result.append(MigrationFile(
            order=order,
            name=entry.name,
            path=entry,
            checksum=checksum,
        ))

    result.sort(key=lambda mf: mf.order)
    return result
