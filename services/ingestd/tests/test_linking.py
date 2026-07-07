"""Tests for ingestd.linking — entity index building, matching."""

from __future__ import annotations

import structlog
from ingestd.linking import (
    EntityIndex,
    LinkingConfig,
    async_match_location,
    async_match_person,
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


# ---------------------------------------------------------------------------
# Async matching — indexed service integration
# ---------------------------------------------------------------------------

INDEXED_URL = "http://indexed.test:8089"


def _person_index() -> EntityIndex:
    return EntityIndex(
        people={"anna meier": "Person/abc"},
        people_display=[("Anna Meier", "Person/abc")],
    )


def _location_index() -> EntityIndex:
    return EntityIndex(
        locations={"rotondohütte": "Location/hut1", "r hütte": "Location/hut1"},
        locations_display=[("Rotondohütte", "Location/hut1")],
    )


class TestAsyncMatchPerson:
    async def test_fast_path_exact_hit_no_http(self, respx_mock):
        """Fast path hit returns IRI immediately, no indexed call."""
        route = respx_mock.post(f"{INDEXED_URL}/v1/find_entity")
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match_person(_person_index(), "Anna Meier", config)
        assert result == "Person/abc"
        assert not route.called

    async def test_disabled_config_miss_returns_none(self):
        """Fast-path miss + enabled=False → None, no indexed call."""
        config = LinkingConfig(enabled=False)
        result = await async_match_person(_person_index(), "Unknown", config)
        assert result is None

    async def test_high_confidence_accept(self, respx_mock):
        """Indexed returns candidate above min_confidence → IRI returned, log emitted."""
        payload = {
            "candidates": [
                {
                    "iri": "Person/xyz",
                    "class": "Person",
                    "name": "Unbekannt",
                    "aliases": [],
                    "score": 0.92,
                    "commit_id": "def",
                },
            ],
        }
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(json=payload)
        config = LinkingConfig(enabled=True, url=INDEXED_URL, min_confidence=0.85)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_person(_person_index(), "Unbekannt", config)

        assert result == "Person/xyz"
        accepted = [e for e in cap_logs if e.get("event") == "indexed_match_accepted"]
        assert len(accepted) == 1
        assert accepted[0]["type"] == "Person"
        assert accepted[0]["iri"] == "Person/xyz"
        assert accepted[0]["score"] == 0.92

    async def test_low_confidence_fall_through(self, respx_mock):
        """Indexed candidate below threshold → None, log below_threshold."""
        payload = {
            "candidates": [
                {
                    "iri": "Person/low",
                    "class": "Person",
                    "name": "Someone",
                    "aliases": [],
                    "score": 0.60,
                    "commit_id": "ghi",
                },
            ],
        }
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(json=payload)
        config = LinkingConfig(enabled=True, url=INDEXED_URL, min_confidence=0.85)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_person(_person_index(), "Someone", config)

        assert result is None
        below = [e for e in cap_logs if e.get("event") == "indexed_match_below_threshold"]
        assert len(below) == 1
        assert below[0]["type"] == "Person"
        assert below[0]["score"] == 0.60

    async def test_indexed_error_graceful_degradation(self, respx_mock):
        """Indexed returns 500 → None, warning logged, no exception."""
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(500)
        config = LinkingConfig(enabled=True, url=INDEXED_URL)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_person(_person_index(), "Unknown", config)

        assert result is None
        failed = [e for e in cap_logs if e.get("event") == "indexed_match_failed"]
        assert len(failed) == 1
        assert failed[0]["type"] == "Person"


class TestAsyncMatchLocation:
    async def test_fast_path_exact_hit_no_http(self, respx_mock):
        """Fast path hit for location returns IRI, no indexed call."""
        route = respx_mock.post(f"{INDEXED_URL}/v1/find_entity")
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match_location(_location_index(), "Rotondohütte", config)
        assert result == "Location/hut1"
        assert not route.called

    async def test_fast_path_alias_hit(self):
        """Alias in sync index also matches immediately."""
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match_location(_location_index(), "R Hütte", config)
        assert result == "Location/hut1"

    async def test_high_confidence_accept(self, respx_mock):
        """Indexed returns location candidate above min_confidence → IRI, log."""
        payload = {
            "candidates": [
                {
                    "iri": "Location/alp",
                    "class": "Location",
                    "name": "Alphütte",
                    "aliases": [],
                    "score": 0.88,
                    "commit_id": "jkl",
                },
            ],
        }
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(json=payload)
        config = LinkingConfig(enabled=True, url=INDEXED_URL, min_confidence=0.85)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_location(_location_index(), "Alphütte", config)

        assert result == "Location/alp"
        accepted = [e for e in cap_logs if e.get("event") == "indexed_match_accepted"]
        assert len(accepted) == 1
        assert accepted[0]["type"] == "Location"

    async def test_low_confidence_fall_through(self, respx_mock):
        """Location candidate below threshold → None, log."""
        payload = {
            "candidates": [
                {
                    "iri": "Location/far",
                    "class": "Location",
                    "name": "Faraway",
                    "aliases": [],
                    "score": 0.50,
                    "commit_id": "mno",
                },
            ],
        }
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(json=payload)
        config = LinkingConfig(enabled=True, url=INDEXED_URL, min_confidence=0.85)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_location(_location_index(), "Faraway", config)

        assert result is None
        below = [e for e in cap_logs if e.get("event") == "indexed_match_below_threshold"]
        assert len(below) == 1
        assert below[0]["type"] == "Location"

    async def test_indexed_error_graceful_degradation(self, respx_mock):
        """Indexed 500 for location → None, warning logged, no exception."""
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(500)
        config = LinkingConfig(enabled=True, url=INDEXED_URL)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_location(_location_index(), "Hütte", config)

        assert result is None
        failed = [e for e in cap_logs if e.get("event") == "indexed_match_failed"]
        assert len(failed) == 1
        assert failed[0]["type"] == "Location"
