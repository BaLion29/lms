"""Unit tests for firnline_webui.introspect helpers."""

from __future__ import annotations

import pytest

from firnline_webui.introspect import (
    browsable_classes,
    doc_preview,
    format_iri,
    group_classes_by_module,
    inbox_classes,
    row_from_doc,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def inbox_schema() -> list[dict]:
    """Schema modelled on the real firnline-ext-inbox schema.json."""
    return [
        {
            "@id": "InboxAudio",
            "@inherits": "Source",
            "@type": "Class",
            "created_at": "xsd:dateTime",
            "file_name": "xsd:string",
            "file_path": "xsd:string",
            "recorded_at": "xsd:dateTime",
            "status": "InboxAudioStatus",
            "transcription": "xsd:string",
            "updated_at": "xsd:dateTime",
        },
        {
            "@id": "InboxNote",
            "@inherits": "Source",
            "@type": "Class",
            "content": "xsd:string",
            "created_at": "xsd:dateTime",
            "status": "InboxNoteStatus",
            "updated_at": "xsd:dateTime",
        },
        {
            "@id": "InboxAudioStatus",
            "@type": "Enum",
            "@value": ["new", "transcribed", "processed", "failed", "archived"],
        },
        {
            "@id": "InboxNoteStatus",
            "@type": "Enum",
            "@value": ["new", "processed", "failed", "archived"],
        },
    ]


@pytest.fixture
def full_schema() -> list[dict]:
    """Schema with classes, enums, abstract, and subdocument entries."""
    return [
        {"@id": "InboxNote", "@type": "Class", "text": "xsd:string", "status": "xsd:string"},
        {"@id": "Person", "@type": "Class", "name": "xsd:string", "age": "xsd:integer"},
        {"@id": "AbstractThing", "@type": "Class", "@abstract": True, "name": "xsd:string"},
        {"@id": "SubDoc", "@type": "Class", "@subdocument": True, "value": "xsd:string"},
        {"@id": "Status", "@type": "Enum", "@value": ["a", "b"]},
        {"@id": "Event", "@type": "Class", "name": "xsd:string", "date": "xsd:dateTime"},
    ]


@pytest.fixture
def sample_modules() -> list[dict]:
    return [
        {
            "name": "inbox_ext",
            "version": "1.0.0",
            "exports": ["InboxNote", "InboxNoteStatus"],
        },
        {
            "name": "core_ext",
            "version": "2.0.0",
            "exports": ["Person", "Event"],
        },
    ]


# ── inbox_classes ───────────────────────────────────────────────────────


def test_inbox_classes_finds_inbox_prefix(inbox_schema):
    result = inbox_classes(inbox_schema)
    assert result == ["InboxAudio", "InboxNote"]


def test_inbox_classes_excludes_abstract(full_schema):
    result = inbox_classes(full_schema)
    assert "AbstractThing" not in result


def test_inbox_classes_excludes_subdocument(full_schema):
    result = inbox_classes(full_schema)
    assert "SubDoc" not in result


def test_inbox_classes_excludes_non_inbox(full_schema):
    result = inbox_classes(full_schema)
    assert "Person" not in result
    assert "Event" not in result


def test_inbox_classes_empty():
    assert inbox_classes([]) == []
    assert inbox_classes([{"@type": "Class", "@id": "Foo"}]) == []


# ── browsable_classes ───────────────────────────────────────────────────


def test_browsable_classes_excludes_abstract(full_schema):
    result = browsable_classes(full_schema)
    assert "AbstractThing" not in result


def test_browsable_classes_excludes_subdocument(full_schema):
    result = browsable_classes(full_schema)
    assert "SubDoc" not in result


def test_browsable_classes_includes_normal_classes(full_schema):
    result = browsable_classes(full_schema)
    assert "InboxNote" in result
    assert "Person" in result
    assert "Event" in result


def test_browsable_classes_sorted():
    schema = [
        {"@id": "Zebra", "@type": "Class"},
        {"@id": "Apple", "@type": "Class"},
    ]
    assert browsable_classes(schema) == ["Apple", "Zebra"]


def test_browsable_classes_empty():
    assert browsable_classes([]) == []


# ── group_classes_by_module ─────────────────────────────────────────────


def test_group_by_module(sample_modules):
    class_ids = ["InboxNote", "Person", "Event", "OtherClass"]
    result = group_classes_by_module(class_ids, sample_modules)
    assert set(result.keys()) == {"inbox_ext", "core_ext", "other"}
    assert result["inbox_ext"] == ["InboxNote"]
    assert result["core_ext"] == ["Event", "Person"]
    assert result["other"] == ["OtherClass"]


def test_group_by_module_empty_exports_go_to_other():
    modules = [{"name": "foo", "exports": []}]
    result = group_classes_by_module(["Bar"], modules)
    assert "other" in result
    assert result["other"] == ["Bar"]


def test_group_by_module_no_exports_go_to_other():
    modules = [{"name": "foo"}]  # no exports key
    result = group_classes_by_module(["Bar"], modules)
    assert "other" in result
    assert result["other"] == ["Bar"]


def test_group_by_module_skip_empty_groups():
    modules = [{"name": "foo", "exports": ["A"]}]
    result = group_classes_by_module(["A"], modules)
    assert "other" not in result  # no unclaimed
    assert result == {"foo": ["A"]}


# ── doc_preview ─────────────────────────────────────────────────────────


def test_doc_preview_prefers_text():
    doc = {"text": "Hello world " * 20, "transcription": "other"}
    result = doc_preview(doc, limit=20)
    assert result.startswith("Hello world Hello wo")
    assert result.endswith("…")


def test_doc_preview_falls_back_to_transcription():
    doc = {"transcription": "A transcript"}
    assert doc_preview(doc) == "A transcript"


def test_doc_preview_falls_back_to_content():
    doc = {"content": "Some content here"}
    assert doc_preview(doc) == "Some content here"


def test_doc_preview_falls_back_to_first_string():
    doc = {"@id": "x", "note": "some text", "count": 5}
    result = doc_preview(doc)
    assert result == "some text"


def test_doc_preview_no_string_fields():
    doc = {"@id": "x", "count": 5, "tags": ["a"]}
    assert doc_preview(doc) == ""


def test_doc_preview_short_enough():
    doc = {"text": "hi"}
    assert doc_preview(doc) == "hi"


# ── row_from_doc ────────────────────────────────────────────────────────


def test_row_from_doc_stringifies():
    doc = {"name": "Alice", "count": 5, "tags": ["a", "b"], "meta": {"x": 1}, "active": True}
    fields = ["name", "count", "tags", "meta", "active", "missing"]
    row = row_from_doc(doc, fields)
    assert row["name"] == "Alice"
    assert row["count"] == "5"
    assert row["tags"] == "[2]"
    assert row["meta"] == "{…}"
    assert row["active"] == "true"
    assert row["missing"] == ""


def test_row_from_doc_none_value():
    doc = {"name": None}
    assert row_from_doc(doc, ["name"]) == {"name": ""}


# ── format_iri ──────────────────────────────────────────────────────────


def test_format_iri_strips_prefix():
    result = format_iri("terminusdb:///data/InboxNote/abc123")
    assert result == "InboxNote/abc123"


def test_format_iri_passthrough():
    result = format_iri("InboxNote/abc123")
    assert result == "InboxNote/abc123"


def test_format_iri_empty():
    assert format_iri("") == ""
