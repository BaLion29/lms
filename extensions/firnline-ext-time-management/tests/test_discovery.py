"""Discovery tests for all four entry points of firnline-ext-time-management:
- firnline.schema_modules (manifest + schema checks)
- firnline.ingestd.extractors
- firnline.queryd.tools
- firnline.indexed.indexers
"""

from __future__ import annotations

import json
from pathlib import Path

from firnline_core.plugins import IndexerPlugin, validate_plugin


PKG_DIR = Path(__file__).parents[1] / "src" / "firnline_ext_time_management"


# ---------------------------------------------------------------------------
# schema_module — manifest + schema presence (ported pattern from planning/routines)
# ---------------------------------------------------------------------------


def test_manifest_and_schema_present():
    """Verify the package contains manifest.json and schema.json."""
    assert (PKG_DIR / "manifest.json").is_file()
    assert (PKG_DIR / "schema.json").is_file()


def test_manifest_name_matches():
    manifest = json.loads((PKG_DIR / "manifest.json").read_text())
    assert manifest["name"] == "time_management"
    assert manifest["version"] == "0.2.0"


def test_schema_exports_all_four_main_classes():
    schema = json.loads((PKG_DIR / "schema.json").read_text())
    ids = {c["@id"] for c in schema}
    assert "Task" in ids
    assert "Event" in ids
    assert "Routine" in ids
    assert "Activity" in ids
    assert "TaskSpec" in ids
    assert "ActivitySpec" in ids


# ---------------------------------------------------------------------------
# extractor entry point
# ---------------------------------------------------------------------------


def test_extractor_plugin_loadable():
    from firnline_ext_time_management.extract import plugin

    assert plugin.name == "time_management_extractor"
    assert plugin.produces == ["Task", "Event", "Person", "Location", "Routine", "Activity", "Project", "Area", "Goal"]


# ---------------------------------------------------------------------------
# tools entry point
# ---------------------------------------------------------------------------


def test_tools_plugin_loadable():
    from firnline_ext_time_management.tools import plugin

    assert plugin.name == "time_management_tools"


# ---------------------------------------------------------------------------
# indexer entry point
# ---------------------------------------------------------------------------


def test_indexer_plugin_loadable():
    from firnline_ext_time_management.indexer import plugin

    assert plugin.name == "time_management_indexer"


def test_indexer_protocol_conformance():
    """The indexer plugin conforms to the IndexerPlugin protocol."""
    from firnline_ext_time_management.indexer import plugin

    violations = validate_plugin(plugin, IndexerPlugin)
    assert violations == [], f"protocol violations: {violations}"


def test_indexer_indexed_classes_cover_all_seven():
    """The indexer covers Task, Event, Routine, Activity, Project, Area, Goal."""
    from firnline_ext_time_management.indexer import plugin

    classes = plugin.indexed_classes()
    assert set(classes) == {"Task", "Event", "Routine", "Activity", "Project", "Area", "Goal"}
