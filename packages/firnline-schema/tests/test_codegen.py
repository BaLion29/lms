"""Tests for the schema codegen module."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from firnline_schema.codegen import generate, schema_checksum, write_generated, GENERATED_MARKER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_composed_schema() -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Return a tiny composed schema, class-to-module mapping, and module-to-target mapping."""
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
    module_to_target = {
        "core": "firnline_core.generated.core",
        "testmod": "firnline_core.generated.testmod",
    }
    return schema, class_to_module, module_to_target


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism(tmp_path: Path):
    """Same input → byte-identical files."""
    schema, class_to_module, module_to_target = _mini_composed_schema()
    checksum = schema_checksum(schema)

    files1 = generate(schema, class_to_module, module_to_target, checksum)
    files2 = generate(schema, class_to_module, module_to_target, checksum)

    assert files1 == files2


# ---------------------------------------------------------------------------
# Abstract classes not generated
# ---------------------------------------------------------------------------


def test_abstract_classes_not_generated():
    """Abstract classes (Source, Context etc.) should NOT appear in generated output."""
    schema, class_to_module, module_to_target = _mini_composed_schema()
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

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
    module_to_target = {
        "core": "firnline_core.generated.core",
        "testmod": "firnline_core.generated.testmod",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

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
    module_to_target = {
        "core": "firnline_core.generated.core",
        "testmod": "firnline_core.generated.testmod",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

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
    module_to_target = {"testmod": "firnline_core.generated.testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

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
    module_to_target = {"core": "firnline_core.generated.core", "testmod": "firnline_core.generated.testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

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
    module_to_target = {"testmod": "firnline_core.generated.testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

    source = files["testmod.py"]

    # Both classes must have the omit comment
    assert "# coordinates (xdd:coordinate) omitted" in source
    assert "# coords (xdd:coordinate) omitted" in source
    # No actual field declarations for these
    assert "coordinates:" not in source.replace("# coordinates (xdd:coordinate) omitted", "")
    assert "coords:" not in source.replace("# coords (xdd:coordinate) omitted", "")


# ---------------------------------------------------------------------------
# xsd:decimal → float
# ---------------------------------------------------------------------------


def test_xsd_decimal_maps_to_float():
    """xsd:decimal should map to Python float."""
    schema = [
        {
            "@id": "Config",
            "@type": "Class",
            "confidence": "xsd:decimal",
        },
        {
            "@id": "Config2",
            "@type": "Class",
            "threshold": {"@class": "xsd:decimal", "@type": "Optional"},
        },
    ]
    class_to_module = {"Config": "testmod", "Config2": "testmod"}
    module_to_target = {"testmod": "firnline_core.generated.testmod"}
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

    source = files["testmod.py"]
    assert "confidence: float" in source
    assert "threshold: float | None = None" in source


# ---------------------------------------------------------------------------
# Absolute cross-target imports
# ---------------------------------------------------------------------------


def test_absolute_cross_target_imports():
    """Classes referencing types in a different target use absolute imports."""
    schema = [
        {"@abstract": [], "@id": "Entity", "@type": "Class", "created_at": "xsd:dateTime"},
        {
            "@id": "TaskSpec",
            "@type": "Class",
            "name": "xsd:string",
            "priority": {"@class": "xsd:integer", "@type": "Optional"},
        },
        {
            "@id": "Provenance",
            "@subdocument": [],
            "@type": "Class",
            "confidence": "xsd:decimal",
        },
        {
            "@id": "Task",
            "@inherits": "TaskSpec",
            "@type": "Class",
            "due_date": {"@class": "xsd:dateTime", "@type": "Optional"},
            "provenance": {"@class": "Provenance", "@type": "Optional"},
        },
    ]
    class_to_module = {
        "Entity": "core",
        "TaskSpec": "planning",
        "Provenance": "core",
        "Task": "routines",
    }
    module_to_target = {
        "core": "firnline_core.generated.core",
        "planning": "firnline_ext_planning.models",
        "routines": "firnline_ext_routines.models",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)

    routines_src = files.get("routines.py", "")
    # Provenance (subdocument) is a nested cross-target ref → absolute import
    assert "from firnline_core.generated.core import Provenance" in routines_src
    # Should NOT use relative imports
    assert "from ." not in routines_src

    # TaskSpec is referenced only via @inherits → fields are flattened, so no import needed.
    # But TaskSpec's own file should only have local imports.
    planning_src = files.get("planning.py", "")
    assert "from ." not in planning_src


# ---------------------------------------------------------------------------
# write_generated routes to per-target paths
# ---------------------------------------------------------------------------


def test_write_generated_per_target_routing(tmp_path: Path):
    """Each module's output goes to the filesystem path resolved from its models_target."""
    import sys

    schema = [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {
            "@id": "Foo",
            "@inherits": "Source",
            "@type": "Class",
            "name": "xsd:string",
        },
    ]
    class_to_module = {"Source": "core", "Foo": "testmod"}
    checksum = schema_checksum(schema)

    # Create a fake package structure on sys.path so importlib can resolve it.
    # Use a unique top-level name so we don't clash with real installed packages.
    pkg_root = tmp_path / "pkg"
    pkg_name = f"_test_{tmp_path.name}"
    top_dir = pkg_root / pkg_name
    fake_gen = top_dir / "generated"
    fake_gen.mkdir(parents=True)
    (top_dir / "__init__.py").write_text("")
    (fake_gen / "__init__.py").write_text(GENERATED_MARKER + "\n")
    sys.path.insert(0, str(pkg_root))

    try:
        module_to_target = {
            "core": f"{pkg_name}.generated.core",
            "testmod": f"{pkg_name}.generated.testmod",
        }
        paths = write_generated(schema, class_to_module, module_to_target, checksum)

        path_names = {p.name for p in paths}
        assert "core.py" in path_names
        assert "testmod.py" in path_names

        # core.py should be in the fake_gen dir
        core_path = next(p for p in paths if p.name == "core.py")
        assert core_path.parent == fake_gen

        # __init__.py should be regenerated since it had the marker
        assert any(p.name == "__init__.py" for p in paths)
    finally:
        sys.path.pop(0)


def test_write_generated_init_no_overwrite_on_handwritten(tmp_path: Path):
    """If __init__.py exists but doesn't start with the GENERATED marker, it stays untouched."""
    import sys

    schema = [
        {"@id": "Foo", "@type": "Class", "name": "xsd:string"},
    ]
    class_to_module = {"Foo": "testmod"}
    checksum = schema_checksum(schema)

    pkg_root = tmp_path / "pkg"
    pkg_name = f"_test2_{tmp_path.name}"
    top_dir = pkg_root / pkg_name
    fake_gen = top_dir / "generated"
    fake_gen.mkdir(parents=True)
    (top_dir / "__init__.py").write_text("")
    original_init = "# Hand-written init, do not touch\n"
    (fake_gen / "__init__.py").write_text(original_init)
    sys.path.insert(0, str(pkg_root))

    try:
        module_to_target = {"testmod": f"{pkg_name}.generated.testmod"}
        paths = write_generated(schema, class_to_module, module_to_target, checksum)

        # __init__.py should NOT be in the written paths
        assert not any(p.name == "__init__.py" for p in paths)
        # Content should be unchanged
        assert (fake_gen / "__init__.py").read_text() == original_init
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# models_import — cross-target imports use models_import instead of models_target
# ---------------------------------------------------------------------------


def test_cross_target_uses_models_import():
    """When models_import is set, cross-target imports use it, not models_target."""
    schema = [
        {"@abstract": [], "@id": "Entity", "@type": "Class", "created_at": "xsd:dateTime"},
        {
            "@id": "Provenance",
            "@subdocument": [],
            "@type": "Class",
            "confidence": "xsd:decimal",
        },
        {
            "@id": "Address",
            "@subdocument": [],
            "@type": "Class",
            "city": "xsd:string",
        },
        {
            "@id": "RoutineStep",
            "@inherits": "Entity",
            "@type": "Class",
            "provenance": {"@class": "Provenance", "@type": "Optional"},
            "addresses": {"@class": "Address", "@type": "List"},
        },
    ]
    class_to_module = {
        "Entity": "core",
        "Provenance": "core",
        "Address": "planning",
        "RoutineStep": "routines",
    }
    module_to_target = {
        "core": "firnline_core.generated.core",
        "planning": "firnline_ext_planning.models",
        "routines": "firnline_ext_routines.models",
    }
    module_to_import = {
        "core": "firnline_core.models",
        "planning": "firnline_ext_planning.models",
        "routines": "firnline_ext_routines.models",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum, module_to_import=module_to_import)

    routines_src = files["routines.py"]
    # Should import from firnline_core.models, not firnline_core.generated.core
    assert "from firnline_core.models import Provenance" in routines_src
    assert "from firnline_core.generated.core" not in routines_src
    # planning has no special models_import → uses models_target
    assert "from firnline_ext_planning.models import Address" in routines_src


def test_cross_target_fallback_when_no_models_import():
    """When module_to_import is None, fall back to module_to_target."""
    schema = [
        {"@abstract": [], "@id": "Entity", "@type": "Class", "created_at": "xsd:dateTime"},
        {
            "@id": "Provenance",
            "@subdocument": [],
            "@type": "Class",
            "confidence": "xsd:decimal",
        },
        {
            "@id": "RoutineStep",
            "@inherits": "Entity",
            "@type": "Class",
            "provenance": {"@class": "Provenance", "@type": "Optional"},
        },
    ]
    class_to_module = {
        "Entity": "core",
        "Provenance": "core",
        "RoutineStep": "routines",
    }
    module_to_target = {
        "core": "firnline_core.generated.core",
        "routines": "firnline_ext_routines.models",
    }
    checksum = schema_checksum(schema)
    files = generate(schema, class_to_module, module_to_target, checksum)  # no module_to_import

    routines_src = files["routines.py"]
    # Falls back to module_to_target
    assert "from firnline_core.generated.core import Provenance" in routines_src
