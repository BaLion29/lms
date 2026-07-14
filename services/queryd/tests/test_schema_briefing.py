"""Tests for queryd.schema_briefing."""

from __future__ import annotations

from queryd.schema_briefing import (
    render_module_briefing,
    render_prompt_briefing,
    render_schema_summary,
)

# ---------------------------------------------------------------------------
# Minimal hand-written introspection fixture.
#
# Contains: Query with Task + Project fields; Task with _id/name/status/due_date;
# Project (NEW — not in any hardcoded set) with _id/name;
# SchemaModule + SchemaMigration (MUST be excluded from prompt briefing);
# Provenance + ExternalRef (subdocument-only, MUST be excluded);
# Task_Filter; DateTimeFilter; TaskStatus enum; TerminusMutation (excluded).
# ---------------------------------------------------------------------------


_INTROSPECTION: dict = {
    "__schema": {
        "queryType": {"name": "Query"},
        "mutationType": {"name": "TerminusMutation"},
        "types": [
            # --- Query ----------------------------------------------------
            {
                "name": "Query",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "Task",
                        "args": [
                            {
                                "name": "filter",
                                "type": {
                                    "kind": "INPUT_OBJECT",
                                    "name": "Task_Filter",
                                    "ofType": None,
                                },
                            },
                        ],
                        "type": {
                            "kind": "LIST",
                            "name": None,
                            "ofType": {
                                "kind": "OBJECT",
                                "name": "Task",
                                "ofType": None,
                            },
                        },
                    },
                    {
                        "name": "Project",
                        "args": [],
                        "type": {
                            "kind": "LIST",
                            "name": None,
                            "ofType": {
                                "kind": "OBJECT",
                                "name": "Project",
                                "ofType": None,
                            },
                        },
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- Task (OBJECT) --------------------------------------------
            {
                "name": "Task",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "_id",
                        "args": [],
                        "type": {
                            "kind": "NON_NULL",
                            "name": None,
                            "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None},
                        },
                    },
                    {
                        "name": "due_date",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "name",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "status",
                        "args": [],
                        "type": {"kind": "ENUM", "name": "TaskStatus", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- Project (OBJECT) — NOT in old hardcoded set --------------
            {
                "name": "Project",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "_id",
                        "args": [],
                        "type": {
                            "kind": "NON_NULL",
                            "name": None,
                            "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None},
                        },
                    },
                    {
                        "name": "name",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- SchemaModule (MUST be excluded from prompt briefing) -----
            {
                "name": "SchemaModule",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "checksum",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "installed_at",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "name",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "origin",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "version",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- SchemaMigration (MUST be excluded from prompt briefing) --
            {
                "name": "SchemaMigration",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "applied_at",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "checksum",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "filename",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                    {
                        "name": "module",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- Provenance (subdocument, excluded) -----------------------
            {
                "name": "Provenance",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "agent",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- ExternalRef (subdocument, excluded) ----------------------
            {
                "name": "ExternalRef",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "external_id",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- Task_Filter (INPUT_OBJECT) -------------------------------
            {
                "name": "Task_Filter",
                "kind": "INPUT_OBJECT",
                "fields": None,
                "inputFields": [
                    {
                        "name": "due_date",
                        "type": {
                            "kind": "INPUT_OBJECT",
                            "name": "DateTimeFilter",
                            "ofType": None,
                        },
                    },
                ],
                "enumValues": None,
            },
            # --- DateTimeFilter -------------------------------------------
            {
                "name": "DateTimeFilter",
                "kind": "INPUT_OBJECT",
                "fields": None,
                "inputFields": [
                    {
                        "name": "eq",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "ne",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "lt",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "le",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "gt",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                    {
                        "name": "ge",
                        "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None},
                    },
                ],
                "enumValues": None,
            },
            # --- StringFilter ---------------------------------------------
            {
                "name": "StringFilter",
                "kind": "INPUT_OBJECT",
                "fields": None,
                "inputFields": [
                    {
                        "name": "eq",
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "enumValues": None,
            },
            # --- TaskStatus_Enum_Filter -----------------------------------
            {
                "name": "TaskStatus_Enum_Filter",
                "kind": "INPUT_OBJECT",
                "fields": None,
                "inputFields": [
                    {
                        "name": "eq",
                        "type": {"kind": "ENUM", "name": "TaskStatus", "ofType": None},
                    },
                ],
                "enumValues": None,
            },
            # --- TaskStatus (ENUM) ----------------------------------------
            {
                "name": "TaskStatus",
                "kind": "ENUM",
                "fields": None,
                "inputFields": None,
                "enumValues": [
                    {"name": "open"},
                    {"name": "planned"},
                    {"name": "done"},
                ],
            },
            # --- TerminusMutation (MUST be excluded) ----------------------
            {
                "name": "TerminusMutation",
                "kind": "OBJECT",
                "fields": [
                    {
                        "name": "_insertDocuments",
                        "args": [],
                        "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                    },
                ],
                "inputFields": None,
                "enumValues": None,
            },
            # --- Introspection dunder types (MUST be excluded) ------------
            {
                "name": "__Schema",
                "kind": "OBJECT",
                "fields": [],
                "inputFields": None,
                "enumValues": None,
            },
        ],
    }
}


# ---------------------------------------------------------------------------
# Tests: render_schema_summary
# ---------------------------------------------------------------------------


def test_render_schema_summary_contains_task_fields():
    summary = render_schema_summary(_INTROSPECTION)
    assert "type Task {" in summary
    assert "_id: ID!" in summary
    assert "name: String" in summary
    assert "status: TaskStatus" in summary
    assert "due_date: DateTime" in summary


def test_render_schema_summary_contains_filter_operators():
    summary = render_schema_summary(_INTROSPECTION)
    assert "input DateTimeFilter {" in summary
    assert "eq" in summary
    assert "ne" in summary
    assert "lt" in summary
    assert "le" in summary
    assert "gt" in summary
    assert "ge" in summary


def test_render_schema_summary_contains_enum_values():
    summary = render_schema_summary(_INTROSPECTION)
    assert "enum TaskStatus {" in summary
    assert "open" in summary
    assert "planned" in summary
    assert "done" in summary


def test_render_schema_summary_excludes_mutation():
    summary = render_schema_summary(_INTROSPECTION)
    assert "TerminusMutation" not in summary
    assert "_insertDocuments" not in summary


def test_render_schema_summary_excludes_dunders():
    summary = render_schema_summary(_INTROSPECTION)
    assert "__Schema" not in summary


def test_render_schema_summary_deterministic():
    """Calling twice yields identical output."""
    a = render_schema_summary(_INTROSPECTION)
    b = render_schema_summary(_INTROSPECTION)
    assert a == b


# ---------------------------------------------------------------------------
# Tests: render_prompt_briefing (new: derived, not enumerated)
# ---------------------------------------------------------------------------


def test_render_prompt_briefing_contains_task():
    """Task (OBJECT kind, reachable from Query) appears."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "type Task {" in briefing
    assert "_id: ID!" in briefing
    assert "name: String" in briefing


def test_render_prompt_briefing_contains_project():
    """Project (not in any hardcoded set, derived from introspection) appears."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "type Project {" in briefing
    assert "name: String" in briefing


def test_render_prompt_briefing_excludes_schema_module():
    """SchemaModule (registry meta-class) is excluded."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "type SchemaModule {" not in briefing
    assert "type SchemaMigration {" not in briefing


def test_render_prompt_briefing_excludes_subdocuments():
    """Provenance and ExternalRef (subdocument helpers) are excluded from
    the type listing."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "type Provenance {" not in briefing
    assert "type ExternalRef {" not in briefing


def test_render_prompt_briefing_excludes_mutation_and_query():
    """TerminusMutation and Query are excluded from the domain type listing."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "type TerminusMutation {" not in briefing
    assert "type Query {" not in briefing


def test_render_prompt_briefing_entity_preamble_present_once():
    """The universal Entity preamble appears exactly once."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "=== Universal Entity Fields ===" in briefing
    assert "created_at" in briefing
    assert "updated_at" in briefing
    assert "provenance" in briefing
    assert "contexts" in briefing
    assert "external_refs" in briefing
    # Must appear exactly once
    assert briefing.count("=== Universal Entity Fields ===") == 1


def test_render_prompt_briefing_provenance_traversal_note():
    """The derived_from ancestry chain note is in Query Conventions."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "derived_from chain" in briefing
    assert "birth certificate" in briefing


def test_render_prompt_briefing_contains_status_enum():
    """TaskStatus enum appears with its values."""
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "TaskStatus" in briefing
    assert "open" in briefing
    assert "planned" in briefing
    assert "done" in briefing


def test_render_prompt_briefing_contains_iri_note():
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "terminusdb:///data/" in briefing
    assert "Task/xyz" in briefing


def test_render_prompt_briefing_contains_nested_reference_note():
    briefing = render_prompt_briefing(_INTROSPECTION)
    assert "NESTED OBJECTS" in briefing
    assert "{ trigger { name fired_at } }" in briefing


def test_render_prompt_briefing_schema_docs_injection():
    """When schema_docs is provided, @documentation comments appear on
    class and enum blocks."""
    docs = {
        "Task": "A to-do item with status tracking.",
        "Project": "A project grouping related tasks.",
        "TaskStatus": "Possible states for a task.",
    }
    briefing = render_prompt_briefing(_INTROSPECTION, schema_docs=docs)
    # Task doc appears before its type block
    assert "# A to-do item with status tracking." in briefing
    assert "# A project grouping related tasks." in briefing
    # Enum doc appears before its enum block
    assert "# Possible states for a task." in briefing


def test_render_prompt_briefing_deterministic():
    """Calling twice yields identical output."""
    a = render_prompt_briefing(_INTROSPECTION)
    b = render_prompt_briefing(_INTROSPECTION)
    assert a == b


# ---------------------------------------------------------------------------
# Tests: render_module_briefing
# ---------------------------------------------------------------------------


def test_render_module_briefing_empty():
    assert render_module_briefing([]) == ""
    assert render_module_briefing(None) == ""  # type: ignore[arg-type]


def test_render_module_briefing_name_version():
    modules = [{"name": "core", "version": "1.1.0"}]
    result = render_module_briefing(modules)
    assert "core 1.1.0" in result


def test_render_module_briefing_with_origin():
    """origin field is rendered in parentheses."""
    modules = [{"name": "core", "version": "1.1.0", "origin": "repo"}]
    result = render_module_briefing(modules)
    assert "core 1.1.0 (repo)" in result


def test_render_module_briefing_with_origin_and_description():
    """origin and description both rendered."""
    modules = [
        {
            "name": "planning",
            "version": "0.1.0",
            "origin": "firnline-ext-planning",
            "description": "Task/Event planning module",
        }
    ]
    result = render_module_briefing(modules)
    assert "planning 0.1.0 (firnline-ext-planning): Task/Event planning module" in result


def test_render_module_briefing_multiple_modules_sorted():
    modules = [
        {"name": "zulu", "version": "1.0"},
        {"name": "alpha", "version": "2.0"},
    ]
    result = render_module_briefing(modules)
    alpha_pos = result.index("alpha")
    zulu_pos = result.index("zulu")
    assert alpha_pos < zulu_pos


def test_render_module_briefing_with_active_plugins():
    modules = [{"name": "core", "version": "1.0"}]
    result = render_module_briefing(modules, active_plugins=["planning_tools"])
    assert "=== Installed Schema Modules ===" in result
    assert "=== Active Write-Tool Plugins ===" in result
    assert "planning_tools" in result
