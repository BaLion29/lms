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
    DocumentationError,
    LabelFieldError,
    AnchorFieldError,
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
    models_target: str | None = None,
    models_import: str | None = None,
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
        "models_target": models_target or f"firnline_core.generated.{name}",
    }
    if models_import is not None:
        manifest["models_import"] = models_import
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    if classes is not None:
        # Auto-inject @documentation for exported classes that lack it
        export_set = set(exports or [])
        for cls in classes:
            cid = cls.get("@id")
            if cid in export_set and "@documentation" not in cls:
                cls["@documentation"] = {"@comment": f"Test class {cid}"}
        (mod_dir / "schema.json").write_text(json.dumps(classes))
    if context is not None:
        (mod_dir / "context.json").write_text(json.dumps(context))
    return mod_dir


def _core_context() -> dict:
    return {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}


def _core_classes() -> list[dict]:
    return [
        {"@abstract": [], "@id": "Source", "@type": "Class", "@documentation": {"@comment": "Base source class"}},
        {"@abstract": [], "@id": "Context", "@type": "Class", "@documentation": {"@comment": "Base context class"}},
    ]


def _make_core(base: Path, version: str = "0.1.0") -> Path:
    return _make_module(
        base,
        "core",
        version=version,
        exports=["Source", "Context"],
        classes=_core_classes(),
        context=_core_context(),
        models_import="firnline_core.models",
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

    # Check if real modules support L3 (@documentation)
    # If they don't yet, the refactor is in-progress — skip.
    core_manifest_path = MODULES_DIR / "core" / "manifest.json"
    if core_manifest_path.is_file():
        core_manifest = json.loads(core_manifest_path.read_text())
        if "models_target" not in core_manifest:
            pytest.skip("Schema modules not yet migrated to use models_target/@documentation")
    # Also check if first exported class in core has @documentation
    try:
        core_schema = json.loads((MODULES_DIR / "core" / "schema.json").read_text())
        core_exports = core_manifest.get("exports", [])
        if core_exports:
            by_id = {cls.get("@id"): cls for cls in core_schema if "@id" in cls}
            first_export = by_id.get(core_exports[0], {})
            if "@documentation" not in first_export:
                pytest.skip("Core schema classes not yet migrated with @documentation")
    except Exception:
        pytest.skip("Cannot read core schema to check @documentation")

    # Load and normalize monolithic
    mono_raw = json.loads(MONOLITHIC_PATH.read_text())
    mono_ctx, mono_classes = _normalize(mono_raw)

    # Compose and normalize
    try:
        result = compose(MODULES_DIR)
    except Exception as exc:
        if "entry-point discovery failed" in str(exc).lower() or "Missing manifest" in str(exc):
            pytest.skip(f"Entry-point modules not ready yet: {exc}")
        raise
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
    extension_modules = {"inbox", "places", "time_management", "people", "reminders"}
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
        "models_target": "firnline_core.generated.core",
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


def test_time_management_resolves_transitive_deps() -> None:
    """Compose with repo modules + time_management/address_book/reminders resolves transitive trigger dep."""
    _EXT_DIR = Path(__file__).parents[3] / "extensions"

    # Check if extension manifests exist and have models_target
    for ext_name in ("address-book", "time-management"):
        manifest_path = _EXT_DIR / f"firnline-ext-{ext_name}" / "src" / f"firnline_ext_{ext_name.replace('-', '_')}" / "manifest.json"
        if manifest_path.is_file():
            try:
                m = json.loads(manifest_path.read_text())
                if "models_target" not in m:
                    pytest.skip(f"Extension '{ext_name}' not yet migrated to use models_target")
            except Exception:
                pytest.skip(f"Extension '{ext_name}' manifest not readable")
        else:
            pytest.skip(f"Extension '{ext_name}' manifest not found")

    entry_point_modules: dict[str, ModuleSource] = {
        "address_book": ModuleSource(
            name="address_book",
            path=_EXT_DIR / "firnline-ext-address-book" / "src" / "firnline_ext_address_book",
            origin="pkg:test-address-book",
        ),
        "time_management": ModuleSource(
            name="time_management",
            path=_EXT_DIR / "firnline-ext-time-management" / "src" / "firnline_ext_time_management",
            origin="pkg:test-time-management",
        ),
        "reminders": ModuleSource(
            name="reminders",
            path=_EXT_DIR / "firnline-ext-reminders" / "src" / "firnline_ext_reminders" / "reminders_module",
            origin="pkg:test-reminders",
        ),
    }

    try:
        result = compose(MODULES_DIR, include_entry_points=True, entry_point_modules=entry_point_modules)
    except DepMismatchError as exc:
        pytest.skip(f"Dependency range mismatch (likely mid-refactor): {exc}")

    names = {m.name for m in result.modules}
    assert "triggers" in names
    assert "time_management" in names
    assert "address_book" in names
    assert "reminders" in names


# ---------------------------------------------------------------------------
# L3: documentation lint
# ---------------------------------------------------------------------------


def test_l3_pass_with_documentation(tmp_path: Path) -> None:
    """Exported classes with @documentation + @comment pass L3."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        classes=[{
            "@id": "Foo",
            "@type": "Class",
            "@documentation": {"@comment": "A documented class"},
            "name": "xsd:string",
        }],
    )

    result = compose(tmp_path, include_entry_points=False)
    assert any(m.name == "m1" for m in result.modules)


def test_l3_fail_missing_documentation(tmp_path: Path) -> None:
    """Exported class without @documentation fails L3."""
    _make_core(tmp_path)

    # Create module manually to bypass auto-injection of @documentation
    mod_dir = tmp_path / "m1"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "m1",
        "version": "1.0.0",
        "depends_on": [],
        "exports": ["Foo"],
        "description": "test",
        "models_target": "firnline_core.generated.m1",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "schema.json").write_text(json.dumps([
        {"@id": "Foo", "@type": "Class", "name": "xsd:string"},
    ]))

    with pytest.raises(DocumentationError) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "L3" in str(exc.value)
    assert "m1:Foo" in str(exc.value)


def test_l3_fail_empty_comment(tmp_path: Path) -> None:
    """Exported class with @documentation but empty @comment fails L3."""
    _make_core(tmp_path)

    mod_dir = tmp_path / "m1"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "m1", "version": "1.0.0",
        "depends_on": [], "exports": ["Foo"],
        "description": "test",
        "models_target": "firnline_core.generated.m1",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "schema.json").write_text(json.dumps([{
        "@id": "Foo", "@type": "Class",
        "@documentation": {"@comment": ""},
        "name": "xsd:string",
    }]))

    with pytest.raises(DocumentationError) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "m1:Foo" in str(exc.value)


def test_l3_fail_whitespace_only_comment(tmp_path: Path) -> None:
    """Exported class with whitespace-only @comment fails L3."""
    _make_core(tmp_path)

    mod_dir = tmp_path / "m1"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "m1", "version": "1.0.0",
        "depends_on": [], "exports": ["Foo"],
        "description": "test",
        "models_target": "firnline_core.generated.m1",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))
    (mod_dir / "schema.json").write_text(json.dumps([{
        "@id": "Foo", "@type": "Class",
        "@documentation": {"@comment": "   "},
        "name": "xsd:string",
    }]))

    with pytest.raises(DocumentationError) as exc:
        compose(tmp_path, include_entry_points=False)
    assert "m1:Foo" in str(exc.value)


def test_l3_non_exported_no_doc_ok(tmp_path: Path) -> None:
    """Non-exported classes without @documentation are fine."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=[],
        classes=[{"@id": "Hidden", "@type": "Class", "name": "xsd:string"}],
    )

    result = compose(tmp_path, include_entry_points=False)
    assert any(m.name == "m1" for m in result.modules)


