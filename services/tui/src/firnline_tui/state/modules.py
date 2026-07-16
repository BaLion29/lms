"""Modules state — schema module listing and per-service plugin info."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from firnline_core.uiclients import UiClientError

from firnline_tui.state.context import AppContext


@dataclass(frozen=True)
class ModuleInfo:
    name: str = ""
    version: str = ""
    description: str = ""
    exports: tuple[str, ...] = ()
    exports_str: str = ""
    depends_on: tuple[str, ...] = ()
    depends_on_str: str = ""


@dataclass(frozen=True)
class ModulesData:
    modules: tuple[ModuleInfo, ...] = ()
    captured_plugins: tuple[str, ...] = ()
    queryd_plugins: tuple[str, ...] = ()
    indexed_plugins: tuple[str, ...] = ()
    error: str = ""


async def load_modules(ctx: AppContext) -> ModulesData:
    """Load modules from TerminusDB and plugins from health endpoints."""
    try:
        modules = await _fetch_modules(ctx)
    except UiClientError as exc:
        return ModulesData(error=f"Failed to load modules: {exc.detail}")

    try:
        plugins = await _fetch_plugins(ctx)
    except Exception:
        plugins = {
            "captured": ("unreachable",),
            "queryd": ("unreachable",),
            "indexed": ("unreachable",),
        }

    return ModulesData(
        modules=tuple(modules),
        captured_plugins=plugins.get("captured", ()),
        queryd_plugins=plugins.get("queryd", ()),
        indexed_plugins=plugins.get("indexed", ()),
    )


async def _fetch_modules(ctx: AppContext) -> list[ModuleInfo]:
    tdb = ctx.make_tdb()
    try:
        raw = await tdb.get_modules()
    finally:
        await tdb.aclose()

    result: list[ModuleInfo] = []
    for mod in raw:
        exports = mod.get("exports", []) or []
        depends_on = mod.get("depends_on", []) or []
        if not isinstance(exports, list):
            exports = [exports]
        if not isinstance(depends_on, list):
            depends_on = [depends_on]
        result.append(
            ModuleInfo(
                name=str(mod.get("@id", mod.get("name", "?"))),
                version=str(mod.get("version", "")),
                description=str(mod.get("description", "")),
                exports=tuple(str(e) for e in exports),
                exports_str=", ".join(str(e) for e in exports) if exports else "-",
                depends_on=tuple(str(d) for d in depends_on),
                depends_on_str=", ".join(str(d) for d in depends_on) if depends_on else "-",
            )
        )
    result.sort(key=lambda m: m.name)
    return result


async def _fetch_plugins(ctx: AppContext) -> dict[str, tuple[str, ...]]:
    c_cap, c_qry, c_idx, _ = ctx.make_health()
    cap_r, qry_r, idx_r = await asyncio.gather(
        _safe_healthz(c_cap),
        _safe_healthz(c_qry),
        _safe_healthz(c_idx),
    )
    return {
        "captured": cap_r,
        "queryd": qry_r,
        "indexed": idx_r,
    }


async def _safe_healthz(client) -> tuple[str, ...]:
    try:
        data = await client.healthz()
    except Exception:
        return ("unreachable",)
    plugins = data.get("plugins", data.get("handlers", [])) or []
    return tuple(plugins)
