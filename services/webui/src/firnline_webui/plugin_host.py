"""WebUI page plugin registry — discovery, validation, and selection.

The registry is built once at module-import time (synchronous, compressed
into the Reflex compile phase) and exposed via module-level accessors so
both ``firnline_webui.py`` (app page registration) and ``pages/modules.py``
can consume it without re-executing the discovery/validation logic.

Design notes
------------
* The **builtin** plugin (``builtin_pages.BuiltinPages``) always loads.
  It has no ``ModuleRequirement`` and therefore never needs TDB access.
* **External** plugins are discovered from the ``firnline.webui.pages``
  entry-point group.
* If TerminusDB is reachable the registry fetches ``SchemaModule`` docs
  once and validates external plugin requirements against them.
* If TDB is unreachable (or the fetch times out), requirement validation is
  **skipped** and all structurally-valid external plugins are loaded
  optimistically.  The WebUI must never fail to boot because TDB is down
  at compile time.
* **Route collisions** between any two plugins raise ``RuntimeError`` at
  import time, following the ``PluginHost.collision_key`` convention.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import (
    HostResult,
    ModuleRequirement,
    WebUIPagePlugin,
    check_requirements,
    discover_plugins,
    validate_plugin,
)

from firnline_webui.builtin_pages import BuiltinPages

log = logging.getLogger(__name__)

_EXTERNAL_GROUP = "firnline.webui.pages"
_TDB_TIMEOUT = 5.0  # seconds — must not stall Reflex compile


# ---------------------------------------------------------------------------
# Module-level registry (lazy-built on first access)
# ---------------------------------------------------------------------------

_registry: _PageRegistry | None = None


class _PageRegistry:
    """Immutable snapshot of the plugin resolution result."""

    __slots__ = ("_result", "_page_specs")

    def __init__(
        self,
        result: HostResult,
        page_specs: list[PageSpec],
    ) -> None:
        self._result = result
        self._page_specs = tuple(page_specs)  # frozen view

    @property
    def result(self) -> HostResult:
        return self._result

    @property
    def page_specs(self) -> list[PageSpec]:
        return list(self._page_specs)

    @property
    def active_plugins(self) -> list[tuple[str, object]]:
        return list(self._result.active)


def _fetch_tdb_registry(timeout: float) -> list[dict[str, Any]] | None:
    """Fetch SchemaModule docs from TDB, safe for any event-loop context.

    Returns ``None`` when TDB is unreachable or the caller is already
    inside a running event loop (e.g. Reflex dev-mode reloads).
    """
    async def _fetch() -> list[dict[str, Any]]:
        from firnline_webui.clients import make_tdb_browser  # noqa: PLC0415

        tdb = make_tdb_browser()
        try:
            return await asyncio.wait_for(
                tdb.get_documents("SchemaModule"),
                timeout=timeout,
            )
        finally:
            await tdb.aclose()

    # SAFETY: asyncio.run() crashes if called from within a running loop.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # No loop → safe to call asyncio.run()
    else:
        log.warning(
            "Running event loop detected — skipping TDB registry fetch; "
            "external plugins will load optimistically"
        )
        return None

    try:
        return asyncio.run(_fetch())
    except Exception as exc:
        log.warning(
            "TDB registry fetch failed — loading external plugins optimistically: %s",
            exc,
        )
        return None


def _check_plugin_requirements(
    obj: object, ep_name: str, registry_docs: list[dict[str, Any]]
) -> list[str]:
    """Validate a plugin's module requirements against pre-fetched registry docs.

    Safe to call even from within a running event loop — falls back to
    optimistic loading in that case.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        log.warning(
            "Running event loop detected — skipping requirement check for '%s'; "
            "loading optimistically",
            ep_name,
        )
        return []

    try:
        reqs: list[ModuleRequirement] = getattr(obj, "requires", [])
        return asyncio.run(
            check_requirements(
                None,  # tdb not needed — registry pre-fetched
                reqs,
                registry=registry_docs,
            )
        )
    except Exception as exc:
        log.warning(
            "Requirement check failed for plugin '%s': %s — loading optimistically",
            ep_name,
            exc,
        )
        return []


