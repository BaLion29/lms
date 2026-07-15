"""Tests for firnline_ext_address_book.tools — address-book ToolSpec handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firnline_core.toolspec import ToolContext

from firnline_ext_address_book.tools import (
    AddressBookToolsPlugin,
    GeocodeArgs,
    _do_create_location,
    _do_create_organization,
    _do_create_person,
    _do_geocode,
    _do_get,
    _do_lookup,
    _handle_create_location,
    _handle_create_organization,
    _handle_create_person,
    _handle_geocode,
    _handle_get,
    _handle_lookup,
    plugin,
)

# ---------------------------------------------------------------------------
# Fake documents
# ---------------------------------------------------------------------------

_UTC = timezone.utc

_PERSON_ALICE = {
    "@id": "Person/alice",
    "@type": "Person",
    "name": "Alice Smith",
    "aliases": ["Ally", "A. Smith"],
}

_PERSON_BOB = {
    "@id": "Person/bob",
    "@type": "Person",
    "name": "Bob Jones",
    "aliases": ["Bobby"],
}

_LOCATION_OFFICE = {
    "@id": "Location/office",
    "@type": "Location",
    "name": "Main Office",
    "aliases": ["HQ"],
    "address": "123 Main St",
    "coordinates": None,
}

_LOCATION_HOME = {
    "@id": "Location/home",
    "@type": "Location",
    "name": "Home Base",
    "aliases": [],
    "address": None,
    "coordinates": [40.7128, -74.0060],
}

_ORG_ACME = {
    "@id": "Organization/acme",
    "@type": "Organization",
    "name": "ACME Corp",
    "aliases": ["ACME"],
}


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


def test_plugin_name_and_requires():
    assert plugin.name == "address_book_tools"
    reqs = plugin.requires
    assert len(reqs) == 1
    assert reqs[0].name == "address_book"
    assert reqs[0].range == ">=0.1.0 <0.2.0"


def test_plugin_tool_specs():
    specs = plugin.tool_specs()
    names = {s.name for s in specs}
    assert names == {
        "address_book_lookup",
        "address_book_get",
        "address_book_create_person",
        "address_book_create_location",
        "address_book_create_organization",
        "address_book_geocode",
    }


def test_plugin_no_legacy_tools_method():
    """Plugin does NOT implement legacy ToolPlugin.tools()."""
    assert not hasattr(plugin, "tools")


# ---------------------------------------------------------------------------
# Helper: build a mock tdb + ToolContext
# ---------------------------------------------------------------------------


def _make_ctx(tdb: MagicMock | None = None) -> ToolContext:
    if tdb is None:
        tdb = MagicMock()
    return ToolContext(tdb=tdb, branch="main")


# ---------------------------------------------------------------------------
# _do_lookup
# ---------------------------------------------------------------------------


async def test_lookup_match_all():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(
        side_effect=lambda cls, branch: {
            "Person": [_PERSON_ALICE, _PERSON_BOB],
            "Location": [_LOCATION_OFFICE, _LOCATION_HOME],
            "Organization": [_ORG_ACME],
        }.get(cls, [])
    )

    result = await _do_lookup("a", 10, None, tdb=tdb, branch="main")
    assert result["ok"] is True
    # "a" matches "Alice Smith" (Person), "ACM" in ACME (Organization), but not Bob/Office/Home
    names = [h["name"] for h in result["hits"]]
    assert "Alice Smith" in names
    assert "ACME Corp" in names


async def test_lookup_match_alias():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_PERSON_BOB])

    result = await _do_lookup("bobby", 10, "person", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert len(result["hits"]) == 1
    assert result["hits"][0]["name"] == "Bob Jones"


async def test_lookup_no_match():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_PERSON_ALICE, _PERSON_BOB])

    result = await _do_lookup("xyzzy", 10, "person", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert result["hits"] == []


async def test_lookup_kind_filter_person():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_PERSON_ALICE])

    result = await _do_lookup("alice", 10, "person", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert len(result["hits"]) == 1
    assert result["hits"][0]["type"] == "person"


async def test_lookup_kind_filter_location():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_LOCATION_OFFICE])

    result = await _do_lookup("office", 10, "location", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert len(result["hits"]) == 1
    assert result["hits"][0]["type"] == "location"


async def test_lookup_kind_filter_organization():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_ORG_ACME])

    result = await _do_lookup("acme", 10, "organization", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert len(result["hits"]) == 1
    assert result["hits"][0]["type"] == "organization"


async def test_lookup_invalid_kind():
    result = await _do_lookup("test", 10, "penguin", tdb=MagicMock(), branch="main")
    assert result["ok"] is False
    assert "invalid kind filter" in result["error"]


async def test_lookup_limit():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(
        side_effect=lambda cls, branch: {
            "Person": [_PERSON_ALICE, _PERSON_BOB],
        }.get(cls, [])
    )

    result = await _do_lookup("a", 1, "person", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert len(result["hits"]) == 1


async def test_lookup_tdb_error_graceful():
    """If a class's documents can't be fetched, skip it gracefully."""
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(side_effect=RuntimeError("boom"))

    result = await _do_lookup("test", 10, None, tdb=tdb, branch="main")
    assert result["ok"] is True
    assert result["hits"] == []


# ---------------------------------------------------------------------------
# _do_get
# ---------------------------------------------------------------------------


async def test_get_found():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_PERSON_ALICE))

    result = await _do_get("Person/alice", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert result["doc"]["name"] == "Alice Smith"


async def test_get_not_found():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(side_effect=RuntimeError("not found"))

    result = await _do_get("Person/nope", tdb=tdb, branch="main")
    assert result["ok"] is False
    assert "document not found" in result["error"]


# ---------------------------------------------------------------------------
# _do_create_person
# ---------------------------------------------------------------------------


async def test_create_person_minimal():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Person/p1"])

    result = await _do_create_person("Alice Smith", [], None, None, None, tdb=tdb, branch="main")
    assert result["ok"] is True
    assert "iri" in result
    assert tdb.insert_documents.called

    # Verify the doc body
    args, kwargs = tdb.insert_documents.call_args
    docs = kwargs.get("branch") is not None and args[0] or kwargs.get("branch") is None and args[0]
    # Actually insert_documents(docs, branch=..., message=...) so args[0] is [doc]
    sent = args[0]
    doc = sent[0] if isinstance(sent, list) else sent
    assert doc["name"] == "Alice Smith"
    assert doc["@type"] == "Person"


async def test_create_person_with_contact():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Person/p2"])

    result = await _do_create_person(
        "Bob", ["Bobby"], "bob@test.com", "+123", None, tdb=tdb, branch="main"
    )
    assert result["ok"] is True

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    contact = doc["contact"]
    assert contact["email"] == "bob@test.com"
    assert contact["phone"] == "+123"


async def test_create_person_with_valid_domicile():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_LOCATION_OFFICE))
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Person/p3"])

    result = await _do_create_person(
        "Alice", [], None, None, "Location/office", tdb=tdb, branch="main"
    )
    assert result["ok"] is True

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    assert doc["contact"]["domicile"] == "Location/office"


async def test_create_person_invalid_domicile():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(side_effect=RuntimeError("not found"))
    tdb.insert_documents = AsyncMock()

    result = await _do_create_person(
        "Alice", [], None, None, "Location/nope", tdb=tdb, branch="main"
    )
    assert result["ok"] is False
    assert "location not found" in result["error"]
    assert not tdb.insert_documents.called


async def test_create_person_domicile_wrong_type():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_PERSON_BOB))  # not a Location
    tdb.insert_documents = AsyncMock()

    result = await _do_create_person(
        "Alice", [], None, None, "Person/bob", tdb=tdb, branch="main"
    )
    assert result["ok"] is False
    assert "not a Location" in result["error"]
    assert not tdb.insert_documents.called


# ---------------------------------------------------------------------------
# _do_create_location
# ---------------------------------------------------------------------------


async def test_create_location_minimal():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Location/l1"])

    result = await _do_create_location("Office", [], None, None, None, tdb=tdb, branch="main")
    assert result["ok"] is True
    assert "iri" in result

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    assert doc["name"] == "Office"
    assert doc["@type"] == "Location"


async def test_create_location_with_coordinates():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Location/l2"])

    result = await _do_create_location(
        "HQ", ["Headquarters"], "123 Main St", 40.7128, -74.0060, tdb=tdb, branch="main"
    )
    assert result["ok"] is True

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    assert doc["name"] == "HQ"
    assert doc["address"] == "123 Main St"
    assert doc["coordinates"] == [40.7128, -74.0060]
    assert doc["aliases"] == ["Headquarters"]


# ---------------------------------------------------------------------------
# _do_create_organization
# ---------------------------------------------------------------------------


async def test_create_organization_minimal():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Organization/o1"])

    result = await _do_create_organization("ACME", [], None, tdb=tdb, branch="main")
    assert result["ok"] is True
    assert "iri" in result

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    assert doc["name"] == "ACME"
    assert doc["@type"] == "Organization"


async def test_create_organization_with_valid_location():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_LOCATION_OFFICE))
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Organization/o2"])

    result = await _do_create_organization(
        "ACME", ["Acme Inc"], "Location/office", tdb=tdb, branch="main"
    )
    assert result["ok"] is True

    sent = tdb.insert_documents.call_args[0][0]
    doc = sent[0]
    assert doc["location"] == "Location/office"


async def test_create_organization_invalid_location():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(side_effect=RuntimeError("not found"))
    tdb.insert_documents = AsyncMock()

    result = await _do_create_organization(
        "ACME", [], "Location/nope", tdb=tdb, branch="main"
    )
    assert result["ok"] is False
    assert "location not found" in result["error"]


# ---------------------------------------------------------------------------
# _do_geocode
# ---------------------------------------------------------------------------


async def test_geocode_by_query_success():
    tdb = MagicMock()
    with patch(
        "firnline_ext_address_book.tools.GeocodingClient.geocode",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = (52.52, 13.405)
        result = await _do_geocode("Berlin", None, tdb=tdb, branch="main")

    assert result["ok"] is True
    assert result["coordinates"] == [52.52, 13.405]


async def test_geocode_by_query_no_result():
    tdb = MagicMock()
    with patch(
        "firnline_ext_address_book.tools.GeocodingClient.geocode",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = None
        result = await _do_geocode("nowhere", None, tdb=tdb, branch="main")

    assert result["ok"] is False
    assert "no geocoding result" in result["error"]


async def test_geocode_by_query_geocoder_exception():
    tdb = MagicMock()
    with patch(
        "firnline_ext_address_book.tools.GeocodingClient.geocode",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.side_effect = RuntimeError("network down")
        result = await _do_geocode("Berlin", None, tdb=tdb, branch="main")

    assert result["ok"] is False
    assert "geocoding failed unexpectedly" in result["error"]


async def test_geocode_by_location_id_persists():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_LOCATION_OFFICE))
    tdb.insert_documents = AsyncMock()

    with patch(
        "firnline_ext_address_book.tools.GeocodingClient.geocode",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = (40.7128, -74.0060)
        result = await _do_geocode(None, "Location/office", tdb=tdb, branch="main")

    assert result["ok"] is True
    assert result["coordinates"] == [40.7128, -74.0060]
    assert tdb.insert_documents.called
    # Verify coordinates were persisted
    sent_docs = tdb.insert_documents.call_args[0][0]
    assert sent_docs[0]["coordinates"] == [40.7128, -74.0060]


async def test_geocode_by_location_id_already_has_coordinates():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_LOCATION_HOME))
    tdb.insert_documents = AsyncMock()

    result = await _do_geocode(None, "Location/home", tdb=tdb, branch="main")
    assert result["ok"] is True
    assert result["coordinates"] == [40.7128, -74.0060]
    assert result.get("already_set") is True
    assert not tdb.insert_documents.called


async def test_geocode_by_location_id_not_found():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(side_effect=RuntimeError("not found"))

    result = await _do_geocode(None, "Location/nope", tdb=tdb, branch="main")
    assert result["ok"] is False
    assert "location not found" in result["error"]


async def test_geocode_by_location_id_wrong_type():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_PERSON_ALICE))

    result = await _do_geocode(None, "Person/alice", tdb=tdb, branch="main")
    assert result["ok"] is False
    assert "not a Location" in result["error"]


async def test_geocode_no_query_and_no_location_id():
    result = await _do_geocode(None, None, tdb=MagicMock(), branch="main")
    assert result["ok"] is False
    assert "exactly one" in result["error"]


async def test_geocode_both_query_and_location_id():
    result = await _do_geocode("Berlin", "Location/office", tdb=MagicMock(), branch="main")
    assert result["ok"] is False
    assert "exactly one" in result["error"]


# ---------------------------------------------------------------------------
# ToolSpec handler integration tests (handler → _do_*)
# ---------------------------------------------------------------------------


async def test_handler_lookup():
    tdb = MagicMock()
    tdb.get_documents = AsyncMock(return_value=[_PERSON_ALICE])
    ctx = ToolContext(tdb=tdb, branch="main")

    from firnline_ext_address_book.tools import LookupArgs

    result = await _handle_lookup(LookupArgs(query="alice", limit=10, kind="person"), ctx)
    assert result["ok"] is True
    assert len(result["hits"]) == 1


async def test_handler_get():
    tdb = MagicMock()
    tdb.get_document = AsyncMock(return_value=dict(_PERSON_ALICE))
    ctx = ToolContext(tdb=tdb, branch="main")

    from firnline_ext_address_book.tools import GetArgs

    result = await _handle_get(GetArgs(id="Person/alice"), ctx)
    assert result["ok"] is True
    assert result["doc"]["name"] == "Alice Smith"


async def test_handler_create_person():
    tdb = MagicMock()
    tdb.insert_documents = AsyncMock(return_value=["terminusdb:///data/Person/p1"])
    ctx = ToolContext(tdb=tdb, branch="main")

    from firnline_ext_address_book.tools import CreatePersonArgs

    result = await _handle_create_person(
        CreatePersonArgs(name="Alice", email="a@b.com"), ctx
    )
    assert result["ok"] is True


async def test_handler_geocode():
    tdb = MagicMock()
    ctx = ToolContext(tdb=tdb, branch="main")

    with patch(
        "firnline_ext_address_book.tools.GeocodingClient.geocode",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = (1.0, 2.0)
        result = await _handle_geocode(GeocodeArgs(query="Berlin"), ctx)

    assert result["ok"] is True
    assert result["coordinates"] == [1.0, 2.0]


# ---------------------------------------------------------------------------
# Plugin is importable as entry point
# ---------------------------------------------------------------------------


def test_plugin_module_level():
    """plugin at module level is an AddressBookToolsPlugin instance."""
    assert isinstance(plugin, AddressBookToolsPlugin)
