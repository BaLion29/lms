"""Health-check state — polls captured / queryd / indexed healthz."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import reflex as rx

from firnline_webui.settings import get_settings
from firnline_webui.clients import (
    CapturedClient,
    IndexedHealthClient,
    QuerydClient,
)
from firnline_webui.state.base import BaseState


_settings = get_settings()


def _make_clients() -> tuple[CapturedClient, QuerydClient, IndexedHealthClient]:
    timeout = _settings.request_timeout_seconds
    return (
        CapturedClient(_settings.captured_url, _settings.captured_api_token, timeout=timeout),
        QuerydClient(_settings.queryd_url, _settings.queryd_api_token, timeout=timeout),
        IndexedHealthClient(_settings.indexed_url, timeout=timeout),
    )


class HealthState(BaseState):
    """Health-check results for all three services."""

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
    indexed_version: str = ""
    indexed_terminusdb: str = "unknown"
    indexed_plugins: list[str] = []  # type: ignore[assignment]
    indexed_blob_root_writable: bool = False
    indexed_blob_root_writable_available: bool = False

    loading: bool = False
    last_refresh: str = ""

    async def _fetch_single(self, name: str, coro) -> dict:
        try:
            return await coro
        except Exception:
            return {"status": "unreachable"}

    @rx.event
    async def refresh(self):
        """Refresh health data from all three services concurrently."""
        self.loading = True
        yield

        c_cap, c_qry, c_idx = _make_clients()
        cap_r, qry_r, idx_r = await asyncio.gather(
            self._fetch_single("captured", c_cap.healthz()),
            self._fetch_single("queryd", c_qry.healthz()),
            self._fetch_single("indexed", c_idx.healthz()),
        )

        self._apply_captured(cap_r)
        self._apply_queryd(qry_r)
        self._apply_indexed(idx_r)

        self.loading = False
        self.last_refresh = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        yield

    def _apply_captured(self, data: dict) -> None:
        self.captured_status = data.get("status", "unknown")
        self.captured_version = data.get("version", "")
        td = data.get("terminusdb", {})
        if isinstance(td, dict):
            self.captured_terminusdb = td.get("status", "unknown")
        else:
            self.captured_terminusdb = str(td) if td else "unknown"
        self.captured_handlers = data.get("handlers", data.get("plugins", [])) or []
        blob = data.get("blob_root_writable")
        self.captured_blob_root_writable_available = blob is not None
        self.captured_blob_root_writable = bool(blob)

    def _apply_queryd(self, data: dict) -> None:
        self.queryd_status = data.get("status", "unknown")
        self.queryd_version = data.get("version", "")
        td = data.get("terminusdb", {})
        if isinstance(td, dict):
            self.queryd_terminusdb = td.get("status", "unknown")
        else:
            self.queryd_terminusdb = str(td) if td else "unknown"
        self.queryd_plugins = data.get("plugins", []) or []

    def _apply_indexed(self, data: dict) -> None:
        self.indexed_status = data.get("status", "unknown")
        self.indexed_version = data.get("version", "")
        td = data.get("terminusdb", {})
        if isinstance(td, dict):
            self.indexed_terminusdb = td.get("status", "unknown")
        else:
            self.indexed_terminusdb = str(td) if td else "unknown"
        self.indexed_plugins = data.get("plugins", []) or []
        blob = data.get("blob_root_writable")
        self.indexed_blob_root_writable_available = blob is not None
        self.indexed_blob_root_writable = bool(blob)
