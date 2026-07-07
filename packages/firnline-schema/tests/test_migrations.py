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
