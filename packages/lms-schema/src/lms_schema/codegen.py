"""Schema → Pydantic model code generator.

Reads the composed schema (and meta mapping) and emits one Python module
per schema module with flattened Pydantic models.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema classification helpers
# ---------------------------------------------------------------------------

META_KEYS = {
    "@id", "@type", "@inherits", "@abstract", "@subdocument",
    "@key", "@oneOf", "@value",
}

XSD_XDD_PREFIXES = {"xsd", "xdd"}


def _is_builtin(name: str) -> bool:
    """Return True if *name* is an xsd: or xdd: primitive."""
    if ":" in name:
        return name.split(":", 1)[0] in XSD_XDD_PREFIXES
    return False


def _is_abstract(cls: dict[str, Any]) -> bool:
    """A class is abstract if it has an ``@abstract`` key (any value, including false)."""
    return "@abstract" in cls


def _is_subdocument(cls: dict[str, Any]) -> bool:
    """A class is a subdocument if it has ``@subdocument``."""
    return "@subdocument" in cls


def _is_enum(cls: dict[str, Any]) -> bool:
    return cls.get("@type") == "Enum"


def _is_class(cls: dict[str, Any]) -> bool:
    return cls.get("@type") == "Class"


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

PRIMITIVE_MAP: dict[str, str] = {
    "xsd:string": "str",
    "xsd:integer": "int",
    "xsd:boolean": "bool",
    "xsd:dateTime": "TdbDateTime",
    "xsd:duration": "str",
}


def _resolve_prop_type(
    prop_value: Any,
    class_id_to_module: dict[str, str],
    current_module: str,
    all_classes: dict[str, dict[str, Any]],
    in_oneof: bool = False,
    wrapper_type: str | None = None,
) -> tuple[str | None, bool]:
    """Return (python_type_string, is_nested_model) for a property value.

    *is_nested_model* is True when the type refers to a Pydantic model class
    (subdocument, @oneOf, or List of concrete class) that must be imported and nested.

    Returns (None, False) for xdd:coordinate — the caller should skip the field.
    """
    if isinstance(prop_value, str):
        # Plain class or primitive reference
        if _is_builtin(prop_value):
            if prop_value == "xdd:coordinate":
                return None, False  # signal: skip this field
            py_type = PRIMITIVE_MAP.get(prop_value, "str")
            return py_type, False

        # Class reference
        if prop_value in all_classes:
            cls_def = all_classes[prop_value]
            if _is_enum(cls_def):
                # Enum types are used as-is
                return prop_value, False
            if _is_subdocument(cls_def) or in_oneof:
                # Must be imported as model
                return prop_value, True
            elif _is_abstract(cls_def):
                # Abstract ref → str IRI
                return "str", False
            else:
                # Concrete non-subdocument ref → str IRI
                return "str", False
        # Unrecognised string — pass through as type name
        return prop_value, False

    if isinstance(prop_value, dict):
        wtype = prop_value.get("@type", wrapper_type or "")
        inner_class = prop_value.get("@class")

        # Resolve inner
        if isinstance(inner_class, dict):
            # Nested wrapper — recurse into inner's @class
            inner_type, nested = _resolve_prop_type(
                inner_class, class_id_to_module, current_module, all_classes, in_oneof,
                wrapper_type=wtype,
            )
        elif isinstance(inner_class, str):
            if _is_builtin(inner_class):
                if inner_class == "xdd:coordinate":
                    return None, False
                inner_type = PRIMITIVE_MAP.get(inner_class, "str")
                nested = False
            elif inner_class in all_classes:
                cls_def = all_classes[inner_class]
                if _is_enum(cls_def):
                    inner_type = inner_class
                    nested = False
                elif _is_subdocument(cls_def) or in_oneof:
                    inner_type = inner_class
                    nested = True
                elif _is_abstract(cls_def):
                    inner_type = "str"
                    nested = False
                else:
                    # Concrete class — check List vs Set for nesting decision
                    if wtype == "List":
                        # List of concrete class → nested models
                        inner_type = inner_class
                        nested = True
                    else:
                        # Set or Optional of concrete class → str IRI
                        inner_type = "str"
                        nested = False
            else:
                inner_type = inner_class  # enum or unknown
                nested = False
        else:
            inner_type = "str"
            nested = False

        if inner_type is None:
            return None, False

        if wtype in ("Set", "List"):
            return f"list[{inner_type}]", nested
        elif wtype == "Optional":
            return f"{inner_type} | None", nested
        else:
            # Plain wrapper or unknown — treat as the inner type
            return inner_type, nested

    return "str", False


def _is_optional(prop_value: Any) -> bool:
    """Check if a property has Optional wrapper."""
    if isinstance(prop_value, dict):
        return prop_value.get("@type") == "Optional"
    return False


def _has_default(prop_value: Any) -> bool:
    """Check if a property has a default (Set/List → default_factory=list; Optional → None)."""
    if isinstance(prop_value, dict):
        return prop_value.get("@type") in ("Set", "List", "Optional")
    return False


def _is_collection(prop_value: Any) -> bool:
    """Check if a property is Set or List."""
    if isinstance(prop_value, dict):
        return prop_value.get("@type") in ("Set", "List")
    return False


# ---------------------------------------------------------------------------
# Code generation helpers
# ---------------------------------------------------------------------------

def _field_default(prop_value: Any) -> str | None:
    """Return Field() expression for a property, or None for plain annotation."""
    if isinstance(prop_value, dict):
        if prop_value.get("@type") in ("Set", "List"):
            return "Field(default_factory=list)"
    return None


def _attr_name(key: str) -> str:
    """Convert a schema property name to a Python identifier."""
    return key


def _class_name(cls_id: str) -> str:
    """The Python class name is the @id."""
    return cls_id


def _build_fields(
    cls_def: dict[str, Any],
    class_id_to_module: dict[str, str],
    current_module: str,
    all_classes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the list of fields for a concrete class, flattening inheritance.

    Returns a list of dicts with keys: name, type, default, nested, skip_comment.
    """
    own_fields: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _add_fields(from_cls_def: dict[str, Any]) -> None:
        for key, val in from_cls_def.items():
            if key in META_KEYS:
                continue
            if key in own_fields:
                continue  # child overrides parent

            wtype = None
            if isinstance(val, dict):
                wtype = val.get("@type")

            py_type, is_nested = _resolve_prop_type(
                val, class_id_to_module, current_module, all_classes,
                in_oneof=("@oneOf" in from_cls_def),
                wrapper_type=wtype,
            )
            if py_type is None:
                # xdd:coordinate → add as a comment-only field
                own_fields[key] = {
                    "name": key,
                    "type": "SKIP",
                    "nested": False,
                    "optional": _is_optional(val),
                    "has_default": True,  # treat as optional for ordering
                    "is_collection": False,
                    "raw_value": val,
                    "skip_comment": f"# {key} (xdd:coordinate) omitted",
                }
                continue

            own_fields[key] = {
                "name": key,
                "type": py_type,
                "nested": is_nested,
                "optional": _is_optional(val),
                "has_default": _has_default(val),
                "is_collection": _is_collection(val),
                "raw_value": val,
                "skip_comment": None,
            }

    # Walk inheritance chain (flattened: parent first, then own)
    inherits = cls_def.get("@inherits")
    if inherits:
        if isinstance(inherits, str):
            inherits = [inherits]
        for parent_id in inherits:
            if parent_id in all_classes:
                _add_fields(all_classes[parent_id])

    _add_fields(cls_def)

    # Now handle @oneOf: add each branch as an optional field
    oneof = cls_def.get("@oneOf")
    if oneof and isinstance(oneof, dict):
        for prop_name, branch_ref in oneof.items():
            if prop_name in own_fields:
                continue
            if isinstance(branch_ref, str):
                py_type, is_nested = branch_ref, True  # @oneOf branches are nested models
                own_fields[prop_name] = {
                    "name": prop_name,
                    "type": f"{py_type} | None",
                    "nested": is_nested,
                    "optional": True,
                    "has_default": True,
                    "is_collection": False,
                    "raw_value": branch_ref,
                    "skip_comment": None,
                }

    # Convert to list, sorted: required first (alphabetical), then optional (alphabetical)
    result = []
    required = []
    optional = []
    for f in own_fields.values():
        if f["has_default"]:
            optional.append(f)
        else:
            required.append(f)

    required.sort(key=lambda f: f["name"])
    optional.sort(key=lambda f: f["name"])
    result.extend(required)
    result.extend(optional)
    return result