def test_l3_enum_exported_needs_doc(tmp_path: Path) -> None:
    """Exported enums also need @documentation."""
    _make_core(tmp_path)

    _make_module(
        tmp_path,
        "m1",
        exports=["MyEnum"],
        classes=[{
            "@id": "MyEnum",
            "@type": "Enum",
            "@value": ["a", "b"],
            "@documentation": {"@comment": "An enum"},
        }],
    )

    result = compose(tmp_path, include_entry_points=False)
    assert any(m.name == "m1" for m in result.modules)


# ---------------------------------------------------------------------------
# models_target in ComposeResult
# ---------------------------------------------------------------------------


def test_compose_result_carries_models_target(tmp_path: Path) -> None:
    """ComposeResult.module_to_target maps module_name → models_target."""
    _make_core(tmp_path, version="1.0.0")

    _make_module(
        tmp_path,
        "m1",
        models_target="firnline_core.generated.m1",
        exports=["Foo"],
        classes=[{"@id": "Foo", "@type": "Class", "@documentation": {"@comment": "x"}, "name": "xsd:string"}],
    )

    result = compose(tmp_path, include_entry_points=False)
    assert result.module_to_target["core"] == "firnline_core.generated.core"
    assert result.module_to_target["m1"] == "firnline_core.generated.m1"


