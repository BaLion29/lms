"""Dashboard state — service health overview + recent captures."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class ServiceHealth:
    name: str
    status: str = "unknown"
    version: str = ""
    terminusdb: str = "unknown"
    error: str = ""


@dataclass(frozen=True)
class DashboardData:
    services: tuple[ServiceHealth, ...] = ()
    recent_captures: tuple[dict, ...] = ()
    error: str = ""


async def load_dashboard(ctx: AppContext) -> DashboardData:
    """Load health for all services + recent captures."""
    # Fan-out healthz
    c_cap, c_qry, c_idx, c_mcpd = ctx.make_health()
    results = await asyncio.gather(
        _safe_healthz("captured", c_cap),
        _safe_healthz("queryd", c_qry),
        _safe_healthz("indexed", c_idx),
        _safe_healthz("mcpd", c_mcpd),
        return_exceptions=True,
    )
    services: list[ServiceHealth] = []
    for r in results:
        if isinstance(r, Exception):
            services.append(ServiceHealth(name="unknown", error=str(r)))
        else:
            services.append(r)

    # Recent captures
    recent: list[dict] = []
    try:
        from firnline_core.introspect import inbox_classes, doc_preview  # noqa: PLC0415

        tdb = ctx.make_tdb()
        try:
            schema = await tdb.get_schema()
            class_ids = inbox_classes(schema)
            for cid in class_ids:
                docs = await tdb.get_documents(cid)
                for doc in docs[:10]:
                    recent.append(
                        {
                            "id": doc.get("@id", ""),
                            "status": str(doc.get("status", "")),
                            "preview": doc_preview(doc),
                        }
                    )
        finally:
            await tdb.aclose()
    except UiClientError:
        pass

    return DashboardData(
        services=tuple(services),
        recent_captures=tuple(recent[:10]),
    )


async def _safe_healthz(name: str, client) -> ServiceHealth:
    try:
        data = await client.healthz()
        return ServiceHealth(
            name=name,
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            terminusdb=_parse_tdb(data),
        )
    except Exception as exc:
        return ServiceHealth(name=name, error=str(exc))


def _parse_tdb(data: dict) -> str:
    td = data.get("terminusdb", "unknown")
    if isinstance(td, dict):
        return str(td.get("status", "unknown"))
    return str(td) if td else "unknown"
