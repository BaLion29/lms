"""Tests for the schema module composer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lms_schema.composer import (
    compose,
    CycleError,
    L1Error,
    L2Error,
    DuplicateIdError,
    DepMismatchError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_module(
    base: Path,
    name: str,
    version: str = "1.0.0",
    depends_on: list[dict[str, str]] | None = None,
    exports: list[str] | None = None,
    description: str = "Test module",
    classes: list[dict] | None = None,
    context: dict | None = None,
) -> Path:
    """Create a minimal schema module directory tree under *base*."""
    mod_dir = base / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "depends_on": depends_on if depends_on is not None else [],
        "exports": exports if exports is not None else [],
        "description": description,
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    if classes is not None:
        (mod_dir / "schema.json").write_text(json.dumps(classes))
    if context is not None:
        (mod_dir / "context.json").write_text(json.dumps(context))
    return mod_dir


def _core_context() -> dict:
    return {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}


def _core_classes() -> list[dict]:
    return [
        {"@abstract": [], "@id": "Source", "@type": "Class"},
        {"@abstract": [], "@id": "Context", "@type": "Class"},
    ]


def _make_core(base: Path, version: str = "1.0.0") -> Path:
    return _make_module(
        base,
        "core",
        version=version,
        exports=["Source", "Context"],
        classes=_core_classes(),
        context=_core_context(),
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        classes=[{"@id": "Foo", "@type": "Class", "@inherits": "Source", "name": "xsd:string"}],
    )
    _make_module(
        tmp_path,
        "m2",
        exports=["Bar"],
        classes=[{"@id": "Bar", "@type": "Class", "@inherits": "Source", "label": "xsd:string"}],
    )

    r1 = compose(tmp_path)
    r2 = compose(tmp_path)

    assert json.dumps(r1.composed_schema) == json.dumps(r2.composed_schema)
    assert r1.modules == r2.modules


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def test_cycle_detection(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(tmp_path, "a", exports=["A"], depends_on=[{"name": "b", "range": ">=1.0.0"}],
                 classes=[{"@id": "A", "@type": "Class"}])
    _make_module(tmp_path, "b", exports=["B"], depends_on=[{"name": "a", "range": ">=1.0.0"}],
                 classes=[{"@id": "B", "@type": "Class"}])

    with pytest.raises(CycleError) as exc:
        compose(tmp_path)
    assert "Cycle" in str(exc.value)


# ---------------------------------------------------------------------------
# Dependency range mismatch
# ---------------------------------------------------------------------------


def test_dep_range_mismatch(tmp_path: Path) -> None:
    _make_core(tmp_path, version="0.9.0")

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        depends_on=[{"name": "core", "range": ">=1.0.0"}],
        classes=[{"@id": "Foo", "@type": "Class"}],
    )

    with pytest.raises(DepMismatchError) as exc:
        compose(tmp_path)
    assert ">=1.0.0" in str(exc.value)
    assert "0.9.0" in str(exc.value)


# ---------------------------------------------------------------------------
# Duplicate @id
# ---------------------------------------------------------------------------


def test_duplicate_id(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(tmp_path, "m1", exports=["Foo"],
                 classes=[{"@id": "Foo", "@type": "Class"}])
    _make_module(tmp_path, "m2", exports=["Bar"],
                 classes=[{"@id": "Foo", "@type": "Class"}])

    with pytest.raises(DuplicateIdError) as exc:
        compose(tmp_path)
    assert "Foo" in str(exc.value)


# ---------------------------------------------------------------------------
# L1: non-core @abstract
# ---------------------------------------------------------------------------


def test_non_core_abstract_rejected(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Bad"],
        classes=[{"@abstract": [], "@id": "Bad", "@type": "Class"}],
    )

    with pytest.raises(L1Error) as exc:
        compose(tmp_path)
    assert "abstract" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# L1: non-core @context
# ---------------------------------------------------------------------------


def test_non_core_context_rejected(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        classes=[
            {"@id": "Foo", "@type": "Class"},
            {"@type": "@context", "@base": "x", "@schema": "y"},
        ],
    )

    with pytest.raises(L1Error) as exc:
        compose(tmp_path)
    assert "@context" in str(exc.value)


# ---------------------------------------------------------------------------
# L2: reference to non-exported class of a declared dependency
# ---------------------------------------------------------------------------


def test_l2_non_exported_class_of_dep(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        version="1.0.0",
        exports=["Exported"],
        classes=[
            {"@id": "Exported", "@type": "Class"},
            {"@id": "Internal", "@type": "Class"},
        ],
    )
    _make_module(
        tmp_path,
        "m2",
        version="1.0.0",
        depends_on=[{"name": "m1", "range": ">=1.0.0"}],
        exports=["Bar"],
        classes=[{"@id": "Bar", "@type": "Class", "ref": "Internal"}],
    )

    with pytest.raises(L2Error) as exc:
        compose(tmp_path)
    assert "Internal" in str(exc.value)
    assert "m1" in str(exc.value)


# ---------------------------------------------------------------------------
# L2: reference to class from undeclared module
# ---------------------------------------------------------------------------


def test_l2_undeclared_dep_reference(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        version="1.0.0",
        exports=["Foo"],
        classes=[{"@id": "Foo", "@type": "Class"}],
    )
    _make_module(
        tmp_path,
        "m2",
        version="1.0.0",
        exports=["Bar"],
        classes=[{"@id": "Bar", "@type": "Class", "ref": "Foo"}],
    )

    with pytest.raises(L2Error) as exc:
        compose(tmp_path)
    assert "Foo" in str(exc.value)
    assert "m2" in str(exc.value)
    assert "m1" in str(exc.value)


# ---------------------------------------------------------------------------
# Topological sort is deterministic (alphabetical tie-break)
# ---------------------------------------------------------------------------


def test_topo_deterministic_alphabetical(tmp_path: Path) -> None:
    _make_core(tmp_path)

    # a and b both depend only on core → both ready at start, a should come first
    _make_module(tmp_path, "a", exports=["A"],
                 classes=[{"@id": "A", "@type": "Class"}])
    _make_module(tmp_path, "b", exports=["B"],
                 classes=[{"@id": "B", "@type": "Class"}])

    result = compose(tmp_path)
    names = [m.name for m in result.modules]
    assert names[0] == "core"
    assert names.index("a") < names.index("b")


# ---------------------------------------------------------------------------
# Equivalence test — composed matches the monolithic schema
# ---------------------------------------------------------------------------

MONOLITHIC_PATH = Path(__file__).parents[3] / "services" / "ingestd" / "schema" / "schema.json"
MODULES_DIR = Path(__file__).parents[3] / "schema" / "modules"


def _normalize(schema_array: list[dict]) -> tuple[dict, dict[str, dict]]:
    """Split a schema array into (context, classes_by_id).

    The canonical JSON of each class object is used as the value so that
    key-order differences within a class do not cause false mismatches.
    """
    import json as _json
    context = None
    classes: dict[str, dict] = {}
    for obj in schema_array:
        if obj.get("@type") == "@context":
            context = obj
            continue
        cid = obj["@id"]
        # Canonical-JSON representation as a string for byte-exact comparison
        canonical = _json.dumps(obj, sort_keys=True, separators=(",", ":"))
        classes[cid] = _json.loads(canonical)
    return context, classes


def test_equivalence_with_monolithic() -> None:
    """The composed schema must be semantically identical to the monolithic one."""
    if not MONOLITHIC_PATH.is_file():
        pytest.skip("Monolithic schema file not found")

    # Load and normalize monolithic
    mono_raw = json.loads(MONOLITHIC_PATH.read_text())
    mono_ctx, mono_classes = _normalize(mono_raw)

    # Compose and normalize
    result = compose(MODULES_DIR)
    comp_ctx, comp_classes = _normalize(result.composed_schema)

    # Context must match
    assert comp_ctx == mono_ctx, "Context object mismatch"

    # Same set of @ids
    assert set(comp_classes.keys()) == set(mono_classes.keys()), (
        f"@id set mismatch: "
        f"only in composed={set(comp_classes) - set(mono_classes)}, "
        f"only in monolithic={set(mono_classes) - set(comp_classes)}"
    )

    # Each class object must be byte-exact (via canonical JSON)
    for cid, mono_cls in mono_classes.items():
        comp_cls = comp_classes[cid]
        assert comp_cls == mono_cls, f"Mismatch for class '{cid}'"
