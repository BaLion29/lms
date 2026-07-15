"""Tests for AddressBookGeocoderExecutor — location enrichment ActionExecutor."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from firnline_core.plugins import (
    ActionContext,
    ActionExecutor,
    ExecutionResult,
    validate_plugin,
)

from firnline_ext_address_book.enrich import AddressBookGeocoderExecutor, plugin
from firnline_ext_address_book.geocode import GeocodingSettings


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_plugin_is_action_executor() -> None:
    """plugin instance passes isinstance check against ActionExecutor."""
    assert isinstance(plugin, ActionExecutor)


def test_plugin_name_requires_kinds() -> None:
    """plugin has correct name, requires, and kinds."""
    assert plugin.name == "address_book_geocoder"
    assert plugin.kinds == ("address_book_geocoder",)
    assert len(plugin.requires) == 1
    assert plugin.requires[0].name == "address_book"
    assert plugin.requires[0].range == ">=0.1.0 <0.2.0"


def test_validate_plugin_returns_empty() -> None:
    """Structural validation against ActionExecutor returns no violations."""
    violations = validate_plugin(plugin, ActionExecutor)
    assert violations == []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_lazy_loading() -> None:
    """Settings are loaded lazily on first access."""
    executor = AddressBookGeocoderExecutor()
    s = executor.settings
    assert isinstance(s, GeocodingSettings)
    assert s.base_url == "https://nominatim.openstreetmap.org"


def test_import_works_without_env_vars() -> None:
    """Module-level plugin import succeeds without GEOCODING_* env vars."""
    assert plugin is not None
    s = plugin.settings
    assert s.base_url == "https://nominatim.openstreetmap.org"


# ---------------------------------------------------------------------------
# No subject
# ---------------------------------------------------------------------------


async def test_no_subject_returns_not_retryable() -> None:
    """When subject is None, returns not-retryable."""
    executor = _configured_executor()
    ctx = _ctx()

    result = await executor.execute({}, {}, None, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "No subject" in result.detail


# ---------------------------------------------------------------------------
# Wrong type
# ---------------------------------------------------------------------------


async def test_subject_not_location_returns_not_retryable() -> None:
    """When subject is not a Location, returns not-retryable."""
    executor = _configured_executor()
    ctx = _ctx()

    subject: dict[str, object] = {"@id": "Person/p1", "@type": "Person", "name": "Alice"}
    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "not a Location" in result.detail


# ---------------------------------------------------------------------------
# Already has coordinates — skip
# ---------------------------------------------------------------------------


async def test_already_has_coordinates_skips() -> None:
    """Location already has coordinates → skip, return ok."""
    executor = _configured_executor()
    ctx = _ctx()

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Berlin",
        "address": "Berlin, Germany",
        "coordinates": [52.52, 13.405],
    }
    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is True
    assert "already has coordinates" in result.detail


# ---------------------------------------------------------------------------
# No address, no name
# ---------------------------------------------------------------------------


async def test_no_address_no_name_returns_not_retryable() -> None:
    """Location with no address and no name → not-retryable."""
    executor = _configured_executor()
    ctx = _ctx()

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "",
        "address": None,
    }
    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is False
    assert result.retryable is False
    assert "no address or name" in result.detail.lower()


# ---------------------------------------------------------------------------
# Happy path — geocoding succeeds, coordinate written back
# ---------------------------------------------------------------------------


async def test_geocode_success_updates_document() -> None:
    """Successful geocoding writes coordinates back via ctx.tdb."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    tdb_mock.insert_documents = AsyncMock(return_value=["Location/loc1"])
    ctx = _ctx(tdb=tdb_mock)

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Bern",
        "address": "Bern, Switzerland",
        "coordinates": None,
    }

    # Replace the internal client with a mock
    mock_client = MagicMock()
    mock_client.geocode = AsyncMock(return_value=(46.948, 7.4474))
    executor._client = mock_client

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is True
    assert "Geocoded" in result.detail
    assert "46.948" in result.detail

    # Verify TDB write
    tdb_mock.insert_documents.assert_called_once()
    call_args = tdb_mock.insert_documents.call_args
    docs = call_args[0][0]
    assert len(docs) == 1
    updated = docs[0]
    assert updated["@id"] == "Location/loc1"
    assert updated["coordinates"] == [46.948, 7.4474]

    # Verify geocoding call used address (not name)
    mock_client.geocode.assert_called_once_with("Bern, Switzerland")


