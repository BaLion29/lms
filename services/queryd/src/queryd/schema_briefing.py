"""Schema introspection and briefing for TerminusDB v12.0.6.

TerminusDB v12.0.6 exposes NO SDL — only GraphQL introspection JSON.
"""

from __future__ import annotations

from typing import Any

from lms_core.tdb import TdbClient

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


def render_module_briefing(
    modules: list[dict[str, Any]],
    *,
    active_plugins: list[str] | None = None,
) -> str:
    """Render the installed-modules list for the system-prompt briefing.

    Returns an empty string when *modules* is empty (i.e. the registry
    exists but has no entries yet — pre-modularisation state).
    """
    if not modules or not isinstance(modules, list):
        return ""

    lines: list[str] = []
    lines.append("=== Installed Schema Modules ===")
    lines.append("")
    for doc in sorted(modules, key=lambda d: (d if isinstance(d, dict) else {}).get("name", "")):
        if not isinstance(doc, dict):
            continue
        name = doc.get("name", "?")
        version = doc.get("version", "?")
        lines.append(f"  {name} {version}")
    lines.append("")

    if active_plugins:
        lines.append("=== Active Write-Tool Plugins ===")
        lines.append("")
        for p in sorted(active_plugins):
            lines.append(f"  {p}")
        lines.append("")

    return "\n".join(lines)


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
    reachable = _collect_reachable(query_type_name)

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


# ---------------------------------------------------------------------------
# Prompt briefing (shorter, for the system prompt)
# ---------------------------------------------------------------------------

_DOMAIN_CLASSES = frozenset(
    {
        "Task",
        "Event",
        "Reminder",
        "Person",
        "Location",
        "InboxNote",
        "InboxAudio",
        "Activity",
        "Routine",
    }
)


def render_prompt_briefing(introspection: dict[str, Any]) -> str:
    """Return a SHORTER briefing for the system prompt.

    Only lists domain classes (Task, Event, Reminder, Person, Location,
    InboxNote, InboxAudio, Activity, Routine — those present) with their key
    fields and types, the status enums with exact values, plus fixed
    explanatory notes about query args, filter operators, IRI format, nested
    references, and datetime format.
    """
    schema = introspection.get("__schema", introspection)
    type_list: list[dict[str, Any]] = schema.get("types", [])
    types_by_name: dict[str, dict[str, Any]] = {t["name"]: t for t in type_list}

    lines: list[str] = []
    lines.append("=== Domain Schema ===")
    lines.append("")

    # Domain classes with fields
    for name in sorted(n for n in _DOMAIN_CLASSES if n in types_by_name):
        t = types_by_name[name]
        if t.get("kind") not in _OBJECT_KINDS:
            continue
        fields = t.get("fields") or []
        key_fields = sorted(fields, key=lambda f: f["name"])
        lines.append(f"type {name} {{")
        for f in key_fields:
            lines.append(f"  {f['name']}: {_field_type_str(f)}")
        lines.append("}")
        lines.append("")

    # Status enums
    status_enum_names = sorted(
        n
        for n, t in types_by_name.items()
        if t.get("kind") in _ENUM_KINDS and n.endswith("Status")
    )
    if status_enum_names:
        lines.append("=== Status Enums ===")
        lines.append("")
        for name in status_enum_names:
            t = types_by_name[name]
            values = [v["name"] for v in t.get("enumValues") or []]
            lines.append(f"enum {name} {{ {' | '.join(values)} }}")
        lines.append("")

    # Fixed explanatory notes
    lines.append("=== Query Conventions ===")
    lines.append("")
    lines.append("- Query args: (id, ids, offset, limit, filter, orderBy).")
    lines.append(
        "- Filter operators: eq, ne, lt, le, gt, ge; "
        "StringFilter also has regex, startsWith, allOfTerms, anyOfTerms."
    )
    lines.append(
        "- _id returns FULL IRIs like terminusdb:///data/Task/xyz; "
        "the document API uses short form Task/xyz."
    )
    lines.append(
        "- References (Task.derived_from: Source, Event.location: Location, "
        "Reminder.refers_to: Remindable=Task|Event) are NESTED OBJECTS in "
        "GraphQL — select subfields like { location { name } } instead of "
        "expecting scalar IRIs."
    )
    lines.append(
        '- Datetimes are ISO "YYYY-MM-DDTHH:MM:SSZ" (UTC).'
        "  Always use string comparisons for dates."
        "  For timezone conversions interpret everything as Zurich/Europe."
    )

    return "\n".join(lines)