def _generate_module(
    module_name: str,
    classes: list[dict[str, Any]],
    all_classes: dict[str, dict[str, Any]],
    class_id_to_module: dict[str, str],
    lock_checksum: str,
) -> str:
    """Generate Python source for one module."""
    lines: list[str] = []
    L = lines.append

    L("# GENERATED by lms-schema codegen — do not edit")
    L(f"# Source lock checksum: {lock_checksum}")
    L("")

    # --- Collect imports ---
    from_imports: dict[str, set[str]] = {}  # module → set of names

    # Collect nested model refs
    nested_refs: set[str] = set()
    # Track which features are used
    needs_enum = False
    needs_model_validator = False
    needs_tdbdatetime = False

    enums: list[dict[str, Any]] = []
    concrete: list[dict[str, Any]] = []
    skipped_coords: list[tuple[str, str]] = []  # (class, field_name)

    for cls in classes:
        cid = cls.get("@id", "")
        if cls.get("@type") == "Enum":
            enums.append(cls)
            needs_enum = True
        elif _is_class(cls) and not _is_abstract(cls):
            concrete.append(cls)

    # First pass: determine all nested model references per concrete class
    class_fields: dict[str, list[dict[str, Any]]] = {}
    for cls_def in concrete:
        fields = _build_fields(cls_def, class_id_to_module, module_name, all_classes)
        class_fields[cls_def["@id"]] = fields
        for f in fields:
            if f["nested"]:
                nested_refs.add(f["type"].replace(" | None", "").replace("list[", "").rstrip("]"))
            if f["skip_comment"]:
                skipped_coords.append((cls_def["@id"], f["name"]))
            # Check if any field uses TdbDateTime
            if "TdbDateTime" in f.get("type", ""):
                needs_tdbdatetime = True
        if "@oneOf" in cls_def:
            needs_model_validator = True

    # Determine cross-module imports
    for ref in sorted(nested_refs):
        ref_module = class_id_to_module.get(ref, module_name)
        if ref_module != module_name:
            from_imports.setdefault(f".{ref_module}", set()).add(ref)

    # Base imports — always needed
    from_imports.setdefault("lms_core.base", set()).add("TdbDocument")
    if needs_tdbdatetime:
        from_imports["lms_core.base"].add("TdbDateTime")

    # Standard imports — only include what's needed
    has_any_classes = bool(concrete)
    has_any_exports = has_any_classes or enums

    if has_any_classes:
        L("from __future__ import annotations")
        L("")
        if needs_enum:
            L("from enum import StrEnum")
        L("from typing import Literal")
        L("")
        if needs_model_validator:
            L("from pydantic import Field, model_validator")
        else:
            L("from pydantic import Field")

        # from-imports
        for mod in sorted(from_imports):
            names = sorted(from_imports[mod])
            names_str = ", ".join(names)
            L(f"from {mod} import {names_str}")

        # Local nested imports (same module)
        local_nested = sorted(ref for ref in nested_refs if class_id_to_module.get(ref, module_name) == module_name)
        if local_nested:
            L("")
            L("# --- forward references for local nested types ---")
    elif enums:
        # Only enums, no classes
        L("from enum import StrEnum")
        L("")

    if not has_any_exports:
        L("")

    L("")
    L("")
    L("__all__ = [")

    # Export all concrete classes and enums
    all_exports = sorted([cls["@id"] for cls in enums] + [cls["@id"] for cls in concrete])
    for name in all_exports:
        L(f'    "{name}",')
    L("]")
    L("")

    # --- Generate enums ---
    if enums:
        L("# ---------------------------------------------------------------------------")
        L("# Enums")
        L("# ---------------------------------------------------------------------------")
        L("")
        for enum_def in enums:
            values: list[str] = enum_def.get("@value", [])
            eid = enum_def["@id"]
            L(f"class {_class_name(eid)}(StrEnum):")
            for v in values:
                member_name = v.upper()
                L(f'    {member_name} = "{v}"')
            L("")
            L("")

    # --- Generate models ---
    for cls_def in concrete:
        cid = cls_def["@id"]
        fields = class_fields[cid]
        has_oneof = "@oneOf" in cls_def

        L("# ---------------------------------------------------------------------------")
        if _is_subdocument(cls_def):
            L(f"# {cid} — @subdocument")
            L("# ---------------------------------------------------------------------------")
        else:
            L(f"# {cid}")
            L("# ---------------------------------------------------------------------------")
        L("")

        # Optional class docstring
        L(f"class {_class_name(cid)}(TdbDocument):")

        # type_ literal
        L(f'    type_: Literal["{cid}"] = Field(alias="@type", default="{cid}")')

        # Fields
        for f in fields:
            if f["skip_comment"]:
                L(f"    {f['skip_comment']}")
                continue
            name = _attr_name(f["name"])
            py_type = f["type"]
            default = _field_default(f["raw_value"])
            has_default = f["has_default"]

            if default:
                L(f"    {name}: {py_type} = {default}")
            elif has_default:
                L(f"    {name}: {py_type} = None")
            else:
                L(f"    {name}: {py_type}")

        # @oneOf validator
        if has_oneof:
            oneof = cls_def.get("@oneOf", {})
            branch_names = sorted(oneof.keys())
            L("")
            L("    @model_validator(mode=\"after\")")
            L("    def _oneof_check(self):")
            set_checks = " + ".join(f"(1 if self.{n} is not None else 0)" for n in branch_names)
            L("        __tracebackhide__ = True")
            L(f"        if ({set_checks}) != 1:")
            names_str = ", ".join(f'"{n}"' for n in branch_names)
            L(f"            raise ValueError('Exactly one of ({names_str}) must be set')")
            L("        return self")

        L("")
        L("")

    return "\n".join(lines)