async def test_geocode_falls_back_to_name() -> None:
    """When address is None, name is used as query."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    tdb_mock.insert_documents = AsyncMock(return_value=["Location/loc1"])
    ctx = _ctx(tdb=tdb_mock)

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Zürich",
        "address": None,
        "coordinates": None,
    }

    mock_client = MagicMock()
    mock_client.geocode = AsyncMock(return_value=(47.3769, 8.5417))
    executor._client = mock_client

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is True
    mock_client.geocode.assert_called_once_with("Zürich")
    assert "47.3769" in result.detail


# ---------------------------------------------------------------------------
# Geocoding returns None — retryable failure
# ---------------------------------------------------------------------------


async def test_geocode_no_result_returns_retryable() -> None:
    """Geocoding returns None → retryable failure, no TDB write."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    ctx = _ctx(tdb=tdb_mock)

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Narnia",
        "address": "Wardrobe",
        "coordinates": None,
    }

    mock_client = MagicMock()
    mock_client.geocode = AsyncMock(return_value=None)
    executor._client = mock_client

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "no result" in result.detail.lower()
    tdb_mock.insert_documents.assert_not_called()


# ---------------------------------------------------------------------------
# TDB write failure
# ---------------------------------------------------------------------------


async def test_tdb_write_failure_returns_retryable() -> None:
    """TDB insert_documents raises → retryable failure."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    tdb_mock.insert_documents = AsyncMock(side_effect=RuntimeError("TDB down"))
    ctx = _ctx(tdb=tdb_mock)

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Paris",
        "address": "Paris, France",
        "coordinates": None,
    }

    mock_client = MagicMock()
    mock_client.geocode = AsyncMock(return_value=(48.8566, 2.3522))
    executor._client = mock_client

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is False
    assert result.retryable is True
    assert "Failed to update" in result.detail


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


async def test_dry_run_skips_everything() -> None:
    """ctx.dry_run=True returns ok without any TDB write or geocode call."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    ctx = _ctx(tdb=tdb_mock, dry_run=True)

    mock_client = MagicMock()
    mock_client.geocode = AsyncMock()
    executor._client = mock_client

    subject: dict[str, object] = {
        "@id": "Location/loc1",
        "@type": "Location",
        "name": "Berlin",
        "address": None,
        "coordinates": None,
    }

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is True
    assert result.detail == "dry_run"
    tdb_mock.insert_documents.assert_not_called()
    mock_client.geocode.assert_not_called()


# ---------------------------------------------------------------------------
# Address with empty string is treated as missing
# ---------------------------------------------------------------------------


async def test_empty_address_falls_back_to_name() -> None:
    """Empty string address is treated like None — name used instead."""
    executor = _configured_executor()

    tdb_mock = AsyncMock()
    tdb_mock.insert_documents = AsyncMock(return_value=["Location/loc1"])
    ctx = _ctx(tdb=tdb_mock)

    subject: dict[str, object] = {
        "@id": "Location/loc2",
        "@type": "Location",
        "name": "Geneva",
        "address": "",
        "coordinates": None,
    }

    mock_client = MagicMock()
    mock_client.geocode = AsyncMock(return_value=(46.2044, 6.1432))
    executor._client = mock_client

    result = await executor.execute({}, {}, subject, ctx)

    assert result.ok is True
    mock_client.geocode.assert_called_once_with("Geneva")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configured_executor() -> AddressBookGeocoderExecutor:
    """Return an AddressBookGeocoderExecutor pre-configured with test settings."""
    executor = AddressBookGeocoderExecutor()
    executor._settings = GeocodingSettings(
        base_url="https://geo.example.com",
        timeout_seconds=10,
    )
    return executor


def _ctx(
    tdb: AsyncMock | None = None,
    dry_run: bool = False,
) -> ActionContext:
    return ActionContext(
        tdb=tdb or AsyncMock(),
        logger=MagicMock(),
        now=lambda: datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
        idempotency_key="ik-test",
        dry_run=dry_run,
    )
