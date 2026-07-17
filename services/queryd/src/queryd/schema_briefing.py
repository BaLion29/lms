"""Schema introspection and briefing for TerminusDB v12.0.6.

TerminusDB v12.0.6 exposes NO SDL — only GraphQL introspection JSON.
"""

from __future__ import annotations

from typing import Any

from firnline_core.tdb import TdbClient

# ---------------------------------------------------------------------------
# GraphQL introspection query
# ---------------------------------------------------------------------------

# _GraphQL_Full_Introspection_Query_ - no descriptions, no directives.
# Includes: types with name/kind/fields(name,args,type refs via ofType up to 5
# levels)/inputFields/enumValues.

_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      name
      kind
      fields {
        name
        args { name type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } } }
        type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } }
      }
      inputFields {
        name
        type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } }
      }
      enumValues { name }
    }
  }
}
"""


async def fetch_introspection(tdb: TdbClient) -> dict[str, Any]:
    """Run a standard introspection query via *tdb*.graphql.

    Returns the full ``{"__schema": ...}`` dict.
    """
    return await tdb.graphql(_INTROSPECTION_QUERY)


# ---------------------------------------------------------------------------
# Module registry helpers (capability awareness)
# ---------------------------------------------------------------------------


async def fetch_module_list(
    tdb: TdbClient,
    *,
    branch: str = "main",
) -> list[dict[str, Any]]:
    """Fetch ``SchemaModule`` docs from the in-database registry.

    Returns a list of module dicts (each has at least ``name`` and
    ``version``).  Raises ``TdbError`` if the registry is unavailable
    (e.g. before the modularisation rollout).
    """
    return await tdb.get_documents("SchemaModule", branch=branch)


# ---------------------------------------------------------------------------
# SDL-like schema summary (full, for get_schema_details tool)
# ---------------------------------------------------------------------------

# Kinds from the GraphQL spec
_SCALAR_KINDS = frozenset({"SCALAR"})
_OBJECT_KINDS = frozenset({"OBJECT", "INTERFACE", "UNION"})
_INPUT_OBJECT_KINDS = frozenset({"INPUT_OBJECT"})
_ENUM_KINDS = frozenset({"ENUM"})

# Introspection dunder types to skip
_SKIP_TYPES = frozenset(
    {
        "__Schema",
        "__Type",
        "__Field",
        "__InputValue",
        "__EnumValue",
        "__Directive",
        "__TypeKind",
        "__DirectiveLocation",
    }
)


def _unwrap_type(
    type_ref: dict[str, Any] | None, depth: int = 0
) -> dict[str, Any] | None:
    """Follow ``ofType`` chain up to *depth* levels."""
    if type_ref is None:
        return None
    if type_ref.get("kind") != "NON_NULL" and type_ref.get("kind") != "LIST":
        return type_ref
    if depth >= 6:
        return type_ref
    return _unwrap_type(type_ref.get("ofType"), depth + 1)


def _type_name(type_ref: dict[str, Any] | None) -> str:
    """Return a human-readable type string from an introspection type ref.

    Produces strings like ``String``, ``[Task!]!``, ``[String]``, etc.
    """
    if type_ref is None:
        return "Unknown"

    kind = type_ref.get("kind")

    if kind == "NON_NULL":
        return _type_name(type_ref.get("ofType")) + "!"
    elif kind == "LIST":
        return "[" + _type_name(type_ref.get("ofType")) + "]"
    else:
        return type_ref.get("name") or "Unknown"


def _field_type_str(field: dict[str, Any]) -> str:
    """Return the type string for a field (including list/non-null wrappers)."""
    return _type_name(field.get("type"))


def render_schema_summary(introspection: dict[str, Any]) -> str:
    """Render a compact SDL-like text from introspection JSON.

    Covers:

    * OBJECT types reachable from ``Query`` (skips introspection dunders,
      skips generated noise).
    * Input filter types (``*_Filter``, ``DateTimeFilter``, ``StringFilter``,
      ``*_Enum_Filter``).
    * Ordering input types.
    * All ENUM types with exact values.

    Excludes ``TerminusMutation`` entirely.
    """
    schema = introspection.get("__schema", introspection)
    type_list: list[dict[str, Any]] = schema.get("types", [])
    types_by_name: dict[str, dict[str, Any]] = {t["name"]: t for t in type_list}

    query_type_name = schema.get("queryType", {}).get("name", "Query")
    mutation_type_name = schema.get("mutationType", {}).get("name")

    lines: list[str] = []
    emitted: set[str] = set()

    # Helper to add a section header
    def _header(title: str) -> None:
        lines.append(f"# --- {title} ---")

    # Collect OBJECT types reachable from Query
    def _collect_reachable(root: str) -> list[str]:
        """BFS from *root* through OBJECT/INTERFACE/UNION field types."""
        seen: set[str] = set()
        queue: list[str] = [root]
        while queue:
            name = queue.pop(0)
            if name in seen or name in _SKIP_TYPES:
                continue
            seen.add(name)
            t = types_by_name.get(name)
            if t is None:
                continue
            kind = t.get("kind")
            if kind in _OBJECT_KINDS:
                for field in t.get("fields") or []:
                    inner = _unwrap_type(field.get("type"))
                    if inner and inner.get("kind") in _OBJECT_KINDS:
                        target = inner.get("name")
                        if target and target not in seen and target not in _SKIP_TYPES:
                            queue.append(target)
        return sorted(seen)

    # Object types
    _header("OBJECT TYPES")
    reachable: list[str] = _collect_reachable(query_type_name)

    # In the zero-extension ("melt") scenario, Query has no fields, so BFS
    # only reaches Query itself.  Include all non-introspection OBJECT
    # types so kernel document classes still appear.
    extra = sorted(
        n
        for n, t in types_by_name.items()
        if n not in reachable
        and t.get("kind") in _OBJECT_KINDS
        and n not in _SKIP_TYPES
        and n != mutation_type_name
    )
    reachable.extend(extra)

    for name in reachable:
        t = types_by_name.get(name)
        if t is None or t.get("kind") not in _OBJECT_KINDS:
            continue
        if name == mutation_type_name:
            continue
        if name in _SKIP_TYPES:
            continue
        lines.append(f"type {name} {{")
        for field in sorted(t.get("fields") or [], key=lambda f: f["name"]):
            fname = field["name"]
            ftype = _field_type_str(field)
            # Collect args for display
            args = field.get("args") or []
            if args:
                arg_parts = []
                for a in sorted(args, key=lambda x: x["name"]):
                    a_str = f"{a['name']}: {_type_name(a.get('type'))}"
                    arg_parts.append(a_str)
                lines.append(f"  {fname}({', '.join(arg_parts)}): {ftype}")
            else:
                lines.append(f"  {fname}: {ftype}")
        lines.append("}")
        lines.append("")
        emitted.add(name)

    # Input types (filter + ordering)
    _header("INPUT TYPES (Filters & Ordering)")
    input_names = sorted(
        n
        for n, t in types_by_name.items()
        if t.get("kind") in _INPUT_OBJECT_KINDS and n not in _SKIP_TYPES
    )
    for name in input_names:
        t = types_by_name[name]
        lines.append(f"input {name} {{")
        for field in sorted(t.get("inputFields") or [], key=lambda f: f["name"]):
            lines.append(f"  {field['name']}: {_type_name(field.get('type'))}")
        lines.append("}")
        lines.append("")
        emitted.add(name)

    # Enum types
    _header("ENUM TYPES")
    enum_names = sorted(
        n
        for n, t in types_by_name.items()
        if t.get("kind") in _ENUM_KINDS and n not in _SKIP_TYPES
    )
    for name in enum_names:
        t = types_by_name[name]
        values = [v["name"] for v in t.get("enumValues") or []]
        lines.append(f"enum {name} {{")
        for v in sorted(values):
            lines.append(f"  {v}")
        lines.append("}")
        lines.append("")
        emitted.add(name)

    return "\n".join(lines)


async def fetch_schema_meta_or_none(
    tdb: TdbClient,
    *,
    branch: str = "main",
) -> dict[str, str] | None:
    """Fetch @documentation.@comment for every schema class/enum.

    Uses ``tdb.get_schema()`` (document API) to read the full schema graph,
    then extracts the ``@documentation.@comment`` annotation for each
    class/enum entry.

    Returns a ``{name: comment}`` dict, or ``None`` on any error.
    """
    try:
        raw = await tdb.get_schema(branch)
    except Exception:
        return None
    docs: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("@id")
        if not isinstance(name, str):
            continue
        doc = entry.get("@documentation")
        if isinstance(doc, dict):
            comment = doc.get("@comment", "")
            if comment:
                docs[name] = comment
    return docs
