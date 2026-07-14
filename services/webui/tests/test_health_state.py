"""Tests for HealthState healthz response parsing."""

from __future__ import annotations

from firnline_webui.state.health import HealthState


def _new_state():
    """Create a fresh HealthState for testing."""
    return HealthState()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TerminusDB flat string parsing
# ---------------------------------------------------------------------------


def test_parse_terminusdb_flat_string_up():
    assert HealthState._parse_terminusdb({"terminusdb": "up"}) == "up"


def test_parse_terminusdb_flat_string_down():
    assert HealthState._parse_terminusdb({"terminusdb": "down"}) == "down"


def test_parse_terminusdb_nested_dict_legacy_fallback():
    assert HealthState._parse_terminusdb({"terminusdb": {"status": "connected"}}) == "connected"


def test_parse_terminusdb_missing_key_returns_unknown():
    assert HealthState._parse_terminusdb({}) == "unknown"


def test_parse_terminusdb_none_returns_unknown():
    assert HealthState._parse_terminusdb({"terminusdb": None}) == "unknown"


# ---------------------------------------------------------------------------
# Captured parsing test
# ---------------------------------------------------------------------------


def test_apply_captured_full():
    state = _new_state()
    state._apply_captured(
        {
            "status": "ok",
            "version": "1.2.3",
            "terminusdb": "up",
            "handlers": ["h1", "h2"],
            "blob_root_writable": True,
        }
    )
    assert state.captured_status == "ok"
    assert state.captured_version == "1.2.3"
    assert state.captured_terminusdb == "up"
    assert state.captured_handlers == ["h1", "h2"]
    assert state.captured_blob_root_writable is True
    assert state.captured_blob_root_writable_available is True


def test_apply_captured_degraded():
    state = _new_state()
    state._apply_captured({"status": "degraded", "terminusdb": "down", "blob_root_writable": False})
    assert state.captured_status == "degraded"
    assert state.captured_terminusdb == "down"
    assert state.captured_blob_root_writable is False
    assert state.captured_blob_root_writable_available is True


# ---------------------------------------------------------------------------
# Queryd parsing test
# ---------------------------------------------------------------------------


def test_apply_queryd_full():
    state = _new_state()
    state._apply_queryd(
        {
            "status": "ok",
            "version": "2.0.0",
            "terminusdb": "up",
            "plugins": ["p1", "p2"],
        }
    )
    assert state.queryd_status == "ok"
    assert state.queryd_version == "2.0.0"
    assert state.queryd_terminusdb == "up"
    assert state.queryd_plugins == ["p1", "p2"]


# ---------------------------------------------------------------------------
# Indexed parsing test (flat string, store/poller, absent fields)
# ---------------------------------------------------------------------------


def test_apply_indexed_full():
    state = _new_state()
    state._apply_indexed(
        {
            "status": "ok",
            "terminusdb": "up",
            "store": "ready",
            "poller": "running",
        }
    )
    assert state.indexed_status == "ok"
    assert state.indexed_version == "\u2014"  # em dash — indexed has no version
    assert state.indexed_terminusdb == "up"
    assert state.indexed_plugins == []  # indexed has no plugins
    assert state.indexed_store == "ready"
    assert state.indexed_poller == "running"


def test_apply_indexed_absent_store_and_poller():
    """When store/poller are missing, they display em-dash."""
    state = _new_state()
    state._apply_indexed({"status": "ok", "terminusdb": "up"})
    assert state.indexed_store == "\u2014"
    assert state.indexed_poller == "\u2014"


def test_apply_indexed_empty_store_and_poller():
    """When store/poller are empty strings, they display em-dash."""
    state = _new_state()
    state._apply_indexed({"status": "ok", "terminusdb": "up", "store": "", "poller": ""})
    assert state.indexed_store == "\u2014"
    assert state.indexed_poller == "\u2014"


# ---------------------------------------------------------------------------
# MCPD parsing test
# ---------------------------------------------------------------------------


def test_apply_mcpd_ok():
    state = _new_state()
    state._apply_mcpd({"status": "ok"})
    assert state.mcpd_status == "ok"


def test_apply_mcpd_degraded():
    state = _new_state()
    state._apply_mcpd({"status": "degraded"})
    assert state.mcpd_status == "degraded"


def test_apply_mcpd_unreachable_default():
    """When status key is missing, defaults to 'unknown'."""
    state = _new_state()
    state._apply_mcpd({})
    assert state.mcpd_status == "unknown"
