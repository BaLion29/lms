"""Verify models and indexer import cleanly after re-baseline."""

from __future__ import annotations


def test_models_import() -> None:
    import firnline_ext_routines.models as m

    assert hasattr(m, "Routine")
    assert hasattr(m, "RoutineStep")
    assert hasattr(m, "Activity")
    assert hasattr(m, "ActivitySpec")
    assert m.Routine.__name__ == "Routine"
    assert m.Activity.__name__ == "Activity"


def test_indexer_import() -> None:
    import firnline_ext_routines.indexer as idx

    plugin = idx.plugin
    assert plugin.name == "routines_indexer"
    assert plugin.indexed_classes() == ["Routine", "Activity"]
