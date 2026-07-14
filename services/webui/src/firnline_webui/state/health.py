"""Health-check state — polls captured / queryd / indexed / mcpd healthz."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import reflex as rx

from firnline_webui.clients import make_health_clients
from firnline_webui.state.base import BaseState

logger = logging.getLogger(__name__)


class HealthState(BaseState):
    """Health-check results for all monitored services."""

    # captured
    captured_status: str = "unknown"
    captured_version: str = ""
    captured_terminusdb: str = "unknown"
    captured_handlers: list[str] = []  # type: ignore[assignment]
    captured_blob_root_writable: bool = False
    captured_blob_root_writable_available: bool = False

    # queryd
    queryd_status: str = "unknown"
    queryd_version: str = ""
    queryd_terminusdb: str = "unknown"
    queryd_plugins: list[str] = []  # type: ignore[assignment]

    # indexed
    indexed_status: str = "unknown"
    indexed_version: str = "\u2014"  # indexed has no version field
    indexed_terminusdb: str = "unknown"
    indexed_plugins: list[str] = []  # type: ignore[assignment]  # indexed has no plugins
    indexed_store: str = "\u2014"
    indexed_poller: str = "\u2014"

    # mcpd
    mcpd_status: str = "unknown"

    loading: bool = False
    last_refresh: str = ""

    @staticmethod
    def _parse_terminusdb(data: dict) -> str:
        """Extract terminusdb status from flat string or nested dict (legacy fallback)."""
        td = data.get("terminusdb", "unknown")
        if isinstance(td, dict):
            return str(td.get("status", "unknown"))
        return str(td) if td else "unknown"

    async def _fetch_single(self, name: str, coro) -> dict:
        try:
            return await coro
        except Exception:
            logger.warning("healthz fetch failed for %s", name, exc_info=True)
            return {"status": "unreachable"}

    @rx.event
    async def refresh(self):
        """Refresh health data from all monitored services concurrently."""
        self.loading = True
        yield

        c_cap, c_qry, c_idx, c_mcpd = make_health_clients()
        cap_r, qry_r, idx_r, mcpd_r = await asyncio.gather(
            self._fetch_single("captured", c_cap.healthz()),
            self._fetch_single("queryd", c_qry.healthz()),
            self._fetch_single("indexed", c_idx.healthz()),
            self._fetch_single("mcpd", c_mcpd.healthz()),
        )

        self._apply_captured(cap_r)
        self._apply_queryd(qry_r)
        self._apply_indexed(idx_r)
        self._apply_mcpd(mcpd_r)

        self.loading = False
        self.last_refresh = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        yield

    def _apply_captured(self, data: dict) -> None:
        self.captured_status = data.get("status", "unknown")
        self.captured_version = data.get("version", "")
        self.captured_terminusdb = self._parse_terminusdb(data)
        self.captured_handlers = data.get("handlers", data.get("plugins", [])) or []
        blob = data.get("blob_root_writable")
        self.captured_blob_root_writable_available = blob is not None
        self.captured_blob_root_writable = bool(blob)

    def _apply_queryd(self, data: dict) -> None:
        self.queryd_status = data.get("status", "unknown")
        self.queryd_version = data.get("version", "")
        self.queryd_terminusdb = self._parse_terminusdb(data)
        self.queryd_plugins = data.get("plugins", []) or []

    def _apply_indexed(self, data: dict) -> None:
        self.indexed_status = data.get("status", "unknown")
        self.indexed_version = "\u2014"  # indexed has no version field
        self.indexed_terminusdb = self._parse_terminusdb(data)
        self.indexed_plugins = []  # indexed has no plugins
        self.indexed_store = str(data.get("store", "\u2014")) or "\u2014"
        self.indexed_poller = str(data.get("poller", "\u2014")) or "\u2014"

    def _apply_mcpd(self, data: dict) -> None:
        self.mcpd_status = data.get("status", "unknown")