def _build_registry() -> _PageRegistry:
    """Discover, validate, and merge all page plugins (builtin + external).

    Must be safe to call at Reflex compile time — never raises on TDB
    unavailability, only on structural errors (route collisions, broken
    builtin).
    """
    result = HostResult()
    all_specs: list[PageSpec] = []

    # ── 1. Builtin (always active) ───────────────────────────────────
    builtin = BuiltinPages()
    result.active.append(("builtin", builtin))

    # ── 2. Discover external plugins ─────────────────────────────────
    discovered = discover_plugins(_EXTERNAL_GROUP)
    result.failed = discovered.failed
    for name, err in discovered.failed:
        log.warning("plugin_load_failed plugin=%s error=%s", name, err.split("\n")[-1])

    # ── 3. Attempt TDB registry fetch ────────────────────────────────
    registry_docs: list[dict[str, Any]] | None = None
    tdb_unavailable = False

    # Only bother if there are external plugins to validate.
    if discovered.active:
        try:
            from firnline_webui.clients import make_tdb_browser  # noqa: PLC0415
        except ImportError:
            log.warning("TDB client unavailable — loading external plugins optimistically")
            tdb_unavailable = True
        else:
            registry_docs = _fetch_tdb_registry(_TDB_TIMEOUT)
            if registry_docs is None:
                tdb_unavailable = True

    if registry_docs is not None:
        log.debug("plugin_registry_fetched count=%d", len(registry_docs))

    # ── 4. Validate & select external plugins ────────────────────────
    for ep_name, obj in discovered.active:
        # Structural validation (always performed)
        violations = validate_plugin(obj, WebUIPagePlugin)
        if violations:
            result.skipped.append((ep_name, violations))
            log.warning("plugin_skipped plugin=%s violations=%s", ep_name, violations)
            continue

        # Requirement validation (skipped when TDB is unreachable)
        if not tdb_unavailable and registry_docs is not None:
            req_violations = _check_plugin_requirements(obj, ep_name, registry_docs)
            if req_violations:
                result.skipped.append((ep_name, req_violations))
                log.warning("plugin_skipped plugin=%s violations=%s", ep_name, req_violations)
                continue

        result.active.append((ep_name, obj))
        log.info("plugin_active plugin=%s", ep_name)

    # ── 5. Collect PageSpecs with route-collision detection ──────────
    seen_routes: dict[str, str] = {}
    for plugin_name, _plugin in result.active:
        try:
            specs = _plugin.pages()
        except Exception as exc:
            log.error("plugin_pages_failed plugin=%s error=%s", plugin_name, exc)
            continue

        for spec in specs:
            # PageSpec validation — allow dicts for flexibility
            if isinstance(spec, dict):
                spec = PageSpec(**spec)
            if not isinstance(spec, PageSpec):
                log.error(
                    "plugin_bad_page_spec plugin=%s type=%s",
                    plugin_name,
                    type(spec).__name__,
                )
                continue

            route = spec.route
            if route in seen_routes:
                raise RuntimeError(
                    f"Plugin route collision on route {route!r}: "
                    f"{seen_routes[route]!r} and {plugin_name!r}"
                )
            seen_routes[route] = plugin_name
            all_specs.append(spec)

    if not result.active:
        log.warning("plugin_zero_active — no page plugins loaded")

    log.info(
        "page_registry_built active_count=%d skipped_count=%d page_count=%d",
        len(result.active),
        len(result.skipped),
        len(all_specs),
    )

    return _PageRegistry(result, all_specs)


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def _ensure_registry() -> _PageRegistry:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_page_specs() -> list[PageSpec]:
    """Return the merged, collision-free list of :class:`PageSpec` objects."""
    return _ensure_registry().page_specs


def get_active_plugins() -> list[tuple[str, object]]:
    """Return ``[(name, plugin_instance), ...]`` for all active plugins."""
    return _ensure_registry().active_plugins


def get_registry_result() -> HostResult:
    """Return the full :class:`HostResult` (active, skipped, failed)."""
    return _ensure_registry().result
