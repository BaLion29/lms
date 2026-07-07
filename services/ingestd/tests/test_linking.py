"""Tests for ingestd.linking — generic entity index building, matching."""

from __future__ import annotations

import structlog
from unittest.mock import AsyncMock

import pytest

from ingestd.linking import (
    EntityIndex,
    LinkingConfig,
    async_match,
    async_match_location,
    build_index_from_classes,
    match,
    match_location,
    match_person,
)
from firnline_core.tdb import TdbError


# ---------------------------------------------------------------------------
# build_index_from_classes
# ---------------------------------------------------------------------------


class TestBuildIndexFromClasses:
    @pytest.mark.asyncio
    async def test_people_indexed_by_lowercase_name(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[
            {"@id": "Person/abc", "name": "Anna Meier"},
        ])
        index = await build_index_from_classes(tdb, ["Person"])
        assert index.entities["Person"] == {"anna meier": "Person/abc"}
        assert index.display["Person"] == [("Anna Meier", "Person/abc")]

    @pytest.mark.asyncio
    async def test_doc_without_name_skipped(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[
            {"@id": "Person/abc", "name": "Anna Meier"},
            {"@id": "Person/missing", "other": "value"},
        ])
        index = await build_index_from_classes(tdb, ["Person"])
        assert len(index.entities["Person"]) == 1
        assert "Person/missing" not in index.entities["Person"].values()

    @pytest.mark.asyncio
    async def test_location_aliases_indexed_to_same_iri(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[
            {
                "@id": "Location/hut1",
                "name": "Rotondohütte",
                "aliases": ["R Hütte", "Rotondo"],
            },
        ])
        index = await build_index_from_classes(tdb, ["Location"])
        assert index.lookup("Location", "rotondohütte") == "Location/hut1"
        assert index.lookup("Location", "r hütte") == "Location/hut1"
        assert index.lookup("Location", "rotondo") == "Location/hut1"
        assert index.display["Location"] == [("Rotondohütte", "Location/hut1")]

    @pytest.mark.asyncio
    async def test_locations_without_aliases(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[
            {"@id": "Location/simple", "name": "Zürich"},
        ])
        index = await build_index_from_classes(tdb, ["Location"])
        assert index.entities["Location"] == {"zürich": "Location/simple"}

    @pytest.mark.asyncio
    async def test_empty_inputs_produce_empty_index(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[])
        index = await build_index_from_classes(tdb, [])
        assert index.entities == {}
        assert index.display == {}

    @pytest.mark.asyncio
    async def test_casefold_handles_german_eszett(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(return_value=[
            {"@id": "Person/1", "name": "Straße"},
        ])
        index = await build_index_from_classes(tdb, ["Person"])
        assert index.lookup("Person", "strasse") == "Person/1"

    @pytest.mark.asyncio
    async def test_class_fetch_error_skipped(self):
        tdb = AsyncMock()
        tdb.get_documents = AsyncMock(side_effect=TdbError(404, "not found"))
        index = await build_index_from_classes(tdb, ["MissingClass", "Person"])
        # MissingClass skipped silently, no crash
        assert "MissingClass" not in index.entities
        assert "Person" not in index.entities


# ---------------------------------------------------------------------------
# match (generic)
# ---------------------------------------------------------------------------


class TestMatch:
    def test_exact_case_insensitive_hit(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        result = match(index, "Person", "anna meier")
        assert result == "Person/abc"

    def test_different_casing_still_hits(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        result = match(index, "Person", "ANNA MEIER")
        assert result == "Person/abc"

    def test_whitespace_stripped(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        result = match(index, "Person", "  anna meier  ")
        assert result == "Person/abc"

    def test_miss_returns_none(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        result = match(index, "Person", "Unbekannt Person")
        assert result is None

    def test_near_miss_substring_logged_returns_none(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        with structlog.testing.capture_logs() as cap_logs:
            result = match(index, "Person", "Anna")
        assert result is None
        assert len(cap_logs) == 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "anna"
        assert log["known"] == "anna meier"
        assert log["category"] == "person"
        assert log["reason"] == "substring"

    def test_near_miss_first_token_logged_returns_none(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        with structlog.testing.capture_logs() as cap_logs:
            result = match(index, "Person", "Anna Müller")
        assert result is None
        # first token match logs near_miss
        assert len(cap_logs) >= 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "anna müller"
        assert log["known"] == "anna meier"
        assert log["reason"] == "first_token"

    def test_german_eszett_casefold_match(self):
        index = EntityIndex()
        index.register("Person", "Straße", "Person/1")
        result = match(index, "Person", "Straße")
        assert result == "Person/1"

    def test_location_match_via_primary_name(self):
        index = EntityIndex()
        index.register("Location", "Rotondohütte", "Location/hut1")
        result = match(index, "Location", "Rotondohütte")
        assert result == "Location/hut1"

    def test_location_match_via_alias(self):
        index = EntityIndex()
        index.register("Location", "Rotondohütte", "Location/hut1")
        index.register("Location", "R Hütte", "Location/hut1")
        result = match(index, "Location", "R Hütte")
        assert result == "Location/hut1"

    def test_location_casefold_match_umlaut(self):
        index = EntityIndex()
        index.register("Location", "Rotondohütte", "Location/hut1")
        result = match(index, "Location", "ROTONDOHÜTTE")
        assert result == "Location/hut1"

    def test_location_miss_returns_none_with_near_miss_log(self):
        index = EntityIndex()
        index.register("Location", "Rotondohütte", "Location/hut1")
        with structlog.testing.capture_logs() as cap_logs:
            result = match(index, "Location", "Rotondo")
        assert result is None
        assert len(cap_logs) == 1
        log = cap_logs[0]
        assert log["event"] == "near_miss"
        assert log["proposed"] == "rotondo"
        assert log["known"] == "rotondohütte"
        assert log["reason"] == "substring"


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------


class TestBackwardCompatMatchPerson:
    def test_exact_hit(self):
        index = EntityIndex()
        index.register("Person", "Anna Meier", "Person/abc")
        result = match_person(index, "anna meier")
        assert result == "Person/abc"

    def test_miss_returns_none(self):
        index = EntityIndex()
        result = match_person(index, "Unknown")
        assert result is None


class TestBackwardCompatMatchLocation:
    def test_exact_hit(self):
        index = EntityIndex()
        index.register("Location", "Office", "Location/off")
        result = match_location(index, "Office")
        assert result == "Location/off"

    def test_alias_hit(self):
        index = EntityIndex()
        index.register("Location", "Rotondohütte", "Location/hut1")
        index.register("Location", "R Hütte", "Location/hut1")
        result = match_location(index, "R Hütte")
        assert result == "Location/hut1"


# ---------------------------------------------------------------------------
# Async matching — indexed service integration
# ---------------------------------------------------------------------------

INDEXED_URL = "http://indexed.test:8089"


def _person_index() -> EntityIndex:
    index = EntityIndex()
    index.register("Person", "Anna Meier", "Person/abc")
    return index


def _location_index() -> EntityIndex:
    index = EntityIndex()
    index.register("Location", "Rotondohütte", "Location/hut1")
    index.register("Location", "R Hütte", "Location/hut1")
    return index


class TestAsyncMatch:
    async def test_fast_path_exact_hit_no_http(self, respx_mock):
        route = respx_mock.post(f"{INDEXED_URL}/v1/find_entity")
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match(_person_index(), "Person", "Anna Meier", config)
        assert result == "Person/abc"
        assert not route.called

    async def test_disabled_config_miss_returns_none(self):
        config = LinkingConfig(enabled=False)
        result = await async_match(_person_index(), "Person", "Unknown", config)
        assert result is None

    async def test_high_confidence_accept(self, respx_mock):
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
            result = await async_match(
                _person_index(), "Person", "Unbekannt", config
            )

        assert result == "Person/xyz"
        accepted = [e for e in cap_logs if e.get("event") == "indexed_match_accepted"]
        assert len(accepted) == 1
        assert accepted[0]["type"] == "Person"
        assert accepted[0]["iri"] == "Person/xyz"
        assert accepted[0]["score"] == 0.92

    async def test_low_confidence_fall_through(self, respx_mock):
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
            result = await async_match(_person_index(), "Person", "Someone", config)

        assert result is None
        below = [e for e in cap_logs if e.get("event") == "indexed_match_below_threshold"]
        assert len(below) == 1
        assert below[0]["type"] == "Person"
        assert below[0]["score"] == 0.60

    async def test_indexed_error_graceful_degradation(self, respx_mock):
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(500)
        config = LinkingConfig(enabled=True, url=INDEXED_URL)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match(_person_index(), "Person", "Unknown", config)

        assert result is None
        failed = [e for e in cap_logs if e.get("event") == "indexed_match_failed"]
        assert len(failed) == 1
        assert failed[0]["type"] == "Person"


class TestAsyncMatchLocation:
    async def test_fast_path_exact_hit_no_http(self, respx_mock):
        route = respx_mock.post(f"{INDEXED_URL}/v1/find_entity")
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match_location(_location_index(), "Rotondohütte", config)
        assert result == "Location/hut1"
        assert not route.called

    async def test_fast_path_alias_hit(self):
        config = LinkingConfig(enabled=True, url=INDEXED_URL)
        result = await async_match_location(_location_index(), "R Hütte", config)
        assert result == "Location/hut1"

    async def test_high_confidence_accept(self, respx_mock):
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
        respx_mock.post(f"{INDEXED_URL}/v1/find_entity").respond(500)
        config = LinkingConfig(enabled=True, url=INDEXED_URL)

        with structlog.testing.capture_logs() as cap_logs:
            result = await async_match_location(_location_index(), "Hütte", config)

        assert result is None
        failed = [e for e in cap_logs if e.get("event") == "indexed_match_failed"]
        assert len(failed) == 1
        assert failed[0]["type"] == "Location"
