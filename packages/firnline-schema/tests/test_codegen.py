"""Tests for the schema codegen module."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from firnline_schema.codegen import generate, schema_checksum, write_generated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_composed_schema() -> tuple[list[dict], dict[str, str]]:
    """Return a tiny composed schema and class-to-module mapping."""
    schema = [
        {
            "@abstract": [],
            "@id": "Source",
            "@type": "Class",
        },
        {
            "@id": "Foo",
            "@inherits": "Source",
            "@type": "Class",
            "name": "xsd:string",
            "description": {
                "@class": "xsd:string",
                "@type": "Optional",
            },
        },
        {
            "@id": "FooStatus",
            "@type": "Enum",
            "@value": ["active", "inactive"],
        },
    ]
    class_to_module = {
        "Source": "core",
        "Foo": "testmod",
        "FooStatus": "testmod",
    }
    return schema, class_to_module


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism(tmp_path: Path):
    """Same input → byte-identical files."""
    schema, class_to_module = _mini_composed_schema()
    checksum = schema_checksum(schema)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    write_generated(out1, schema, class_to_module, checksum)
    write_generated(out2, schema, class_to_module, checksum)

    files1 = sorted(out1.rglob("*.py"))
    files2 = sorted(out2.rglob("*.py"))
    assert len(files1) == len(files2)

    for f1, f2 in zip(files1, files2):
        assert f1.name == f2.name
        assert f1.read_bytes() == f2.read_bytes()


# ---------------------------------------------------------------------------
# Abstract classes not generated
# ---------------------------------------------------------------------------


def test_abstract_classes_not_generated():
    """Abstract classes (Source, Context etc.) should NOT appear in generated output."""
    schema, class_to_module = _mini_composed_schema()
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    for filename, source in files.items():
        # Source is abstract; should not appear as a class in any file
        assert "class Source(" not in source, f"Abstract class leaked into {filename}"


# ---------------------------------------------------------------------------
# Flattening correctness
# ---------------------------------------------------------------------------


def test_task_fields_flattened():
    """Task must inherit TaskSpec fields (name, description, etc.) + its own."""
    schema = [
        {"@abstract": [], "@id": "Remindable", "@type": "Class"},
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {
            "@id": "TaskSpec",
            "@type": "Class",
            "name": "xsd:string",
            "description": {"@class": "xsd:string", "@type": "Optional"},
            "priority": {"@class": "xsd:integer", "@type": "Optional"},
            "estimated_duration": {"@class": "xsd:integer", "@type": "Optional"},
            "required_context": {"@class": "Source", "@type": "Set"},
        },
        {
            "@id": "Task",
            "@inherits": ["Remindable", "Source", "TaskSpec"],
            "@type": "Class",
            "created_at": "xsd:dateTime",
            "due_date": {"@class": "xsd:dateTime", "@type": "Optional"},
            "status": "TaskStatus",
            "updated_at": "xsd:dateTime",
        },
        {
            "@id": "TaskStatus",
            "@type": "Enum",
            "@value": ["open", "done"],
        },
    ]
    class_to_module = {
        "Remindable": "core",
        "Source": "core",
        "TaskSpec": "testmod",
        "Task": "testmod",
        "TaskStatus": "testmod",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    task_source = files["testmod.py"]

    # Must inherit all TaskSpec fields
    assert "name: str" in task_source
    assert "description: str | None = None" in task_source
    assert "priority: int | None = None" in task_source
    assert "estimated_duration: int | None = None" in task_source
    assert "required_context: list[str] = Field(default_factory=list)" in task_source
    # Own fields
    assert "due_date: TdbDateTime | None = None" in task_source
    assert "status: TaskStatus" in task_source
    assert "created_at: TdbDateTime" in task_source
    assert "updated_at: TdbDateTime" in task_source


# ---------------------------------------------------------------------------
# oneOf validator behavior
# ---------------------------------------------------------------------------


def test_oneof_routine_step(tmp_path: Path):
    """RoutineStep oneOf validator: exactly one branch must be set."""
    schema = [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {
            "@id": "ActivitySpec",
            "@type": "Class",
            "name": "xsd:string",
        },
        {
            "@id": "TaskSpec",
            "@type": "Class",
            "name": "xsd:string",
        },
        {
            "@id": "RoutineStep",
            "@inherits": "Source",
            "@oneOf": {"activity": "ActivitySpec", "task": "TaskSpec"},
            "@type": "Class",
            "cadence_days": {"@class": "xsd:integer", "@type": "Optional"},
        },
    ]
    class_to_module = {
        "Source": "core",
        "ActivitySpec": "testmod",
        "TaskSpec": "testmod",
        "RoutineStep": "testmod",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    source = files["testmod.py"]

    # Write to a temp module and import properly
    import sys
    mod_dir = tmp_path / "testmod_pkg"
    mod_dir.mkdir()
    (mod_dir / "__init__.py").write_text("")
    (mod_dir / "testmod.py").write_text(source)

    sys.path.insert(0, str(tmp_path))
    try:
        from testmod_pkg.testmod import RoutineStep, ActivitySpec, TaskSpec
    finally:
        sys.path.pop(0)

    # Zero set → ValidationError
    with pytest.raises(ValidationError):
        RoutineStep()

    # Both set → ValidationError
    with pytest.raises(ValidationError):
        RoutineStep(activity=ActivitySpec(name="a"), task=TaskSpec(name="t"))

    # One set → ok
    step = RoutineStep(activity=ActivitySpec(name="a"))
    assert step.activity is not None
    assert step.task is None

    step2 = RoutineStep(task=TaskSpec(name="t"))
    assert step2.task is not None
    assert step2.activity is None

    # cadence_days is optional
    assert step2.cadence_days is None


# ---------------------------------------------------------------------------
# Enum generation
# ---------------------------------------------------------------------------


def test_enum_generation():
    """Enums must be StrEnum with UPPER_CASE member names and lowercase values."""
    schema = [
        {
            "@id": "MyEnum",
            "@type": "Enum",
            "@value": ["foo_bar", "baz"],
        },
        {
            "@id": "MyClass",
            "@type": "Class",
            "name": "xsd:string",
            "mode": "MyEnum",
        },
    ]
    class_to_module = {"MyEnum": "testmod", "MyClass": "testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    source = files["testmod.py"]

    # Enum class must exist
    assert "class MyEnum(StrEnum):" in source
    assert 'FOO_BAR = "foo_bar"' in source
    assert 'BAZ = "baz"' in source
    # Field type must use the enum class
    assert "mode: MyEnum" in source


# ---------------------------------------------------------------------------
# Subdocument nesting
# ---------------------------------------------------------------------------


def test_subdocument_nesting():
    """@subdocument classes are nested as model types, not IRI strings."""
    schema = [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {
            "@id": "Contact",
            "@subdocument": [],
            "@type": "Class",
            "email": {"@class": "xsd:string", "@type": "Optional"},
        },
        {
            "@id": "Person",
            "@inherits": "Source",
            "@type": "Class",
            "name": "xsd:string",
            "contact": {"@class": "Contact", "@type": "Optional"},
        },
    ]
    class_to_module = {"Source": "core", "Contact": "testmod", "Person": "testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    source = files["testmod.py"]

    # Person.contact must be Contact | None, not str | None
    assert "contact: Contact | None = None" in source


# ---------------------------------------------------------------------------
# xdd:coordinate skipped
# ---------------------------------------------------------------------------


def test_xdd_coordinate_skipped():
    """Fields typed xdd:coordinate must be omitted with a comment."""
    schema = [
        {
            "@id": "Location",
            "@type": "Class",
            "name": "xsd:string",
            "coordinates": {
                "@class": "xdd:coordinate",
                "@type": "Optional",
            },
        },
        {
            "@id": "Location2",
            "@type": "Class",
            "name": "xsd:string",
            "coords": "xdd:coordinate",
        },
    ]
    class_to_module = {"Location": "testmod", "Location2": "testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, checksum)

    source = files["testmod.py"]

    # Both classes must have the omit comment
    assert "# coordinates (xdd:coordinate) omitted" in source
    assert "# coords (xdd:coordinate) omitted" in source
    # No actual field declarations for these
    assert "coordinates:" not in source.replace("# coordinates (xdd:coordinate) omitted", "")
    assert "coords:" not in source.replace("# coords (xdd:coordinate) omitted", "")
