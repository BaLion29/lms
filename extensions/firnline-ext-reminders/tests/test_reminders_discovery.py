"""Discovery test for firnline-ext-reminders."""

from __future__ import annotations

import json
from pathlib import Path


def test_reminders_module_present():
    """Verify reminders_module contains manifest.json and schema.json."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_reminders"
    mod_dir = pkg_dir / "reminders_module"
    assert (mod_dir / "manifest.json").is_file()
    assert (mod_dir / "schema.json").is_file()

    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["name"] == "reminders"
    assert manifest["version"] == "0.1.0"

    schema = json.loads((mod_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Reminder" in ids
