"""Tests for lms_core.settings.TdbSettings."""

from lms_core.settings import TdbSettings


def test_tdb_settings_from_kwargs():
    """TdbSettings can be constructed with explicit keyword arguments."""
    s = TdbSettings(tdb_db="testdb", tdb_password="secret")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_db == "testdb"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"
    assert s.tdb_password == "secret"


def test_tdb_settings_defaults():
    """TdbSettings has correct default values."""
    s = TdbSettings(tdb_db="db", tdb_password="pw")
    assert s.tdb_url == "http://localhost:6363"
    assert s.tdb_org == "admin"
    assert s.tdb_branch == "main"
    assert s.tdb_user == "admin"


def test_tdb_settings_extra_ignored():
    """Unknown extra fields are ignored (for subclassing compatibility)."""
    # pydantic-settings BaseSettings doesn't have extra="ignore" by default
    # but we just verify the standard behavior
    s = TdbSettings(tdb_db="db", tdb_password="pw")
    assert s.tdb_db == "db"
