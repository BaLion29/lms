"""Address book location geocoding ActionExecutor plugin.

Entry-point group: ``firnline.effectd.executors``
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from firnline_core.plugins import ActionContext, ExecutionResult, ModuleRequirement

from firnline_ext_address_book.geocode import GeocodingClient, GeocodingSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class AddressBookGeocoderExecutor:
    """Geocode Location entities on trigger firing.

    Expects the firing's subject IRI to resolve to a ``Location`` document.
    When the Location lacks ``coordinates`` and has an ``address`` (or at
    least a ``name``), this executor calls the configured geocoding service
    and writes the resulting lat/lon back to the document.
    """

    name: str = "address_book_geocoder"
    requires: list[ModuleRequirement] = [
        ModuleRequirement(name="address_book", range=">=0.2.0 <0.3.0"),
    ]
    kinds: tuple[str, ...] = ("address_book_geocoder",)

    def __init__(self) -> None:
        self._settings: GeocodingSettings | None = None
        self._client: GeocodingClient | None = None

    @property
    def settings(self) -> GeocodingSettings:
        """Lazy-load settings on first use so import works without env vars."""
        if self._settings is None:
            self._settings = GeocodingSettings()  # type: ignore[call-arg]
        return self._settings

    @property
    def client(self) -> GeocodingClient:
        """Lazy-load geocoding client on first use."""
        if self._client is None:
            self._client = GeocodingClient(settings=self.settings)
        return self._client

    async def execute(
        self,
        action: dict[str, Any],
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: ActionContext,
    ) -> ExecutionResult:
        # ── Dry-run — no side effects ────────────────────────────────
        if ctx.dry_run:
            return ExecutionResult(ok=True, detail="dry_run")

        # ── Need a subject document (Location) ───────────────────────
        if not subject:
            return ExecutionResult(
                ok=False,
                detail="No subject document — need a Location to geocode",
                retryable=False,
            )

        doc_id: str = subject.get("@id", "?")

        # ── Verify this is a Location ────────────────────────────────
        if subject.get("@type") != "Location":
            return ExecutionResult(
                ok=False,
                detail=f"Subject is not a Location (got {subject.get('@type')}), skipping",
                retryable=False,
            )

        # ── Idempotency: skip if already geocoded ────────────────────
        if subject.get("coordinates") is not None:
            return ExecutionResult(
                ok=True,
                detail=f"Location {doc_id} already has coordinates, skipping",
            )

        # ── Determine query string — address first, name fallback ────
        address: str | None = subject.get("address")
        name: str | None = subject.get("name")
        query: str | None = address or name
        if not query:
            return ExecutionResult(
                ok=False,
                detail=f"Location {doc_id} has no address or name to geocode",
                retryable=False,
            )

        # ── Geocode ──────────────────────────────────────────────────
        coords = await self.client.geocode(query)
        if coords is None:
            return ExecutionResult(
                ok=False,
                detail=f"Geocoding returned no result for '{query}'",
                retryable=True,
            )

        # ── Write coordinates back ───────────────────────────────────
        now = ctx.now()
        now_str = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        updated: dict[str, Any] = dict(subject)
        updated["coordinates"] = list(coords)
        updated["updated_at"] = now_str

        try:
            await ctx.tdb.insert_documents(
                [updated],
                message=f"effectd: geocoded {doc_id}",
            )
        except Exception as exc:
            logger.exception("Failed to write coordinates for %s", doc_id)
            return ExecutionResult(
                ok=False,
                detail=f"Failed to update {doc_id}: {exc}",
                retryable=True,
            )

        return ExecutionResult(
            ok=True,
            detail=f"Geocoded {doc_id} → ({coords[0]}, {coords[1]})",
        )


plugin = AddressBookGeocoderExecutor()