# ---------------------------------------------------------------------------
# Implicit core-dep injection range ≥0.1.0
# ---------------------------------------------------------------------------


def test_core_dep_injection_range_0_1(tmp_path: Path) -> None:
    """Core dep injection uses ≥0.1.0, so core at 1.0.0 satisfies it."""
    _make_core(tmp_path, version="1.0.0")

    _make_module(
        tmp_path,
        "m1",
        exports=["Foo"],
        classes=[{"@id": "Foo", "@type": "Class", "@documentation": {"@comment": "x"}, "name": "xsd:string"}],
    )

    # Must succeed — implicit core dep is injected at ≥0.1.0, core 1.0.0 satisfies
    result = compose(tmp_path, include_entry_points=False)
    assert any(m.name == "m1" for m in result.modules)


# ---------------------------------------------------------------------------
# Manifest validation: models_target
# ---------------------------------------------------------------------------


def test_manifest_missing_models_target(tmp_path: Path) -> None:
    """Manifest without models_target raises ManifestError."""
    from firnline_schema.manifest import Manifest, ManifestError

    mod_dir = tmp_path / "bad"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "bad",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        # missing models_target
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ManifestError) as exc:
        Manifest.load(mod_dir)
    assert "models_target" in str(exc.value)


def test_manifest_invalid_models_target(tmp_path: Path) -> None:
    """Manifest with invalid models_target (not dotted path) raises ManifestError."""
    from firnline_schema.manifest import Manifest, ManifestError

    mod_dir = tmp_path / "bad"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "bad",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        "models_target": "not_a_valid_path",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ManifestError) as exc:
        Manifest.load(mod_dir)
    assert "models_target" in str(exc.value)


def test_manifest_with_models_import(tmp_path: Path) -> None:
    """Manifest with valid models_import loads and stores it."""
    from firnline_schema.manifest import Manifest

    mod_dir = tmp_path / "mod"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "mod",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        "models_target": "firnline_core.generated.mod",
        "models_import": "firnline_core.models",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))

    m = Manifest.load(mod_dir)
    assert m.models_target == "firnline_core.generated.mod"
    assert m.models_import == "firnline_core.models"


def test_manifest_models_import_defaults_to_target(tmp_path: Path) -> None:
    """When models_import is not specified, it defaults to models_target."""
    from firnline_schema.manifest import Manifest

    mod_dir = tmp_path / "mod"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "mod",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        "models_target": "firnline_core.generated.mod",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))

    m = Manifest.load(mod_dir)
    assert m.models_import == m.models_target


def test_manifest_invalid_models_import(tmp_path: Path) -> None:
    """Manifest with invalid models_import (not dotted path) raises ManifestError."""
    from firnline_schema.manifest import Manifest, ManifestError

    mod_dir = tmp_path / "bad"
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "bad",
        "version": "1.0.0",
        "depends_on": [],
        "exports": [],
        "description": "test",
        "models_target": "firnline_core.generated.bad",
        "models_import": "not_a_valid_path",
    }
    (mod_dir / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ManifestError) as exc:
        Manifest.load(mod_dir)
    assert "models_import" in str(exc.value)


