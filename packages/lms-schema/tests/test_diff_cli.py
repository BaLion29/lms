"""CLI-level tests for the diff command exit codes using tmp module trees."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module(
    base: Path,
    name: str,
    version: str = "1.0.0",
    exports: list[str] | None = None,
    classes: list[dict] | None = None,
    migrations: dict[str, str] | None = None,
    context: dict | None = None,
) -> Path:
    mod_dir = base / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "depends_on": [],
        "exports": exports or [],
        "description": "test",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "schema.json").write_text(json.dumps(classes or []))
    if context is not None:
        (mod_dir / "context.json").write_text(json.dumps(context))
    if migrations:
        mig_dir = mod_dir / "migrations"
        mig_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in migrations.items():
            (mig_dir / fname).write_text(content)
    return mod_dir


def _run_diff(modules_dir: Path, baseline_modules: Path | None = None, baseline_lock: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "lms_schema.cli", "diff", "--modules-dir", str(modules_dir)]
    if baseline_modules:
        cmd.extend(["--baseline-modules", str(baseline_modules)])
    if baseline_lock:
        cmd.extend(["--baseline-lock", str(baseline_lock)])
    return subprocess.run(cmd, capture_output=True, text=True)


# Core context + classes (needed for compose)
_CORE_CONTEXT = {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}
_CORE_CLASSES = [
    {"@abstract": [], "@id": "Source", "@type": "Class"},
    {"@abstract": [], "@id": "Context", "@type": "Class"},
]


def _make_core(base: Path, version: str = "1.0.0") -> Path:
    return _make_module(base, "core", version=version, exports=["Source", "Context"],
                        classes=_CORE_CLASSES, context=_CORE_CONTEXT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiffExitCodes:

    def test_no_changes_exit_0(self, tmp_path: Path):
        """No changes → exit 0."""
        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        # Baseline is same as current
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)

        # Write a consistent lock
        from lms_schema.composer import compose
        result = compose(mod_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in result.modules}}
        real_lock_path = tmp_path / "real_lock.json"
        real_lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=real_lock_path)
        assert proc.returncode == 0, f"stdout={proc.stdout} stderr={proc.stderr}"

    def test_breaking_minor_violation_exit_2(self, tmp_path: Path):
        """Breaking change with only MINOR bump → exit 2."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="1.1.0", exports=[],
                     classes=[])  # removed Foo

        # Build real lock from baseline
        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "BREAKING" in proc.stdout

    def test_breaking_major_no_migration_exit_2(self, tmp_path: Path):
        """Breaking change + MAJOR bump but no new migration → exit 2."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="2.0.0", exports=[],
                     classes=[])  # removed Foo, no migrations

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "migration" in proc.stdout.lower()

    def test_breaking_major_new_migration_ok_exit_1(self, tmp_path: Path):
        """Breaking change + MAJOR bump + new migration → exit 1."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}],
                     migrations={"0001_old.py": "# old\n"})

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="2.0.0", exports=[],
                     classes=[],  # removed Foo
                     migrations={"0001_old.py": "# old\n", "0002_new.py": "# new\n"})

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 1, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "guardrails satisfied" in proc.stdout.lower() or "Removed class" in proc.stdout

    def test_additive_minor_ok_exit_1(self, tmp_path: Path):
        """Additive change + MINOR bump → exit 1."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="1.1.0", exports=["Foo"],
                     classes=[
                         {"@id": "Foo", "@type": "Class"},
                         {"@id": "Bar", "@type": "Class"},
                     ])

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 1, f"stdout={proc.stdout} stderr={proc.stderr}"

    def test_checksum_changed_version_unchanged_violation(self, tmp_path: Path):
        """Checksum changed but version unchanged → violation (exit 2)."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class", "name": "xsd:string"}])

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "version" in proc.stdout.lower()
        assert "not bumped" in proc.stdout.lower() or "checksum" in proc.stdout.lower()

    def test_duplicate_instance_both_baselines(self, tmp_path: Path):
        """Can provide both baseline-lock and baseline-modules simultaneously."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 0, f"stdout={proc.stdout} stderr={proc.stderr}"

    def test_malformed_manifest_no_traceback(self, tmp_path: Path):
        """Malformed manifest should produce a clean error, not a raw traceback."""
        _make_core(tmp_path)
        mod = tmp_path / "m1"
        mod.mkdir(parents=True, exist_ok=True)
        (mod / "manifest.json").write_text("{invalid json")
        (mod / "schema.json").write_text("[]")

        # Baseline dir triggers _diff_fragments which loads manifests
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)

        proc = _run_diff(tmp_path, baseline_modules=bl_dir)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "Error" in proc.stderr
        assert "Traceback" not in proc.stderr

    def test_no_baseline_exit_2(self, tmp_path: Path):
        """No baseline source at all → usage error, exit 2."""
        mod_dir = tmp_path / "current"
        _make_core(mod_dir)

        proc = _run_diff(mod_dir)  # no --baseline-*, no --tdb-*
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "no baseline" in proc.stderr.lower()

    def test_deleted_module_is_breaking(self, tmp_path: Path):
        """Module in baseline but not current → breaking change."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        # m1 deliberately not created

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        proc = _run_diff(mod_dir, baseline_modules=bl_dir, baseline_lock=lock_path)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "deleted" in proc.stdout.lower()

    def test_new_module_in_lock_only(self, tmp_path: Path):
        """Module in lock but not in baseline-modules dir — treated as all-new."""
        bl_dir = tmp_path / "baseline"
        _make_core(bl_dir)
        # m1 exists in baseline lock but NOT in baseline-modules dir
        _make_module(bl_dir, "m1", version="1.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"}])

        mod_dir = tmp_path / "current"
        _make_core(mod_dir)
        _make_module(mod_dir, "m1", version="2.0.0", exports=["Foo"],
                     classes=[{"@id": "Foo", "@type": "Class"},
                              {"@id": "Bar", "@type": "Class"}])

        from lms_schema.composer import compose
        bl_result = compose(bl_dir)
        real_lock = {"modules": {info.name: {"version": info.version, "checksum": info.checksum} for info in bl_result.modules}}
        lock_path = tmp_path / "lock.json"
        lock_path.write_text(json.dumps(real_lock))

        # baseline-modules dir lacks m1, so m1 only in lock → baseline_fragment=[]
        empty_bl = tmp_path / "empty_baseline"
        empty_bl.mkdir()
        _make_core(empty_bl)

        proc = _run_diff(mod_dir, baseline_modules=empty_bl, baseline_lock=lock_path)
        # All classes in m1 are "New class" (additive), version 1.0.0→2.0.0:
        # additive + MAJOR bump = allowed (over-bump). Exit 1.
        assert proc.returncode == 1, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "New class" in proc.stdout

    def test_tdb_partial_args_exit_2(self, tmp_path: Path):
        """Providing --tdb-url without other tdb args → exit 2."""
        mod_dir = tmp_path / "current"
        _make_core(mod_dir)

        cmd = [
            sys.executable, "-m", "lms_schema.cli", "diff",
            "--modules-dir", str(mod_dir),
            "--tdb-url", "http://localhost:6363",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 2, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "missing" in proc.stderr.lower()
