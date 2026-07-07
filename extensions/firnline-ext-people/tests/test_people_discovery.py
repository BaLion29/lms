"""Minimal discovery test for firnline-ext-people schema module."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_and_schema_present():
    """Verify the package contains manifest.json and schema.json."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_people"
    assert (pkg_dir / "manifest.json").is_file()
    assert (pkg_dir / "schema.json").is_file()

    manifest = json.loads((pkg_dir / "manifest.json").read_text())
    assert manifest["name"] == "people"
    assert manifest["version"] == "0.1.0"

    schema = json.loads((pkg_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Person" in ids
    assert "Contact" in ids
