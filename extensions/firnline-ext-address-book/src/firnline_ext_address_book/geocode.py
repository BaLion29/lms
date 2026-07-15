"""Reusable async geocoding client for Nominatim-compatible services."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GeocodingSettings(BaseSettings):
    """Geocoding settings, loaded from GEOCODING_* env vars."""

    model_config = SettingsConfigDict(env_prefix="GEOCODING_")

    base_url: str = "https://nominatim.openstreetmap.org"
    api_key: str = ""
    timeout_seconds: float = 10.0
    user_agent: str = "firnline-address-book"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GeocodingClient:
    """Async geocoding client using the Nominatim ``/search`` endpoint.

    Usage::

        client = GeocodingClient()
        coords = await client.geocode("1600 Amphitheatre Parkway, Mountain View")
        # → (37.422, -122.084) or None
    """

    def __init__(self, settings: GeocodingSettings | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> GeocodingSettings:
        """Lazy-load settings on first use so import works without env vars."""
        if self._settings is None:
            self._settings = GeocodingSettings()  # type: ignore[call-arg]
        return self._settings

    async def geocode(self, query: str) -> tuple[float, float] | None:
        """Geocode *query* and return ``(lat, lon)``, or ``None`` when no result.

        Timeouts and HTTP errors are handled gracefully — they return ``None``
        rather than raising, so callers can treat failure as "no result".
        """
        settings = self.settings
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "limit": 1,
        }
        if settings.api_key:
            params["key"] = settings.api_key

        headers = {"User-Agent": settings.user_agent}
        url = f"{settings.base_url.rstrip('/')}/search"

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                response = await client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
            logger.warning("Geocoding network/timeout error for query: %s", query)
            return None
        except Exception:
            logger.exception("Geocoding unexpected error for query: %s", query)
            return None

        if response.status_code != 200:
            logger.warning(
                "Geocoding API returned %d for query: %s",
                response.status_code,
                query,
            )
            return None

        try:
            data = response.json()
        except Exception:
            logger.warning("Geocoding response is not valid JSON for query: %s", query)
            return None

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        try:
            first = data[0]
            lat = float(first["lat"])
            lon = float(first["lon"])
        except (KeyError, ValueError, TypeError):
            logger.warning("Geocoding response missing lat/lon for query: %s", query)
            return None

        return (lat, lon)