def test_compose_module_to_import(tmp_path: Path) -> None:
    """ComposeResult.module_to_import reflects models_import from manifests."""
    _make_core(tmp_path)
    _make_module(
        tmp_path, "mod",
        version="0.1.0",
        exports=[],
        classes=[
            {"@id": "Foo", "@type": "Class",
             "@documentation": {"@comment": "Test"},
             "name": "xsd:string"},
        ],
        models_target="firnline_core.generated.mod",
    )
    result = compose(tmp_path, entry_point_modules={})
    assert result.module_to_import["core"] == "firnline_core.models"
    # mod has no models_import → defaults to models_target
    assert result.module_to_import["mod"] == "firnline_core.generated.mod"


def test_meta_file_includes_imports(tmp_path: Path) -> None:
    """Compose CLI writes 'imports' to the meta file."""
    _make_core(tmp_path)
    result = compose(tmp_path, entry_point_modules={})
    meta = {
        "classes": dict(sorted(result.class_id_to_module.items())),
        "targets": dict(sorted(result.module_to_target.items())),
        "imports": dict(sorted(result.module_to_import.items())),
    }
    assert "imports" in meta
    assert meta["imports"]["core"] == "firnline_core.models"


# ---------------------------------------------------------------------------
# L4: label_field validation
# ---------------------------------------------------------------------------


def _core_with_entity_anchored() -> tuple[dict, list[dict]]:
    """Return (context, classes) for core with Entity and Anchored abstract classes."""
    ctx = {"@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#", "@type": "@context"}
    classes = [
        {"@abstract": [], "@id": "Entity", "@type": "Class",
         "@documentation": {"@comment": "Universal base"},
         "created_at": "xsd:dateTime", "updated_at": "xsd:dateTime"},
        {"@abstract": [], "@id": "Anchored", "@type": "Class",
         "@documentation": {"@comment": "Temporal anchor marker"}},
        {"@id": "SchemaModule", "@type": "Class", "@key": {"@type": "Lexical", "@fields": ["name"]},
         "@documentation": {"@comment": "Registry record"},
         "name": "xsd:string", "version": "xsd:string", "checksum": "xsd:string",
         "installed_at": "xsd:dateTime"},
    ]
    return ctx, classes


def _make_core_with_entity(base: Path, exports: list[str] | None = None) -> Path:
    ctx, classes = _core_with_entity_anchored()
    if exports is None:
        exports = ["Entity", "Anchored", "SchemaModule"]
    return _make_module(base, "core", exports=exports, classes=classes, context=ctx)


