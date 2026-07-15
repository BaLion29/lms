"""Tests for the GeocodingClient — Nominatim-compatible async geocoding."""

from __future__ import annotations

import httpx
import respx
from httpx import Response

from firnline_ext_address_book.geocode import GeocodingClient, GeocodingSettings


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_env_prefix() -> None:
    """GeocodingSettings uses GEOCODING_ env prefix."""
    assert GeocodingSettings.model_config.get("env_prefix") == "GEOCODING_"


def test_settings_defaults() -> None:
    """GeocodingSettings has sensible defaults."""
    s = GeocodingSettings()
    assert s.base_url == "https://nominatim.openstreetmap.org"
    assert s.api_key == ""
    assert s.timeout_seconds == 10.0
    assert s.user_agent == "firnline-address-book"


def test_settings_from_env(monkeypatch) -> None:
    """Settings are loaded from GEOCODING_* env vars."""
    monkeypatch.setenv("GEOCODING_BASE_URL", "https://geo.example.com")
    monkeypatch.setenv("GEOCODING_API_KEY", "secret")
    monkeypatch.setenv("GEOCODING_TIMEOUT_SECONDS", "5.0")
    monkeypatch.setenv("GEOCODING_USER_AGENT", "my-agent")

    s = GeocodingSettings()
    assert s.base_url == "https://geo.example.com"
    assert s.api_key == "secret"
    assert s.timeout_seconds == 5.0
    assert s.user_agent == "my-agent"


# ---------------------------------------------------------------------------
# Lazy settings loading
# ---------------------------------------------------------------------------


def test_import_works_without_env_vars() -> None:
    """Module-level import succeeds without GEOCODING_* env vars."""
    client = GeocodingClient()
    s = client.settings
    assert s.base_url == "https://nominatim.openstreetmap.org"


# ---------------------------------------------------------------------------
# Geocoding — success
# ---------------------------------------------------------------------------


async def test_geocode_success() -> None:
    """Successful geocoding returns lat/lon tuple."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://geo.example.com/search").mock(
            return_value=Response(
                200,
                json=[{"lat": "52.52", "lon": "13.405"}],
            )
        )
        result = await client.geocode("Berlin")

    assert result == (52.52, 13.405)
    assert route.called
    req = route.calls.last.request
    assert req.url.params.get("q") == "Berlin"
    assert req.url.params.get("format") == "json"
    assert req.url.params.get("limit") == "1"
    assert req.headers["User-Agent"] == "firnline-address-book"


async def test_geocode_sends_api_key_when_set() -> None:
    """api_key is sent as query param when configured."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com", api_key="secret-key")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(200, json=[{"lat": "0", "lon": "0"}])
        result = await client.geocode("test")

    assert result == (0.0, 0.0)


async def test_geocode_no_api_key_when_empty() -> None:
    """No key param is sent when api_key is empty."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com", api_key="")
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://geo.example.com/search").respond(200, json=[{"lat": "0", "lon": "0"}])
        await client.geocode("test")

    assert "key" not in route.calls.last.request.url.params


async def test_geocode_strips_trailing_slash() -> None:
    """Base URL trailing slash is stripped before appending /search."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com/")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(200, json=[{"lat": "0", "lon": "0"}])
        result = await client.geocode("test")

    assert result == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Geocoding — no result
# ---------------------------------------------------------------------------


async def test_geocode_empty_results_returns_none() -> None:
    """Empty Nominatim results → None."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(200, json=[])
        result = await client.geocode("nowhere")

    assert result is None


async def test_geocode_non_200_returns_none() -> None:
    """Non-200 HTTP response → None."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(500)
        result = await client.geocode("Berlin")

    assert result is None


async def test_geocode_missing_lat_lon_returns_none() -> None:
    """Response object missing lat/lon → None."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(200, json=[{"display_name": "Nowhere"}])
        result = await client.geocode("nowhere")

    assert result is None


async def test_geocode_not_json_returns_none() -> None:
    """Non-JSON response → None."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").respond(200, text="not json")
        result = await client.geocode("Berlin")

    assert result is None


# ---------------------------------------------------------------------------
# Geocoding — timeout
# ---------------------------------------------------------------------------


async def test_geocode_timeout_returns_none() -> None:
    """Timeout exception → None (not raised)."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com", timeout_seconds=1.0)
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        result = await client.geocode("Berlin")

    assert result is None


async def test_geocode_connect_error_returns_none() -> None:
    """ConnectError → None."""
    client = GeocodingClient(
        GeocodingSettings(base_url="https://geo.example.com")
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://geo.example.com/search").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = await client.geocode("Berlin")

    assert result is None
