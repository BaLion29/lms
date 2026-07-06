"""Tests for the schema module composer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firnline_schema.composer import (
    compose,
    ComposerError,
    CycleError,
    L1Error,
    L2Error,
    DuplicateIdError,
    DepMismatchError,
    _extract_refs,
    fragment_checksum,
)
from firnline_schema.discovery import ModuleSource


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

    r1 = compose(tmp_path, include_entry_points=False)
    r2 = compose(tmp_path, include_entry_points=False)

    assert json.dumps(r1.composed_schema) == json.dumps(r2.composed_schema)
    assert r1.modules == r2.modules


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def test_cycle_detection(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "a",
        exports=["A"],
        depends_on=[{"name": "b", "range": ">=1.0.0"}],
        classes=[{"@id": "A", "@type": "Class"}],
    )
    _make_module(
        tmp_path,
        "b",
        exports=["B"],
        depends_on=[{"name": "a", "range": ">=1.0.0"}],
        classes=[{"@id": "B", "@type": "Class"}],
    )

    with pytest.raises(CycleError) as exc:
        compose(tmp_path, include_entry_points=False)
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
        compose(tmp_path, include_entry_points=False)
    assert ">=1.0.0" in str(exc.value)
    assert "0.9.0" in str(exc.value)


# ---------------------------------------------------------------------------
# Duplicate @id
# ---------------------------------------------------------------------------


def test_duplicate_id(tmp_path: Path) -> None:
    _make_core(tmp_path)

    _make_module(tmp_path, "m1", exports=["Foo"], classes=[{"@id": "Foo", "@type": "Class"}])
    _make_module(tmp_path, "m2", exports=["Bar"], classes=[{"@id": "Foo", "@type": "Class"}])

    with pytest.raises(DuplicateIdError) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "Foo" in str(exc.value)


# ---------------------------------------------------------------------------
# L1: non-core @abstract
# ---------------------------------------------------------------------------


def test_non_core_abstract_allowed(tmp_path: Path) -> None:
    """Non-core modules may define abstract classes (revised L1)."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Bad"],
        classes=[{"@abstract": [], "@id": "Bad", "@type": "Class"}],
    )

    result = compose(tmp_path, include_entry_points=False)
    # Must not raise L1Error — abstracts in non-core modules are now allowed
    names = [m.name for m in result.modules]
    assert "m1" in names


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
        compose(tmp_path, include_entry_points=False)
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
        compose(tmp_path, include_entry_points=False)
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
        compose(tmp_path, include_entry_points=False)
    assert "Foo" in str(exc.value)
    assert "m2" in str(exc.value)
    assert "m1" in str(exc.value)


# ---------------------------------------------------------------------------
# Topological sort is deterministic (alphabetical tie-break)
# ---------------------------------------------------------------------------


