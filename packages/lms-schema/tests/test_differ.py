"""Tests for the schema differ: change classification, live-instance diff, and guardrails."""

from __future__ import annotations

from lms_schema.differ import (
    Change,
    classify_module_changes,
    classify_manifest_changes,
    check_guardrails,
    diff_against_live,
)
from lms_schema.semver import Version


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLASS_A = {"@id": "A", "@type": "Class", "name": "xsd:string"}
_ENUM_X = {
    "@id": "X", "@type": "Enum",
    "@value": ["one", "two", "three"],
}


# ===================================================================
# Classification table-tests — ADDITIVE
# ===================================================================


class TestAdditiveChanges:
    """Every ADDITIVE change scenario from the spec."""

    def test_new_class(self):
        changes = classify_module_changes("m", [], [_CLASS_A])
        assert changes == [
            Change("m", "additive", "New class 'A'"),
        ]

    def test_new_enum(self):
        changes = classify_module_changes("m", [], [_ENUM_X])
        assert changes == [
            Change("m", "additive", "New class 'X'"),
        ]

    def test_new_optional_property(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, description={"@class": "xsd:string", "@type": "Optional"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "additive"
        assert "description" in changes[0].description

    def test_new_set_property(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, tags={"@class": "xsd:string", "@type": "Set"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "additive"
        assert "tags" in changes[0].description

    def test_new_list_property(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, items={"@class": "xsd:string", "@type": "List"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "additive"
        assert "items" in changes[0].description

    def test_new_enum_value(self):
        old = [dict(_ENUM_X)]
        new = [dict(_ENUM_X, **{"@value": ["one", "two", "three", "four"]})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "additive"
        assert "four" in changes[0].description

    def test_exports_added(self):
        changes = classify_manifest_changes("m", ["Foo"], ["Foo", "Bar"])
        assert len(changes) == 1
        assert changes[0].kind == "additive"
        assert "Bar" in changes[0].description

    def test_description_only_change_no_schema_change(self):
        """Description/metadata-only manifest changes produce no schema changes."""
        changes = classify_module_changes("m", [_CLASS_A], [_CLASS_A])
        assert changes == []


# ===================================================================
# Classification table-tests — BREAKING
# ===================================================================


class TestBreakingChanges:
    """Every BREAKING change scenario from the spec."""

    def test_new_required_property(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, required_field="xsd:string")]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "required_field" in changes[0].description
        assert "REQUIRED" in changes[0].description

    def test_property_removed(self):
        old = [dict(_CLASS_A, x="xsd:integer")]
        new = [dict(_CLASS_A)]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "removed" in changes[0].description
        assert "x" in changes[0].description

    def test_property_type_changed(self):
        old = [dict(_CLASS_A, x="xsd:string")]
        new = [dict(_CLASS_A, x="xsd:integer")]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "range/type" in changes[0].description

    def test_wrapper_change_optional_to_plain(self):
        old = [dict(_CLASS_A, x={"@class": "xsd:string", "@type": "Optional"})]
        new = [dict(_CLASS_A, x="xsd:string")]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "range/type" in changes[0].description

    def test_wrapper_change_optional_to_set(self):
        old = [dict(_CLASS_A, x={"@class": "xsd:string", "@type": "Optional"})]
        new = [dict(_CLASS_A, x={"@class": "xsd:string", "@type": "Set"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"

    def test_class_removed(self):
        old = [_CLASS_A]
        new: list[dict] = []
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "Removed class 'A'" == changes[0].description

    def test_enum_removed(self):
        old = [_ENUM_X]
        new: list[dict] = []
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "Removed class 'X'" == changes[0].description

    def test_enum_value_removed(self):
        old = [dict(_ENUM_X)]
        new = [dict(_ENUM_X, **{"@value": ["one", "three"]})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "two" in changes[0].description

    def test_key_change(self):
        old = [dict(_CLASS_A, **{"@key": "name"})]
        new = [dict(_CLASS_A, **{"@key": "other"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "@key" in changes[0].description

    def test_inherits_change(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, **{"@inherits": "Source"})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "@inherits" in changes[0].description

    def test_abstract_change(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, **{"@abstract": []})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "@abstract" in changes[0].description

    def test_subdocument_change(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, **{"@subdocument": []})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "@subdocument" in changes[0].description

    def test_oneof_change(self):
        old = [dict(_CLASS_A)]
        new = [dict(_CLASS_A, **{"@oneOf": {"a": "xsd:string"}})]
        changes = classify_module_changes("m", old, new)
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "@oneOf" in changes[0].description

    def test_exports_removed(self):
        changes = classify_manifest_changes("m", ["Foo", "Bar"], ["Foo"])
        assert len(changes) == 1
        assert changes[0].kind == "breaking"
        assert "Bar" in changes[0].description


# ===================================================================
# Guardrail tests
# ===================================================================


class TestGuardrails:
    """Semver/migration guardrail checks."""

    def test_breaking_plus_minor_bump_violation(self):
        changes = [Change("m", "breaking", "Removed class 'X'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(1, 1, 0), set(), set(),
        )
        assert len(violations) == 1
        assert "BREAKING" in violations[0]
        assert "1.0.0" in violations[0]

    def test_breaking_plus_major_no_migration_violation(self):
        changes = [Change("m", "breaking", "Removed class 'X'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(2, 0, 0), set(), set(),
        )
        assert len(violations) == 1
        assert "migration" in violations[0].lower()

    def test_breaking_plus_major_plus_migration_ok(self):
        changes = [Change("m", "breaking", "Removed class 'X'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(2, 0, 0),
            {"0001_old.py"}, {"0001_old.py", "0002_new.py"},
        )
        assert violations == []

    def test_additive_plus_minor_ok(self):
        changes = [Change("m", "additive", "New class 'Y'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(1, 1, 0), set(), set(),
        )
        assert violations == []

    def test_additive_plus_patch_ok(self):
        changes = [Change("m", "additive", "New class 'Y'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(1, 0, 1), set(), set(),
        )
        assert violations == []

    def test_no_changes_no_version_change_ok(self):
        violations = check_guardrails(
            "m", [],
            Version(1, 0, 0), Version(1, 0, 0), set(), set(),
        )
        assert violations == []

    def test_major_plus_additive_only_should_be_ok(self):
        """Additive changes with a MAJOR bump — allowed (over-bumping)."""
        changes = [Change("m", "additive", "New class 'Y'")]
        violations = check_guardrails(
            "m", changes,
            Version(1, 0, 0), Version(2, 0, 0), set(), set(),
        )
        assert violations == []


# ===================================================================
# Live-instance diff
# ===================================================================


def test_diff_against_live_added_and_removed():
    current = {
        "A": {"@id": "A", "@type": "Class", "name": "xsd:string"},
        "B": {"@id": "B", "@type": "Class", "x": "xsd:integer"},
    }
    id_to_mod = {"A": "core", "B": "inbox"}
    fetched = [
        {"@type": "@context"},
        {"@id": "A", "@type": "Class", "name": "xsd:string"},
        {"@id": "C", "@type": "Class", "desc": "xsd:string"},
    ]

    changes = diff_against_live(current, id_to_mod, fetched)

    assert len(changes) == 2
    by_kind = {c.kind for c in changes}
    assert "additive" in by_kind  # B added
    assert "breaking" in by_kind  # C removed

    # "B" attributed to "inbox", "C" to "unknown" (default)
    b_change = next(c for c in changes if "'B'" in c.description)
    assert b_change.module == "inbox"
    c_change = next(c for c in changes if "'C'" in c.description)
    assert c_change.module == "unknown"


def test_diff_against_live_property_changed():
    current = {
        "A": {"@id": "A", "@type": "Class", "name": "xsd:string"},
    }
    id_to_mod = {"A": "core"}
    fetched = [
        {"@type": "@context"},
        {"@id": "A", "@type": "Class", "name": "xsd:integer"},
    ]

    changes = diff_against_live(current, id_to_mod, fetched)
    assert len(changes) == 1
    assert changes[0].kind == "breaking"
    assert changes[0].module == "core"
    assert "range/type" in changes[0].description


def test_diff_against_live_no_differences():
    current = {
        "A": {"@id": "A", "@type": "Class", "name": "xsd:string"},
    }
    id_to_mod = {"A": "core"}
    fetched = [
        {"@type": "@context"},
        {"@id": "A", "@type": "Class", "name": "xsd:string"},
    ]

    changes = diff_against_live(current, id_to_mod, fetched)
    assert changes == []
