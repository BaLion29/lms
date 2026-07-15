"""Minimal discovery test for firnline-ext-address-book schema module."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_and_schema_present():
    """Verify the package contains manifest.json and schema.json."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_address_book"
    assert (pkg_dir / "manifest.json").is_file()
    assert (pkg_dir / "schema.json").is_file()

    manifest = json.loads((pkg_dir / "manifest.json").read_text())
    assert manifest["name"] == "address_book"
    assert manifest["version"] == "0.1.0"

    schema = json.loads((pkg_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Person" in ids
    assert "Contact" in ids
    assert "Location" in ids
    assert "Organization" in ids
    assert "Affiliation" in ids
    assert "AddressBookGeocoderAction" in ids


def test_manifest_exports_match_schema():
    """Exports list matches the @id entries in schema.json."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_address_book"
    manifest = json.loads((pkg_dir / "manifest.json").read_text())
    schema = json.loads((pkg_dir / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    exports = set(manifest["exports"])
    assert exports == ids


def test_address_book_geocoder_action_schema():
    """AddressBookGeocoderAction exists with @inherits Action and label_field metadata."""
    pkg_dir = Path(__file__).parents[1] / "src" / "firnline_ext_address_book"
    schema = json.loads((pkg_dir / "schema.json").read_text())
    by_id = {c["@id"]: c for c in schema}
    action = by_id["AddressBookGeocoderAction"]
    assert action["@inherits"] == "Action"
    assert action["@metadata"]["label_field"] == "name"
    assert "@documentation" in action
