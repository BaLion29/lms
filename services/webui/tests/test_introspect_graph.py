"""Unit tests for extract_edges helper."""

from __future__ import annotations


from firnline_webui.introspect import extract_edges


class TestExtractEdges:
    """Tests for extract_edges()."""

    def test_string_ref_matched(self):
        docs = [
            {"@id": "doc/A", "@type": "Foo", "anchor": "doc/B"},
        ]
        known = {"doc/A", "doc/B"}
        result = extract_edges(docs, known)
        assert len(result) == 1
        assert result[0] == {"source": "doc/A", "target": "doc/B", "prop": "anchor"}

    def test_list_of_refs(self):
        docs = [
            {"@id": "doc/A", "tags": ["doc/B", "doc/C"]},
        ]
        known = {"doc/A", "doc/B", "doc/C"}
        result = extract_edges(docs, known)
        assert len(result) == 2
        assert {"source": "doc/A", "target": "doc/B", "prop": "tags"} in result
        assert {"source": "doc/A", "target": "doc/C", "prop": "tags"} in result

    def test_dict_with_at_id_ref(self):
        docs = [
            {"@id": "doc/A", "parent": {"@id": "doc/B", "@type": "Foo"}},
        ]
        known = {"doc/A", "doc/B"}
        result = extract_edges(docs, known)
        assert len(result) == 1
        assert result[0] == {"source": "doc/A", "target": "doc/B", "prop": "parent"}

    def test_unknown_target_skipped(self):
        docs = [
            {"@id": "doc/A", "anchor": "doc/Z"},
        ]
        known = {"doc/A"}
        result = extract_edges(docs, known)
        assert result == []

    def test_self_loop_skipped(self):
        docs = [
            {"@id": "doc/A", "ref": "doc/A"},
        ]
        known = {"doc/A"}
        result = extract_edges(docs, known)
        assert result == []

    def test_deduplication(self):
        docs = [
            {"@id": "doc/A", "ref": "doc/B", "other": "doc/B"},
        ]
        known = {"doc/A", "doc/B"}
        result = extract_edges(docs, known)
        assert len(result) == 2  # different props, so not deduplicated

    def test_same_triple_deduplicated(self):
        docs = [
            {"@id": "doc/A", "ref": "doc/B"},
            {"@id": "doc/A", "ref": "doc/B"},
        ]
        known = {"doc/A", "doc/B"}
        result = extract_edges(docs, known)
        assert len(result) == 1
        assert result[0] == {"source": "doc/A", "target": "doc/B", "prop": "ref"}

    def test_non_string_values_ignored(self):
        docs = [
            {"@id": "doc/A", "count": 42, "flag": True, "nested": {"key": "val"}},
        ]
        known = {"doc/A", "42", "True"}
        result = extract_edges(docs, known)
        assert result == []

    def test_doc_without_at_id_skipped(self):
        docs = [
            {"name": "orphan", "anchor": "doc/B"},
        ]
        known = {"doc/B"}
        result = extract_edges(docs, known)
        assert result == []

    def test_mixed_fields(self):
        docs = [
            {
                "@id": "Task/abc",
                "@type": "Task",
                "assignee": "Person/jane",
                "tags": ["Tag/urgent", "Tag/backlog"],
                "parent": {"@id": "Task/parent"},
            },
        ]
        known = {"Task/abc", "Person/jane", "Tag/urgent", "Tag/backlog", "Task/parent"}
        result = extract_edges(docs, known)
        assert len(result) == 4
        props_found = {e["prop"] for e in result}
        assert props_found == {"assignee", "tags", "parent"}

    def test_list_with_dict_items(self):
        docs = [
            {
                "@id": "doc/A",
                "refs": [{"@id": "doc/B"}, {"@id": "doc/C"}],
            },
        ]
        known = {"doc/A", "doc/B", "doc/C"}
        result = extract_edges(docs, known)
        assert len(result) == 2

    def test_empty_input(self):
        assert extract_edges([], set()) == []
        assert extract_edges([], {"doc/A"}) == []
