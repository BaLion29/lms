"""Plugin-specific tests for lms-ext-people — linking context, plugin metadata."""

from __future__ import annotations

import asyncio

from lms_core.plugins import EntityIndex
from lms_ext_people.extract import PeopleLinkingPlugin, _build_context_block


# ---------------------------------------------------------------------------
# build_context_block (moved from ingestd.linking)
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    """Tests for the context block renderer (moved from ingestd.linking)."""

    def test_small_index_exact_string(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
            locations={"rotondohütte": "Location/hut1"},
            locations_display=[("Rotondohütte", "Location/hut1")],
        )
        block = _build_context_block(index)
        expected = (
            "Known people: Anna Meier <Person/abc>\n"
            "Known locations: Rotondohütte <Location/hut1>"
        )
        assert block == expected

    def test_multiple_entries_comma_separated(self):
        index = EntityIndex(
            people={},
            people_display=[
                ("Anna Meier", "Person/abc"),
                ("Bob Müller", "Person/def"),
            ],
            locations={},
            locations_display=[],
        )
        block = _build_context_block(index)
        assert block == (
            "Known people: Anna Meier <Person/abc>, Bob Müller <Person/def>\n"
            "Known locations: (none)"
        )

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

    def test_proposal_models_is_empty(self):
        models = PeopleLinkingPlugin().proposal_models()
        assert models == []

    def test_prompt_snippet_is_empty(self):
        assert PeopleLinkingPlugin().prompt_snippet() == ""

    def test_linking_context_returns_context_block(self):
        index = EntityIndex(
            people={"bob": "Person/1"},
            people_display=[("Bob", "Person/1")],
            locations={},
            locations_display=[],
        )
        result = asyncio.run(
            PeopleLinkingPlugin().linking_context(None, index=index, branch="")
        )
        assert "Known people: Bob <Person/1>" in result
        assert "Known locations: (none)" in result

    def test_build_documents_returns_empty(self):
        import asyncio
        from lms_core.plugins import BuildContext
        ctx = BuildContext(tdb=None, inbox_iri="test")
        result = asyncio.run(
            PeopleLinkingPlugin().build_documents(
                type("P", (), {"kind": "fake", "name": "x"})(), ctx
            )
        )
        assert result == []
