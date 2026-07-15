"""Tests for queryd.schema_briefing."""

from __future__ import annotations

from queryd.schema_briefing import render_schema_summary

# ---------------------------------------------------------------------------
# Minimal hand-written introspection fixture.
#
# Contains: Query with Task + Project fields; Task with _id/name/status/due_date;
# Project (NEW — not in any hardcoded set) with _id/name;
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