def test_topo_deterministic_alphabetical(tmp_path: Path) -> None:
    _make_core(tmp_path)

    # a and b both depend only on core → both ready at start, a should come first
    _make_module(tmp_path, "a", exports=["A"], classes=[{"@id": "A", "@type": "Class"}])
    _make_module(tmp_path, "b", exports=["B"], classes=[{"@id": "B", "@type": "Class"}])

    result = compose(tmp_path, include_entry_points=False)
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

    Asserts exactly one @context object is present on each side.
    """
    import json as _json

    contexts: list[dict] = [obj for obj in schema_array if obj.get("@type") == "@context"]
    assert len(contexts) == 1, f"Expected exactly one @context object, found {len(contexts)}"
    context = contexts[0]
    classes: dict[str, dict] = {}
    for obj in schema_array:
        if obj.get("@type") == "@context":
            continue
        cid = obj["@id"]
        # Canonical-JSON representation as a string for byte-exact comparison
        canonical = _json.dumps(obj, sort_keys=True, separators=(",", ":"))
        classes[cid] = _json.loads(canonical)
    return context, classes


# Allowed extra classes in composed schema that the monolithic schema
# does not contain (registry classes added in core 1.1.0).
_ALLOWED_EXTRAS = {"SchemaModule", "SchemaMigration", "ExternalRef"}


def test_equivalence_with_monolithic() -> None:
    """Monolithic schema must be a subset of composed; extra classes must be only registry."""
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

    # Monolithic must be a subset of composed
    only_in_composed = set(comp_classes.keys()) - set(mono_classes.keys())
    only_in_monolithic = set(mono_classes.keys()) - set(comp_classes.keys())

    # No classes should exist in monolithic that are missing from composed
    assert not only_in_monolithic, f"Classes in monolithic but not in composed: {only_in_monolithic}"

    # Extra classes in composed must be exactly the allowed registry classes
    assert only_in_composed == _ALLOWED_EXTRAS, (
        f"Unexpected extra classes in composed: {only_in_composed} (allowed extras: {_ALLOWED_EXTRAS})"
    )

    # Each shared class must be byte-exact (via canonical JSON)
    for cid, mono_cls in mono_classes.items():
        comp_cls = comp_classes[cid]
        assert comp_cls == mono_cls, f"Mismatch for class '{cid}'"

    # Extension modules must be present with pkg: source prefix
    extension_modules = {"inbox", "places", "routines", "people", "planning", "reminders"}
    repo_modules = {"core", "triggers"}
    module_names = {m.name for m in result.modules}
    for ext_name in extension_modules:
        assert ext_name in module_names, (
            f"Expected extension module '{ext_name}' is missing from composed modules. "
            f"Present: {module_names}. Is the extension installed and discoverable?"
        )
        ext_info = next(m for m in result.modules if m.name == ext_name)
        assert ext_info.source is not None and ext_info.source.startswith("pkg:"), (
            f"Extension module '{ext_name}' has source {ext_info.source!r}, "
            f"expected a 'pkg:' prefix (installable extension)."
        )
    for repo_name in repo_modules:
        assert repo_name in module_names, f"Expected repo module '{repo_name}' is missing from composed modules."
        repo_info = next(m for m in result.modules if m.name == repo_name)
        assert repo_info.source is not None and repo_info.source.startswith("repo:"), (
            f"Repo module '{repo_name}' has source {repo_info.source!r}, expected a 'repo:' prefix."
        )


# ---------------------------------------------------------------------------
# Finding 1: exports validation — reject bogus exports
# ---------------------------------------------------------------------------


def test_exports_must_be_defined(tmp_path: Path) -> None:
    """Exports must reference an @id actually defined in the module's schema.json."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Ghost"],  # not defined
        classes=[{"@id": "Real", "@type": "Class"}],
    )

    with pytest.raises(ComposerError) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "m1" in str(exc.value)
    assert "Ghost" in str(exc.value)


def test_enum_can_be_exported(tmp_path: Path) -> None:
    """Enum @ids are valid exports (enums are module-private by default but exportable)."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["MyEnum"],
        classes=[{"@id": "MyEnum", "@type": "Enum", "@value": ["a", "b"]}],
    )

    result = compose(tmp_path, include_entry_points=False)
    names = [m.name for m in result.modules]
    assert "m1" in names


def test_valid_exports_no_error(tmp_path: Path) -> None:
    """Valid exports that match defined @ids should compose cleanly."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        classes=[{"@id": "Foo", "@type": "Class"}],
    )

    result = compose(tmp_path, include_entry_points=False)
    assert any(m.name == "m1" for m in result.modules)


# ---------------------------------------------------------------------------
# Finding 3: _extract_refs — nested wrapper recursion
# ---------------------------------------------------------------------------


def test_extract_refs_nested_wrapper() -> None:
    """When @class is itself a dict (nested wrapper), recurse to find inner refs."""
    cls = {
        "@id": "Test",
        "@type": "Class",
        "prop": {"@class": {"@class": "InnerRef", "@type": "Optional"}, "@type": "Set"},
    }
    refs = _extract_refs(cls)
    assert "InnerRef" in refs


# ---------------------------------------------------------------------------
# Finding 4: @oneOf — list-of-dicts and wrapper values
# ---------------------------------------------------------------------------


def test_extract_refs_oneof_list_of_dicts() -> None:
    """@oneOf as a list of wrapper-dicts should extract class refs."""
    cls = {
        "@id": "Test",
        "@type": "Class",
        "@oneOf": [
            {"@class": "A", "@type": "Optional"},
            {"@class": "B", "@type": "Set"},
        ],
    }
    refs = _extract_refs(cls)
    assert "A" in refs
    assert "B" in refs


