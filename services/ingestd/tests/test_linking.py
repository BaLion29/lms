"""Tests for ingestd.linking — entity index building, matching."""

from __future__ import annotations

import structlog
from ingestd.linking import (
    EntityIndex,
    build_index,
    match_location,
    match_person,
)


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------


class TestBuildIndex:
    def test_people_indexed_by_lowercase_name(self):
        people = [{"@id": "Person/abc", "name": "Anna Meier"}]
        locations: list[dict] = []
        index = build_index(people, locations)
        assert index.people == {"anna meier": "Person/abc"}
        assert index.people_display == [("Anna Meier", "Person/abc")]

    def test_doc_without_name_skipped(self):
        people = [
            {"@id": "Person/abc", "name": "Anna Meier"},
            {"@id": "Person/missing", "other": "value"},
        ]
        locations: list[dict] = []
        index = build_index(people, locations)
        assert len(index.people) == 1
        assert "Person/missing" not in index.people.values()

    def test_location_aliases_indexed_to_same_iri(self):
        people: list[dict] = []
        locations = [
            {
                "@id": "Location/hut1",
                "name": "Rotondohütte",
                "aliases": ["R Hütte", "Rotondo"],
            },
        ]
        index = build_index(people, locations)
        assert index.locations["rotondohütte"] == "Location/hut1"
        assert index.locations["r hütte"] == "Location/hut1"
        assert index.locations["rotondo"] == "Location/hut1"
        # display only includes the primary name
        assert index.locations_display == [("Rotondohütte", "Location/hut1")]

    def test_locations_without_aliases(self):
        people: list[dict] = []
        locations = [
            {"@id": "Location/simple", "name": "Zürich"},
        ]
        index = build_index(people, locations)
        assert index.locations == {"zürich": "Location/simple"}

    def test_empty_inputs_produce_empty_index(self):
        index = build_index([], [])
        assert index.people == {}
        assert index.locations == {}
        assert index.people_display == []
        assert index.locations_display == []

    def test_casefold_handles_german_eszett(self):
        """Straße and Strasse both casefold to 'strasse'."""
        people = [{"@id": "Person/1", "name": "Straße"}]
        locations: list[dict] = []
        index = build_index(people, locations)
        # The stored key is the casefold of "Straße"
        assert index.people["strasse"] == "Person/1"


# ---------------------------------------------------------------------------
# match_person
# ---------------------------------------------------------------------------


class TestMatchPerson:
    def test_exact_case_insensitive_hit(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        result = match_person(index, "anna meier")
        assert result == "Person/abc"

    def test_different_casing_still_hits(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        result = match_person(index, "ANNA MEIER")
        assert result == "Person/abc"

    def test_whitespace_stripped(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        result = match_person(index, "  anna meier  ")
        assert result == "Person/abc"

    def test_miss_returns_none(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        result = match_person(index, "Unbekannt Person")
        assert result is None

    def test_near_miss_substring_logged_returns_none(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        with structlog.testing.capture_logs() as cap_logs:
            result = match_person(index, "Anna")
        assert result is None
        assert len(cap_logs) == 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "anna"
        assert log["known"] == "anna meier"
        assert log["category"] == "person"
        assert log["reason"] == "substring"

    def test_near_miss_first_token_logged_returns_none(self):
        index = EntityIndex(
            people={"anna meier": "Person/abc"},
            people_display=[("Anna Meier", "Person/abc")],
        )
        with structlog.testing.capture_logs() as cap_logs:
            result = match_person(index, "Anna Müller")
        assert result is None
        # "anna" (first token) matches "anna meier" (first token)
        assert len(cap_logs) >= 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "anna müller"
        assert log["known"] == "anna meier"
        assert log["reason"] == "first_token"

    def test_german_eszett_casefold_match(self):
        """'Straße' casefolds to 'strasse' — should match."""
        index = EntityIndex(
            people={"strasse": "Person/1"},
            people_display=[("Straße", "Person/1")],
        )
        result = match_person(index, "Straße")
        assert result == "Person/1"


# ---------------------------------------------------------------------------
# match_location
# ---------------------------------------------------------------------------


class TestMatchLocation:
    def test_match_via_primary_name(self):
        index = EntityIndex(
            locations={"rotondohütte": "Location/hut1"},
            locations_display=[("Rotondohütte", "Location/hut1")],
        )
        result = match_location(index, "Rotondohütte")
        assert result == "Location/hut1"

    def test_match_via_alias(self):
        index = EntityIndex(
            locations={"rotondohütte": "Location/hut1", "r hütte": "Location/hut1"},
            locations_display=[("Rotondohütte", "Location/hut1")],
        )
        result = match_location(index, "R Hütte")
        assert result == "Location/hut1"

    def test_casefold_match_umlaut(self):
        """ROTONDOHÜTTE should match rotondohütte."""
        index = EntityIndex(
            locations={"rotondohütte": "Location/hut1"},
            locations_display=[("Rotondohütte", "Location/hut1")],
        )
        result = match_location(index, "ROTONDOHÜTTE")
        assert result == "Location/hut1"

    def test_miss_returns_none_with_near_miss_log(self):
        index = EntityIndex(
            locations={"rotondohütte": "Location/hut1"},
            locations_display=[("Rotondohütte", "Location/hut1")],
        )
        with structlog.testing.capture_logs() as cap_logs:
            result = match_location(index, "Rotondo")
        assert result is None
        assert len(cap_logs) == 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "rotondo"
        assert log["known"] == "rotondohütte"
        assert log["reason"] == "substring"