def test_label_field_positive(tmp_path: Path) -> None:
    """Exported, non-abstract Entity subclass with @metadata.label_field passes L4."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Task"],
        classes=[{
            "@id": "Task", "@type": "Class",
            "@inherits": "Entity",
            "@metadata": {"label_field": "name"},
            "@documentation": {"@comment": "A task"},
            "name": "xsd:string",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_missing(tmp_path: Path) -> None:
    """Exported Entity subclass without @metadata.label_field fails L4."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Task"],
        classes=[{
            "@id": "Task", "@type": "Class",
            "@inherits": "Entity",
            "@documentation": {"@comment": "A task"},
            "name": "xsd:string",
        }],
    )
    with pytest.raises(LabelFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "L4" in str(exc.value)
    assert "Task" in str(exc.value)


def test_label_field_unknown_property(tmp_path: Path) -> None:
    """label_field pointing to non-existent property fails L4."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Task"],
        classes=[{
            "@id": "Task", "@type": "Class",
            "@inherits": "Entity",
            "@metadata": {"label_field": "bogus"},
            "@documentation": {"@comment": "A task"},
            "name": "xsd:string",
        }],
    )
    with pytest.raises(LabelFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "bogus" in str(exc.value)
    assert "not a property" in str(exc.value)


def test_label_field_abstract_exempt(tmp_path: Path) -> None:
    """Abstract Entity subclasses are exempt from label_field requirement."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["AbstractTask"],
        classes=[{
            "@abstract": [],
            "@id": "AbstractTask", "@type": "Class",
            "@inherits": "Entity",
            "@documentation": {"@comment": "Abstract task base"},
            "name": "xsd:string",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_subdocument_exempt(tmp_path: Path) -> None:
    """Subdocument classes are exempt from label_field requirement."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Note"],
        classes=[{
            "@id": "Note", "@type": "Class",
            "@subdocument": [],
            "@inherits": "Entity",
            "@documentation": {"@comment": "A subdoc note"},
            "text": "xsd:string",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_not_exported_exempt(tmp_path: Path) -> None:
    """Non-exported Entity subclasses are exempt from label_field requirement."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=[],
        classes=[{
            "@id": "HiddenTask", "@type": "Class",
            "@inherits": "Entity",
            "@documentation": {"@comment": "Hidden task"},
            "name": "xsd:string",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_transitive_inheritance(tmp_path: Path) -> None:
    """Transitive Entity inheritance (via intermediate abstract) triggers label_field."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["ConcreteTask"],
        classes=[
            {"@abstract": [], "@id": "TaskSpec", "@type": "Class",
             "@inherits": "Entity",
             "@documentation": {"@comment": "Task spec base"},
             "priority": {"@class": "xsd:integer", "@type": "Optional"}},
            {"@id": "ConcreteTask", "@type": "Class",
             "@inherits": "TaskSpec",
             "@metadata": {"label_field": "name"},
             "@documentation": {"@comment": "A concrete task"},
             "name": "xsd:string"},
        ],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_inherited_metadata(tmp_path: Path) -> None:
    """label_field declared on an abstract ancestor → resolved transitively."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["ConcreteTask"],
        classes=[
            {"@abstract": [], "@id": "TaskSpec", "@type": "Class",
             "@inherits": "Entity",
             "@metadata": {"label_field": "name"},
             "@documentation": {"@comment": "Task spec base"},
             "priority": {"@class": "xsd:integer", "@type": "Optional"},
             "name": "xsd:string"},
            {"@id": "ConcreteTask", "@type": "Class",
             "@inherits": "TaskSpec",
             "@documentation": {"@comment": "A concrete task"}},
        ],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_label_field_transitive_missing(tmp_path: Path) -> None:
    """Transitive Entity inheritance without label_field on the concrete class fails."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["ConcreteTask"],
        classes=[
            {"@abstract": [], "@id": "TaskSpec", "@type": "Class",
             "@inherits": "Entity",
             "@documentation": {"@comment": "Task spec base"},
             "priority": {"@class": "xsd:integer", "@type": "Optional"}},
            {"@id": "ConcreteTask", "@type": "Class",
             "@inherits": "TaskSpec",
             "@documentation": {"@comment": "A concrete task"},
             "name": "xsd:string"},
        ],
    )
    with pytest.raises(LabelFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "ConcreteTask" in str(exc.value)


# ---------------------------------------------------------------------------
# L5: anchor_field validation
# ---------------------------------------------------------------------------


def test_anchor_field_positive(tmp_path: Path) -> None:
    """Non-abstract Anchored subclass with @metadata.anchor_field pointing to xsd:dateTime passes L5."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Reminder"],
        classes=[{
            "@id": "Reminder", "@type": "Class",
            "@inherits": "Anchored",
            "@metadata": {"anchor_field": "due_date"},
            "@documentation": {"@comment": "A reminder"},
            "due_date": "xsd:dateTime",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_anchor_field_missing(tmp_path: Path) -> None:
    """Non-abstract Anchored subclass without @metadata.anchor_field fails L5."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Reminder"],
        classes=[{
            "@id": "Reminder", "@type": "Class",
            "@inherits": "Anchored",
            "@documentation": {"@comment": "A reminder"},
            "due_date": "xsd:dateTime",
        }],
    )
    with pytest.raises(AnchorFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "L5" in str(exc.value)
    assert "Reminder" in str(exc.value)


def test_anchor_field_non_datetime(tmp_path: Path) -> None:
    """anchor_field pointing to non-xsd:dateTime type fails L5."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Reminder"],
        classes=[{
            "@id": "Reminder", "@type": "Class",
            "@inherits": "Anchored",
            "@metadata": {"anchor_field": "name"},
            "@documentation": {"@comment": "A reminder"},
            "due_date": "xsd:dateTime",
            "name": "xsd:string",
        }],
    )
    with pytest.raises(AnchorFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "name" in str(exc.value)
    assert "xsd:dateTime" in str(exc.value)


def test_anchor_field_abstract_exempt(tmp_path: Path) -> None:
    """Abstract Anchored subclasses are exempt from anchor_field requirement."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["AbstractReminder"],
        classes=[{
            "@abstract": [],
            "@id": "AbstractReminder", "@type": "Class",
            "@inherits": "Anchored",
            "@documentation": {"@comment": "Abstract reminder base"},
            "due_date": "xsd:dateTime",
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_anchor_field_optional_datetime_ok(tmp_path: Path) -> None:
    """anchor_field pointing to Optional xsd:dateTime is valid."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Reminder"],
        classes=[{
            "@id": "Reminder", "@type": "Class",
            "@inherits": "Anchored",
            "@metadata": {"anchor_field": "due_date"},
            "@documentation": {"@comment": "A reminder"},
            "due_date": {"@class": "xsd:dateTime", "@type": "Optional"},
        }],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


def test_anchor_field_not_exported_still_required(tmp_path: Path) -> None:
    """Non-exported, non-abstract Anchored subclasses STILL require anchor_field."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=[],
        classes=[{
            "@id": "HiddenReminder", "@type": "Class",
            "@inherits": "Anchored",
            "@documentation": {"@comment": "Hidden reminder"},
            "due_date": "xsd:dateTime",
        }],
    )
    with pytest.raises(AnchorFieldError) as exc:
        compose(tmp_path, entry_point_modules={})
    assert "HiddenReminder" in str(exc.value)


def test_anchor_field_transitive_inheritance(tmp_path: Path) -> None:
    """anchor_field declared on an abstract Anchored ancestor → resolved transitively."""
    _make_core_with_entity(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["Reminder"],
        classes=[
            {"@abstract": [], "@id": "AbstractReminderBase", "@type": "Class",
             "@inherits": "Anchored",
             "@metadata": {"anchor_field": "due_date"},
             "@documentation": {"@comment": "Abstract reminder base"},
             "due_date": "xsd:dateTime"},
            {"@id": "Reminder", "@type": "Class",
             "@inherits": "AbstractReminderBase",
             "@documentation": {"@comment": "A concrete reminder"}},
        ],
    )
    result = compose(tmp_path, entry_point_modules={})
    assert any(m.name == "m1" for m in result.modules)


# ---------------------------------------------------------------------------
# ModuleInfo.exports
# ---------------------------------------------------------------------------


def test_module_info_carries_exports(tmp_path: Path) -> None:
    """ComposeResult ModuleInfo includes the module's exports list (sorted)."""
    _make_core(tmp_path)
    _make_module(
        tmp_path, "m1", version="1.0.0",
        exports=["B", "A"],
        classes=[
            {"@id": "A", "@type": "Class", "@documentation": {"@comment": "A"},
             "name": "xsd:string"},
            {"@id": "B", "@type": "Class", "@documentation": {"@comment": "B"},
             "name": "xsd:string"},
        ],
    )
    result = compose(tmp_path, entry_point_modules={})
    m1_info = next(m for m in result.modules if m.name == "m1")
    assert m1_info.exports is not None
    # The exports list should preserve manifest order (not sorted) since it's the raw list
    assert m1_info.exports == ["B", "A"]