def _generate_init(module_exports: dict[str, list[str]]) -> str:
    """Generate __init__.py re-exporting from all module files.

    *module_exports* maps module_name → list of class/enum names.
    """
    lines: list[str] = []
    L = lines.append

    L("# GENERATED by lms-schema codegen — do not edit")
    L('"""Generated LMS document models."""')
    L("")
    L("# ---------------------------------------------------------------------------")
    L("# Re-exports from generated module files")
    L("# ---------------------------------------------------------------------------")
    L("")

    all_names: list[str] = []

    for mod_name in sorted(module_exports):
        exports = sorted(module_exports[mod_name])
        if not exports:
            continue
        L(f"from .{mod_name} import (")
        for name in exports:
            L(f"    {name},")
        L(")")
        all_names.extend(exports)

    L("")
    L("__all__ = [")
    for name in sorted(all_names):
        L(f'    "{name}",')
    L("]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    composed_schema: list[dict[str, Any]],
    class_id_to_module: dict[str, str],
    lock_checksum: str,
) -> dict[str, str]:
    """Generate Python source for each module and __init__.py.

    Returns dict mapping filename (e.g. "core.py") to source text.
    """
    # Index all classes by @id
    all_classes: dict[str, dict[str, Any]] = {}
    for obj in composed_schema:
        cid = obj.get("@id")
        if isinstance(cid, str) and obj.get("@type") != "@context":
            all_classes[cid] = obj

    # Group classes by module
    module_classes: dict[str, list[dict[str, Any]]] = {}
    for cid, cls_def in all_classes.items():
        mod = class_id_to_module.get(cid, "unknown")
        module_classes.setdefault(mod, []).append(cls_def)

    # Sort classes within each module by @id
    for mod in module_classes:
        module_classes[mod].sort(key=lambda c: c.get("@id", ""))

    result: dict[str, str] = {}
    module_exports: dict[str, list[str]] = {}

    for mod_name in sorted(module_classes):
        source = _generate_module(
            mod_name,
            module_classes[mod_name],
            all_classes,
            class_id_to_module,
            lock_checksum,
        )
        result[f"{mod_name}.py"] = source
        # Collect export names
        exports = []
        for cls in module_classes[mod_name]:
            cid = cls.get("@id", "")
            if cls.get("@type") in ("Class", "Enum"):
                if cls.get("@type") == "Enum" or not _is_abstract(cls):
                    exports.append(cid)
        module_exports[mod_name] = exports

    # Generate __init__.py
    result["__init__.py"] = _generate_init(module_exports)

    return result


def write_generated(
    out_dir: Path,
    composed_schema: list[dict[str, Any]],
    class_id_to_module: dict[str, str],
    lock_checksum: str,
) -> list[Path]:
    """Write generated files to *out_dir* and return the list of paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = generate(composed_schema, class_id_to_module, lock_checksum)

    written: list[Path] = []
    for filename, source in files.items():
        path = out_dir / filename
        path.write_text(source + "\n")
        written.append(path)

    return sorted(written)


# ---------------------------------------------------------------------------
# Deterministic checksum of composed schema
# ---------------------------------------------------------------------------


def schema_checksum(composed_schema: list[dict[str, Any]]) -> str:
    """Return a deterministic sha256 of the composed schema."""
    raw = json.dumps(composed_schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
