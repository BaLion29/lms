"""Tests for migration file listing and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firnline_schema.migrations import list_migrations, MigrationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module_with_migrations(base: Path, name: str, files: dict[str, str]) -> Path:
    """Create a module dir with a migrations/ subdir containing *files*.

    *files* maps filename → content.
    """
    mod_dir = base / name
    mod_dir.mkdir(parents=True, exist_ok=True)

    # Minimal manifest + schema so the module dir looks real
    manifest = {
        "name": name,
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        "models_target": f"firnline_core.generated.{name}",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "schema.json").write_text("[]")

    mig_dir = mod_dir / "migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)

    for fname, content in files.items():
        (mig_dir / fname).write_text(content)

    return mod_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_migrations_dir(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {})
    # Remove the migrations dir
    import shutil
    shutil.rmtree(mod_dir / "migrations")
    result = list_migrations(mod_dir)
    assert result == []


def test_empty_migrations_dir(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {})
    result = list_migrations(mod_dir)
    assert result == []


def test_single_migration(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0001_initial.py": "# initial migration\n",
    })
    result = list_migrations(mod_dir)
    assert len(result) == 1
    mf = result[0]
    assert mf.order == 1
    assert mf.name == "0001_initial.py"
    assert mf.path == mod_dir / "migrations" / "0001_initial.py"
    assert len(mf.checksum) == 64  # sha256 hex digest


def test_multiple_migrations_ordered(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0003_third.py": "# third\n",
        "0001_first.py": "# first\n",
        "0002_second.py": "# second\n",
    })
    result = list_migrations(mod_dir)
    assert len(result) == 3
    orders = [mf.order for mf in result]
    assert orders == [1, 2, 3]
    names = [mf.name for mf in result]
    assert names == ["0001_first.py", "0002_second.py", "0003_third.py"]


def test_duplicate_order_raises(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0001_first.py": "# first\n",
        "0001_duplicate.py": "# dup\n",
    })
    with pytest.raises(MigrationError, match="Duplicate migration order"):
        list_migrations(mod_dir)


def test_non_matching_py_raises(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0001_initial.py": "# ok\n",
        "bad_name.py": "# bad\n",
    })
    with pytest.raises(MigrationError, match="does not match"):
        list_migrations(mod_dir)


def test_non_py_files_ignored(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0001_initial.py": "# migration\n",
        "README.md": "migration docs",
        "0002_second.py": "# second\n",
    })
    result = list_migrations(mod_dir)
    assert len(result) == 2
    orders = [mf.order for mf in result]
    assert orders == [1, 2]


def test_checksum_deterministic(tmp_path: Path):
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "0001_initial.py": "def up(): pass\n",
    })
    r1 = list_migrations(mod_dir)
    r2 = list_migrations(mod_dir)
    assert r1[0].checksum == r2[0].checksum


def test_order_number_out_of_range_still_valid(tmp_path: Path):
    """Order numbers like 9999 are valid (just 4 digits)."""
    mod_dir = _make_module_with_migrations(tmp_path, "m", {
        "9999_late.py": "# very late\n",
    })
    result = list_migrations(mod_dir)
    assert result[0].order == 9999


# ---------------------------------------------------------------------------
# Extension migration discovery via applier
# ---------------------------------------------------------------------------


def test_extension_module_dir_discovers_migrations(tmp_path: Path):
    """When ModuleInfo.module_dir is set, migrations are discovered from that dir."""
    from firnline_schema.applier import build_action_plan
    from firnline_schema.composer import ComposeResult, ModuleInfo

    # Build a ComposeResult with a module that has module_dir set
    # (like an entry-point extension)
    mod_dir = _make_module_with_migrations(tmp_path, "time_management", {
        "0001_merge_planning_routines.py": "async def up(tdb, branch): pass\n",
    })
    cr = ComposeResult(
        modules=[
            ModuleInfo(
                name="core",
                version="1.1.0",
                checksum="abc",
                exports=["Source", "Context"],
                module_dir=tmp_path / "core",  # no migrations dir
            ),
            ModuleInfo(
                name="time_management",
                version="0.1.0",
                checksum="def",
                exports=["Task"],
                source="pkg:firnline-ext-time-management==0.1.0",
                module_dir=mod_dir,  # <-- extension's real filesystem path
            ),
        ],
        composed_schema=[
            {"@type": "@context"},
            {"@abstract": [], "@id": "Source", "@type": "Class"},
            {"@abstract": [], "@id": "Context", "@type": "Class"},
            {"@id": "Task", "@type": "Class", "@inherits": "Source", "name": "xsd:string"},
        ],
        class_id_to_module={},
        module_to_target={"core": "firnline_core.generated.core", "time_management": "firnline_ext_time_management.models"},
        module_to_import={},
    )

    plan = build_action_plan(
        compose_result=cr,
        live_schema=cr.composed_schema,
        registry_modules=[
            {"@type": "SchemaModule", "name": "core", "version": "1.1.0", "checksum": "abc"},
            {"@type": "SchemaModule", "name": "time_management", "version": "0.1.0", "checksum": "def"},
        ],
        registry_migrations=[],
        disk_migrations_by_module={
            "time_management": [
                type("PendingMigration", (), {
                    "module": "time_management",
                    "filename": "0001_merge_planning_routines.py",
                    "checksum": "fakechecksum",
                    "path": mod_dir / "migrations" / "0001_merge_planning_routines.py",
                })(),
            ],
        },
        is_bootstrap=False,
    )

    # The migration from the extension should be pending
    assert len(plan.pending_migrations) == 1
    assert plan.pending_migrations[0].module == "time_management"
    assert plan.pending_migrations[0].filename == "0001_merge_planning_routines.py"
