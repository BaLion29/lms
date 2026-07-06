"""Backward-compat import smoke test — semver moved to firnline-core, re-exported here."""

from __future__ import annotations

from firnline_schema.semver import Range, Version


def test_semver_import_compat() -> None:
    """Existing imports from firnline_schema.semver continue to work."""
    v = Version.parse("1.0.0")
    r = Range(">=1.0.0")
    assert r.contains(v)
