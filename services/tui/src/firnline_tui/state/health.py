"""Health state — service health overview (framework-free)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class ServiceHealthDetail:
    name: str
    status: str = "unknown"
    version: str = ""
    terminusdb: str = "unknown"
    handlers: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()
    blob_root_writable: bool = False
    blob_root_writable_available: bool = False
    store: str = "\u2014"
    poller: str = "\u2014"


@dataclass(frozen=True)
class HealthData:
    captured: ServiceHealthDetail = field(
        default_factory=lambda: ServiceHealthDetail(name="captured")
    )
    queryd: ServiceHealthDetail = field(
        default_factory=lambda: ServiceHealthDetail(name="queryd")
    )
    indexed: ServiceHealthDetail = field(
        default_factory=lambda: ServiceHealthDetail(name="indexed")
    )
    mcpd_status: str = "unknown"
    error: str = ""


async def load_health(ctx: AppContext) -> HealthData:
    """Refresh health data from all monitored services concurrently."""
    c_cap, c_qry, c_idx, c_mcpd = ctx.make_health()
    cap_r, qry_r, idx_r, mcpd_r = await asyncio.gather(
        _safe_fetch(c_cap),
        _safe_fetch(c_qry),
        _safe_fetch(c_idx),
        _safe_fetch(c_mcpd),
    )

    return HealthData(
        captured=_apply_captured(cap_r),
        queryd=_apply_queryd(qry_r),
        indexed=_apply_indexed(idx_r),
        mcpd_status=mcpd_r.get("status", "unknown"),
    )


async def _safe_fetch(client) -> dict:
    try:
        return await client.healthz()
    except Exception:
        return {"status": "unreachable"}


def _parse_terminusdb(data: dict) -> str:
    """Extract terminusdb status from flat string or nested dict."""
    td = data.get("terminusdb", "unknown")
    if isinstance(td, dict):
        return str(td.get("status", "unknown"))
    return str(td) if td else "unknown"


def _apply_captured(data: dict) -> ServiceHealthDetail:
    blob = data.get("blob_root_writable")
    return ServiceHealthDetail(
        name="captured",
        status=data.get("status", "unknown"),
        version=data.get("version", ""),
        terminusdb=_parse_terminusdb(data),
        handlers=tuple(data.get("handlers", data.get("plugins", [])) or []),
        plugins=(),
        blob_root_writable_available=blob is not None,
        blob_root_writable=bool(blob),
    )


def _apply_queryd(data: dict) -> ServiceHealthDetail:
    return ServiceHealthDetail(
        name="queryd",
        status=data.get("status", "unknown"),
        version=data.get("version", ""),
        terminusdb=_parse_terminusdb(data),
        plugins=tuple(data.get("plugins", []) or []),
    )


def _apply_indexed(data: dict) -> ServiceHealthDetail:
    return ServiceHealthDetail(
        name="indexed",
        status=data.get("status", "unknown"),
        version="\u2014",
        terminusdb=_parse_terminusdb(data),
        store=str(data.get("store", "\u2014")) or "\u2014",
        poller=str(data.get("poller", "\u2014")) or "\u2014",
    )
