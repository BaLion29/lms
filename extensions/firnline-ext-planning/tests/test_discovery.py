"""Discovery test for firnline-ext-planning schema module + migrations."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_and_schema_present():
    """Verify the package contains manifest.json, schema.json, and migrations/."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_planning"
    assert (pkg_dir / "manifest.json").is_file()
    assert (pkg_dir / "schema.json").is_file()
    assert (pkg_dir / "migrations").is_dir()
    assert (pkg_dir / "migrations" / "0001_noop_relocate_triggers_reminder.py").is_file()

    manifest = json.loads((pkg_dir / "manifest.json").read_text())
    assert manifest["name"] == "planning"
    assert manifest["version"] == "2.0.0"

    schema = json.loads((pkg_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Task" in ids
    assert "Event" in ids
    assert "TaskSpec" in ids
