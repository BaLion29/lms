"""Unit tests for firnline_webui.introspect helpers."""

from __future__ import annotations

import pytest

from firnline_webui.introspect import (
    browsable_classes,
    class_label_field,
    doc_preview,
    format_iri,
    group_classes_by_module,
    inbox_classes,
    row_from_doc,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def captured_schema() -> list[dict]:
    """Schema with the kernel Captured class."""
    return [
        {
            "@id": "Captured",
            "@type": "Class",
            "captured_at": "xsd:dateTime",
            "content_type": "xsd:string",
            "content": "xsd:string",
            "status": "xsd:string",
            "transcription": "xsd:string",
            "file_name": "xsd:string",
            "blob_sha256": "xsd:string",
        },
        {
            "@id": "CapturedStatus",
            "@type": "Enum",
        },
    ]


@pytest.fixture
def full_schema() -> list[dict]:
    """Schema with classes, enums, abstract, and subdocument entries."""
    return [
        {
            "@id": "Captured",
            "@type": "Class",
            "content": "xsd:string",
            "status": "xsd:string",
            "content_type": "xsd:string",
            "captured_at": "xsd:dateTime",
        },
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
            "name": "capture_ext",
            "version": "1.0.0",
            "exports": ["Captured", "CapturedStatus"],
        },
        {
            "name": "core_ext",
            "version": "2.0.0",
            "exports": ["Person", "Event"],
        },
    ]


# ── inbox_classes ───────────────────────────────────────────────────────


def test_inbox_classes_finds_captured(captured_schema):
    result = inbox_classes(captured_schema)
    assert result == ["Captured"]


def test_inbox_classes_excludes_abstract(full_schema):
    result = inbox_classes(full_schema)
    assert "AbstractThing" not in result


def test_inbox_classes_excludes_subdocument(full_schema):
    result = inbox_classes(full_schema)
    assert "SubDoc" not in result


def test_inbox_classes_excludes_non_captured(full_schema):
    result = inbox_classes(full_schema)
    assert "Person" not in result
    assert "Event" not in result


def test_inbox_classes_empty():
    assert inbox_classes([]) == []
    assert inbox_classes([{"@type": "Class", "@id": "Foo"}]) == []


# ── class_label_field ───────────────────────────────────────────────────


def test_class_label_field_from_metadata():
    class_def = {
        "@id": "Person",
        "@type": "Class",
        "@metadata": {"label_field": "name"},
        "name": "xsd:string",
        "age": "xsd:integer",
    }
    assert class_label_field(class_def) == "name"


def test_class_label_field_missing_metadata():
    class_def = {"@id": "Foo", "@type": "Class", "name": "xsd:string"}
    assert class_label_field(class_def) is None


def test_class_label_field_field_not_in_class():
    class_def = {
        "@id": "Foo",
        "@type": "Class",
        "@metadata": {"label_field": "title"},
        "name": "xsd:string",
    }
    assert class_label_field(class_def) is None


def test_class_label_field_non_dict_metadata():
    class_def = {"@id": "Foo", "@type": "Class", "@metadata": "not a dict"}
    assert class_label_field(class_def) is None


# ── browsable_classes ───────────────────────────────────────────────────


def test_browsable_classes_excludes_abstract(full_schema):
    result = browsable_classes(full_schema)
    assert "AbstractThing" not in result


def test_browsable_classes_excludes_subdocument(full_schema):
    result = browsable_classes(full_schema)
    assert "SubDoc" not in result


def test_browsable_classes_includes_normal_classes(full_schema):
    result = browsable_classes(full_schema)
    assert "Captured" in result
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
    class_ids = ["Captured", "Person", "Event", "OtherClass"]
    result = group_classes_by_module(class_ids, sample_modules)
    assert set(result.keys()) == {"capture_ext", "core_ext", "other"}
    assert result["capture_ext"] == ["Captured"]
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
    assert row_from_doc(doc, ["name"]) == {"@id": "", "name": ""}


# ── format_iri ──────────────────────────────────────────────────────────


def test_format_iri_strips_prefix():
    result = format_iri("terminusdb:///data/Captured/abc123")
    assert result == "Captured/abc123"


def test_format_iri_passthrough():
    result = format_iri("Captured/abc123")
    assert result == "Captured/abc123"


def test_format_iri_empty():
    assert format_iri("") == ""
