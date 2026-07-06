"""Backward-compat import smoke test — semver moved to lms-core, re-exported here."""

from __future__ import annotations

from lms_schema.semver import Range, Version


def test_semver_import_compat() -> None:
    """Existing imports from lms_schema.semver continue to work."""
    v = Version.parse("1.0.0")
    r = Range(">=1.0.0")
    assert r.contains(v)