def test_extract_refs_oneof_wrapper_dict() -> None:
    """@oneOf as a single wrapper dict should extract its @class (recursively)."""
    cls = {
        "@id": "Test",
        "@type": "Class",
        "@oneOf": {"@class": "Inner", "@type": "Set"},
    }
    refs = _extract_refs(cls)
    assert "Inner" in refs


# ---------------------------------------------------------------------------
# Finding 6: fragment_checksum
# ---------------------------------------------------------------------------


def test_fragment_checksum_deterministic() -> None:
    """fragment_checksum must be deterministic for the same parsed array."""
    frag = [{"@id": "A"}, {"@id": "B"}]
    assert fragment_checksum(frag) == fragment_checksum(frag)

    # Order in the original array matters (it's the raw fragment)
    frag2 = [{"@id": "B"}, {"@id": "A"}]
    assert fragment_checksum(frag) != fragment_checksum(frag2)


# ---------------------------------------------------------------------------
# Finding 7: @context in core's schema.json is rejected
# ---------------------------------------------------------------------------


def test_core_context_in_schema_json_rejected(tmp_path: Path) -> None:
    """Core's @context must live in context.json, not schema.json."""
    mod_dir = tmp_path / "core"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "core",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "core",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "context.json").write_text(json.dumps(_core_context()))
    # Put a @context entry in schema.json — this should be rejected
    (mod_dir / "schema.json").write_text(
        json.dumps(
            [
                {"@abstract": [], "@id": "Source", "@type": "Class"},
                {"@type": "@context"},
            ]
        )
    )

    with pytest.raises(L1Error) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "@context" in str(exc.value)
    assert "core" in str(exc.value)


# ---------------------------------------------------------------------------
# Finding 8: @abstract with value false (or any value) is still abstract
# ---------------------------------------------------------------------------


def test_abstract_marker_outside_core_allowed(tmp_path: Path) -> None:
    """Abstract markers (key presence) allowed outside core under revised L1."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Bad"],
        classes=[{"@abstract": False, "@id": "Bad", "@type": "Class"}],
    )

    result = compose(tmp_path, include_entry_points=False)
    names = [m.name for m in result.modules]
    assert "m1" in names


# ---------------------------------------------------------------------------
# Triggers relocation: repo-discovered module
# ---------------------------------------------------------------------------


def test_triggers_discovered_from_repo() -> None:
    """compose() over schema/modules (no entry points) discovers triggers from repo source."""
    result = compose(MODULES_DIR, include_entry_points=False)
    names = [m.name for m in result.modules]
    assert names.count("triggers") == 1

    triggers_info = next(m for m in result.modules if m.name == "triggers")
    assert triggers_info.source == "repo:triggers"

    # Verify triggers classes are in the composed schema
    ids = {c.get("@id") for c in result.composed_schema if "@id" in c}
    assert "Trigger" in ids
    assert "ScheduleTrigger" in ids
    assert "RelativeTrigger" in ids


def test_routines_without_reminders_resolves_triggers() -> None:
    """Compose with repo modules + routines/planning/places (no reminders) resolves triggers dep."""
    _EXT_DIR = Path(__file__).parents[3] / "extensions"

    entry_point_modules: dict[str, ModuleSource] = {
        "places": ModuleSource(
            name="places",
            path=_EXT_DIR / "firnline-ext-places" / "src" / "firnline_ext_places",
            origin="pkg:test-places",
        ),
        "planning": ModuleSource(
            name="planning",
            path=_EXT_DIR / "firnline-ext-planning" / "src" / "firnline_ext_planning",
            origin="pkg:test-planning",
        ),
        "routines": ModuleSource(
            name="routines",
            path=_EXT_DIR / "firnline-ext-routines" / "src" / "firnline_ext_routines",
            origin="pkg:test-routines",
        ),
    }

    result = compose(MODULES_DIR, include_entry_points=True, entry_point_modules=entry_point_modules)

    names = {m.name for m in result.modules}
    assert "triggers" in names
    assert "routines" in names
    assert "planning" in names
    assert "places" in names
    assert "reminders" not in names
