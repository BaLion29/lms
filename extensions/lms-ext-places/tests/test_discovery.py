"""Minimal test: lms_ext_places is discoverable and manifest matches."""

from __future__ import annotations

from pathlib import Path

import json


def test_manifest_name_matches() -> None:
    manifest_path = Path(__file__).parents[1] / "src" / "lms_ext_places" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["name"] == "places"


def test_schema_json_exists() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "lms_ext_places" / "schema.json"
    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text())
    assert any(obj.get("@id") == "Location" for obj in schema)
