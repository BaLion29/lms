"""Plugin-specific tests for firnline-ext-people — linking context, plugin metadata."""

from __future__ import annotations

import asyncio

from firnline_core.plugins import EntityIndex
from firnline_ext_people.extract import PeopleLinkingPlugin, _build_context_block


# ---------------------------------------------------------------------------
# build_context_block (moved from ingestd.linking)
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    """Tests for the context block renderer (moved from ingestd.linking)."""

    def test_small_index_exact_string(self):
        index = EntityIndex(
            entities={
                "Person": {"anna meier": "Person/abc"},
                "Location": {"rotondohütte": "Location/hut1"},
            },
            display={
                "Person": [("Anna Meier", "Person/abc")],
                "Location": [("Rotondohütte", "Location/hut1")],
            },
        )
        block = _build_context_block(index)
        expected = "Known people: Anna Meier <Person/abc>\nKnown locations: Rotondohütte <Location/hut1>"
        assert block == expected

    def test_multiple_entries_comma_separated(self):
        index = EntityIndex(
            entities={"Person": {}},
            display={
                "Person": [
                    ("Anna Meier", "Person/abc"),
                    ("Bob Müller", "Person/def"),
                ],
            },
        )
        block = _build_context_block(index)
        assert block == ("Known people: Anna Meier <Person/abc>, Bob Müller <Person/def>\nKnown locations: (none)")

    def test_empty_index_shows_none(self):
        index = EntityIndex()
        block = _build_context_block(index)
        assert block == "Known people: (none)\nKnown locations: (none)"


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def test_name(self):
        assert PeopleLinkingPlugin().name == "people_linking"

    def test_requires_has_people_and_places(self):
        req_names = {r.name for r in PeopleLinkingPlugin().requires}
        assert req_names >= {"people", "places"}

    def test_produces_is_empty_list(self):
        assert PeopleLinkingPlugin().produces == []

    def test_proposal_models_is_empty(self):
        models = PeopleLinkingPlugin().proposal_models()
        assert models == []

    def test_prompt_snippet_is_empty(self):
        assert PeopleLinkingPlugin().prompt_snippet() == ""

    def test_linking_context_returns_context_block(self):
        index = EntityIndex(
            entities={"Person": {"bob": "Person/1"}},
            display={"Person": [("Bob", "Person/1")]},
        )
        result = asyncio.run(PeopleLinkingPlugin().linking_context(None, index=index, branch=""))
        assert "Known people: Bob <Person/1>" in result
        assert "Known locations: (none)" in result

    def test_build_documents_returns_empty(self):
        import asyncio
        from firnline_core.plugins import BuildContext

        ctx = BuildContext(tdb=None, captured_iri="test")
        result = asyncio.run(PeopleLinkingPlugin().build_documents(type("P", (), {"kind": "fake", "name": "x"})(), ctx))
        assert result == []
