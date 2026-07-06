"""Discovery test for firnline-ext-reminders — two schema modules in one package."""

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
    assert manifest["version"] == "1.0.0"

    schema = json.loads((mod_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Reminder" in ids


def test_triggers_module_present():
    """Verify triggers_module contains manifest.json and schema.json."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_reminders"
    mod_dir = pkg_dir / "triggers_module"
    assert (mod_dir / "manifest.json").is_file()
    assert (mod_dir / "schema.json").is_file()

    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["name"] == "triggers"
    assert manifest["version"] == "1.0.0"

    schema = json.loads((mod_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Trigger" in ids
    assert "ScheduleTrigger" in ids
    assert "RelativeTrigger" in ids
