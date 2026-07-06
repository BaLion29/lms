"""Integration tests for lms-schema apply/validate/promote against a dev instance.

Marked with ``@pytest.mark.integration`` — excluded from default suite.
Requires a running TerminusDB at localhost:6363 (admin/root).
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from lms_core.tdb import TdbClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:6363"
ORG = "admin"
USER = "admin"
PASSWORD = "root"
MODULES_DIR = Path(__file__).parents[3] / "schema" / "modules"
MONOLITHIC_PATH = Path(__file__).parents[3] / "services" / "ingestd" / "schema" / "schema.json"
COMPOSED_PATH = Path(__file__).parents[3] / "build" / "composed.schema.json"

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_name() -> str:
    """Return a unique test database name."""
    return f"test_apply_{uuid.uuid4().hex[:12]}"


async def _tdb(db_name: str) -> TdbClient:
    return TdbClient(base_url=BASE_URL, org=ORG, db=db_name, user=USER, password=PASSWORD)


async def _check_dev_reachable() -> bool:
    """Return True if the dev instance is reachable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as c:
            resp = await c.get(f"{BASE_URL}/api/info")
            return resp.status_code == 200
    except Exception:
        return False


async def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run lms-schema CLI with args and return (exit_code, stdout, stderr)."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "lms_schema.cli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_apply_validate_reapply_noop():
    """Full integration: create DB → apply → validate → re-apply (no-op) → cleanup."""
    if not await _check_dev_reachable():
        pytest.skip("Dev TerminusDB instance at localhost:6363 not reachable")

    db_name = _make_db_name()
    tdb = await _tdb(db_name)

    try:
        # Create DB
        await tdb.create_db(label=db_name, comment="integration test")
        assert await tdb.db_exists()

        # --- Apply ---
        exit_code, stdout, stderr = await _run_cli([
            "apply",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"apply failed: {stderr}\nstdout: {stdout}"
        assert "Apply complete" in stdout

        # --- Validate ---
        exit_code, stdout, stderr = await _run_cli([
            "validate",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"validate failed after apply: {stderr}\nstdout: {stdout}"
        assert "passed" in stdout.lower()

        # --- Re-apply (no-op) ---
        exit_code, stdout, stderr = await _run_cli([
            "apply",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"re-apply failed: {stderr}"
        assert "Nothing to do" in stdout

    finally:
        # Clean up
        try:
            await tdb.aclose()
        except Exception:
            pass
        # Delete DB
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, auth=httpx.BasicAuth(USER, PASSWORD)) as c:
            await c.delete(f"/api/db/{ORG}/{db_name}")


@pytest.mark.asyncio
async def test_integration_bootstrap_on_legacy():
    """Push old monolithic schema → apply composed → verify bootstrap + data intact."""
    if not await _check_dev_reachable():
        pytest.skip("Dev TerminusDB instance at localhost:6363 not reachable")

    if not MONOLITHIC_PATH.is_file():
        pytest.skip("Monolithic schema file not found")

    db_name = _make_db_name()
    tdb = await _tdb(db_name)

    try:
        # Create DB
        await tdb.create_db(label=db_name, comment="bootstrap test")
        assert await tdb.db_exists()

        # Push OLD monolithic schema (without registry classes)
        mono_schema = json.loads(MONOLITHIC_PATH.read_text())
        await tdb.push_schema(
            mono_schema,
            branch="main",
            full_replace=True,
            author="test",
            message="bootstrap monolithic schema",
        )

        # Insert a Task document to verify data survives
        task_doc = {
            "@type": "Task",
            "name": "Test bootstrap task",
            "status": "open",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        iris = await tdb.insert_documents([task_doc], branch="main", author="test", message="seed task")
        assert len(iris) == 1
        task_iri = iris[0]

        # Apply composed schema (should bootstrap registry)
        exit_code, stdout, stderr = await _run_cli([
            "apply",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"apply on legacy DB failed: {stderr}\nstdout: {stdout}"
        assert "Apply complete" in stdout

        # Verify Task document intact
        task = await tdb.get_document(task_iri, branch="main")
        assert task.get("name") == "Test bootstrap task"
        assert task.get("status") == "open"

        # Verify registry docs exist
        try:
            modules = await tdb.get_documents("SchemaModule", branch="main")
            assert len(modules) > 0, "No SchemaModule docs after bootstrap apply"
            core_module = next((m for m in modules if m.get("name") == "core"), None)
            assert core_module is not None, "core module not in SchemaModule registry"
            assert core_module.get("version") == "1.1.0"
        except Exception as exc:
            pytest.fail(f"SchemaModule registry not found after bootstrap: {exc}")

        # Validate passes
        exit_code, stdout, stderr = await _run_cli([
            "validate",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"validate failed after bootstrap: {stderr}\nstdout: {stdout}"

    finally:
        try:
            await tdb.aclose()
        except Exception:
            pass
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, auth=httpx.BasicAuth(USER, PASSWORD)) as c:
            await c.delete(f"/api/db/{ORG}/{db_name}")


@pytest.mark.asyncio
async def test_integration_additive_module_change():
    """Synthetic additive module change on a branch → apply → validate."""
    if not await _check_dev_reachable():
        pytest.skip("Dev TerminusDB instance at localhost:6363 not reachable")

    db_name = _make_db_name()
    tdb = await _tdb(db_name)

    # Create temp modules dir with an extra module
    tmp_modules = Path("/tmp") / f"test_modules_{uuid.uuid4().hex[:8]}"
    try:
        # Copy current modules to temp dir
        shutil.copytree(MODULES_DIR, tmp_modules)

        # Add a synthetic module
        extra_dir = tmp_modules / "testextra"
        extra_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": "testextra",
            "version": "0.1.0",
            "depends_on": [{"name": "core", "range": ">=1.0.0"}],
            "exports": ["TestExtra"],
            "description": "Synthetic test module",
        }
        (extra_dir / "manifest.json").write_text(json.dumps(manifest))
        schema = [
            {
                "@id": "TestExtra",
                "@type": "Class",
                "@inherits": "Source",
                "extra_field": "xsd:string",
            },
        ]
        (extra_dir / "schema.json").write_text(json.dumps(schema))

        try:
            # Create DB
            await tdb.create_db(label=db_name, comment="additive test")
            assert await tdb.db_exists()

            # Create branch
            await tdb.create_branch("feature", origin="main")

            # Apply on feature branch
            exit_code, stdout, stderr = await _run_cli([
                "apply",
                "--modules-dir", str(tmp_modules),
                "--tdb-url", BASE_URL,
                "--tdb-org", ORG,
                "--tdb-db", db_name,
                "--tdb-user", USER,
                "--tdb-password", PASSWORD,
                "--branch", "feature",
            ])
            assert exit_code == 0, f"apply on feature branch failed: {stderr}\nstdout: {stdout}"

            # Validate on feature branch
            exit_code, stdout, stderr = await _run_cli([
                "validate",
                "--modules-dir", str(tmp_modules),
                "--tdb-url", BASE_URL,
                "--tdb-org", ORG,
                "--tdb-db", db_name,
                "--tdb-user", USER,
                "--tdb-password", PASSWORD,
                "--branch", "feature",
            ])
            assert exit_code == 0, f"validate on feature failed: {stderr}\nstdout: {stdout}"

            # Plan (should be no-op now)
            exit_code, stdout, stderr = await _run_cli([
                "plan",
                "--modules-dir", str(tmp_modules),
                "--tdb-url", BASE_URL,
                "--tdb-org", ORG,
                "--tdb-db", db_name,
                "--tdb-user", USER,
                "--tdb-password", PASSWORD,
                "--branch", "feature",
            ])
            assert exit_code == 0, f"plan after apply should return 0: {stderr}"

            # TestExtra class should be registered
            modules = await tdb.get_documents("SchemaModule", branch="feature")
            extra_mod = next((m for m in modules if m.get("name") == "testextra"), None)
            assert extra_mod is not None, "testextra module not in SchemaModule registry"
            assert extra_mod.get("version") == "0.1.0"

        finally:
            import httpx
            async with httpx.AsyncClient(base_url=BASE_URL, auth=httpx.BasicAuth(USER, PASSWORD)) as c:
                await c.delete(f"/api/db/{ORG}/{db_name}")

    finally:
        shutil.rmtree(tmp_modules, ignore_errors=True)
        try:
            await tdb.aclose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_integration_promote():
    """Apply on branch → promote → verify main matches."""
    if not await _check_dev_reachable():
        pytest.skip("Dev TerminusDB instance at localhost:6363 not reachable")

    db_name = _make_db_name()
    tdb = await _tdb(db_name)

    try:
        # Create DB
        await tdb.create_db(label=db_name, comment="promote test")
        assert await tdb.db_exists()

        # Apply on main first (to get it in a known state)
        exit_code, stdout, stderr = await _run_cli([
            "apply",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"apply on main failed: {stderr}"

        # Create branch
        await tdb.create_branch("feature", origin="main")

        # Insert a document on feature branch
        task_doc = {
            "@type": "Task",
            "name": "Feature task",
            "status": "open",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        iris = await tdb.insert_documents(
            [task_doc],
            branch="feature",
            author="test",
            message="feature task",
        )
        assert len(iris) == 1

        # Promote feature to main
        exit_code, stdout, stderr = await _run_cli([
            "promote",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "feature",
        ])
        assert exit_code == 0, f"promote failed: {stderr}\nstdout: {stdout}"
        assert "Promoted" in stdout

        # Verify task on main
        tasks = await tdb.get_documents("Task", branch="main")
        feature_task = next((t for t in tasks if t.get("name") == "Feature task"), None)
        assert feature_task is not None, "Feature task not found on main after promote"

        # Assert warning text on normal promote
        assert "WARNING" in stdout, "Promote should print WARNING text"

    finally:
        try:
            await tdb.aclose()
        except Exception:
            pass
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, auth=httpx.BasicAuth(USER, PASSWORD)) as c:
            await c.delete(f"/api/db/{ORG}/{db_name}")


@pytest.mark.asyncio
async def test_integration_promote_diverged_main_refused():
    """Diverged main (main has commits not in branch) → promote refused without --force."""
    if not await _check_dev_reachable():
        pytest.skip("Dev TerminusDB instance at localhost:6363 not reachable")

    db_name = _make_db_name()
    tdb = await _tdb(db_name)

    try:
        # Create DB
        await tdb.create_db(label=db_name, comment="diverged promote test")
        assert await tdb.db_exists()

        # Apply on main first
        exit_code, stdout, stderr = await _run_cli([
            "apply",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "main",
        ])
        assert exit_code == 0, f"apply on main failed: {stderr}"

        # Create feature branch from main
        await tdb.create_branch("feature", origin="main")

        # Insert a document on main (diverging it from feature)
        task_doc_main = {
            "@type": "Task",
            "name": "Main diverged task",
            "status": "open",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        await tdb.insert_documents(
            [task_doc_main],
            branch="main",
            author="test",
            message="diverging commit on main",
        )

        # Insert a different document on feature
        task_doc_feature = {
            "@type": "Task",
            "name": "Feature task",
            "status": "open",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        await tdb.insert_documents(
            [task_doc_feature],
            branch="feature",
            author="test",
            message="feature task",
        )

        # Now main has diverged — promote should fail
        exit_code, stdout, stderr = await _run_cli([
            "promote",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "feature",
        ])
        assert exit_code == 2, f"promote should have been refused (diverged), got {exit_code}: {stderr}"
        assert "NOT an ancestor" in stderr or "NOT an ancestor" in stdout

        # Promote with --force should work
        exit_code, stdout, stderr = await _run_cli([
            "promote",
            "--modules-dir", str(MODULES_DIR),
            "--tdb-url", BASE_URL,
            "--tdb-org", ORG,
            "--tdb-db", db_name,
            "--tdb-user", USER,
            "--tdb-password", PASSWORD,
            "--branch", "feature",
            "--force",
        ])
        assert exit_code == 0, f"promote --force failed: {stderr}"
        assert "WARNING" in stdout

    finally:
        try:
            await tdb.aclose()
        except Exception:
            pass
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, auth=httpx.BasicAuth(USER, PASSWORD)) as c:
            await c.delete(f"/api/db/{ORG}/{db_name}")
