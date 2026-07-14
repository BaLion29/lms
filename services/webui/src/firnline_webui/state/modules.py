"""Schema modules state."""

from __future__ import annotations

import asyncio

import reflex as rx

from firnline_webui.clients import (
    WebuiClientError,
    make_health_clients,
    make_tdb_browser,
)
from firnline_webui.state.base import BaseState


class ModulesState(BaseState):
    """Schema module listing and per-service plugin info."""

    modules: list[dict] = []  # type: ignore[assignment]
    captured_plugins: list[str] = []
    queryd_plugins: list[str] = []
    indexed_plugins: list[str] = []
    loading: bool = False
    error: str = ""

    @rx.event
    async def load(self):
        """Load modules from TerminusDB and plugins from health endpoints."""
        self.loading = True
        self.error = ""
        yield

        try:
            self.modules = await self._fetch_modules()
        except WebuiClientError as exc:
            self.error = f"Failed to load modules: {exc.detail}"
            self.modules = []

        try:
            plugins = await self._fetch_plugins()
            self.captured_plugins = plugins.get("captured", [])
            self.queryd_plugins = plugins.get("queryd", [])
            self.indexed_plugins = plugins.get("indexed", [])
        except Exception:
            # Non-fatal; plugins are informational only
            self.captured_plugins = ["unreachable"]
            self.queryd_plugins = ["unreachable"]
            self.indexed_plugins = ["unreachable"]

        self.loading = False
        yield

    async def _fetch_modules(self) -> list[dict]:
        tdb = make_tdb_browser()
        try:
            raw = await tdb.get_modules()
        finally:
            await tdb.aclose()

        result: list[dict] = []
        for mod in raw:
            exports = mod.get("exports", []) or []
            depends_on = mod.get("depends_on", []) or []
            if not isinstance(exports, list):
                exports = [exports]
            if not isinstance(depends_on, list):
                depends_on = [depends_on]
            result.append(
                {
                    "name": mod.get("@id", mod.get("name", "?")),
                    "version": str(mod.get("version", "")),
                    "description": str(mod.get("description", "")),
                    "exports": exports,
                    "exports_str": ", ".join(str(e) for e in exports) if exports else "-",
                    "depends_on": depends_on,
                    "depends_on_str": ", ".join(str(d) for d in depends_on) if depends_on else "-",
                }
            )
        result.sort(key=lambda m: m["name"])
        return result

    async def _fetch_plugins(self) -> dict[str, list[str]]:
        c_cap, c_qry, c_idx = make_health_clients()
        cap_r, qry_r, idx_r = await asyncio.gather(
            self._safe_healthz(c_cap),
            self._safe_healthz(c_qry),
            self._safe_healthz(c_idx),
        )
        return {
            "captured": cap_r,
            "queryd": qry_r,
            "indexed": idx_r,
        }

    async def _safe_healthz(self, client) -> list[str]:
        try:
            data = await client.healthz()
        except Exception:
            return ["unreachable"]
        return data.get("plugins", data.get("handlers", [])) or []
