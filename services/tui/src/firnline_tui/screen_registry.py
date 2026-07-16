"""TUI screen registry — builtin + external discovery via PluginHost."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from firnline_core.plugins import (
    DiscoveryResult,
    HostResult,
    TuiScreenPlugin,
    discover_plugins,
    validate_plugin,
)
from firnline_core.screenspec import ScreenSpec

log = logging.getLogger(__name__)

EXTERNAL_GROUP = "firnline.tui.screens"


@dataclass(frozen=True)
class ScreenRegistry:
    """Immutable snapshot of resolved screens, in nav order."""

    specs: tuple[ScreenSpec, ...]
    result: HostResult
    degraded: bool = False

    def by_id(self, screen_id: str) -> ScreenSpec | None:
        for s in self.specs:
            if s.screen_id == screen_id:
                return s
        return None

    def nav_specs(self) -> list[ScreenSpec]:
        """Return specs visible in navigation (nav_section is not None), sorted."""
        visible = [s for s in self.specs if s.nav_section is not None]
        return sorted(visible, key=lambda s: (s.nav_section, s.nav_order, s.screen_id))

    def nav_sections(self) -> list[tuple[str, list[ScreenSpec]]]:
        """Return [(section_name, [specs]), ...] grouped and sorted."""
        visible = self.nav_specs()
        sections: list[tuple[str, list[ScreenSpec]]] = []
        current_section: str | None = None
        for spec in visible:
            if spec.nav_section != current_section:
                current_section = spec.nav_section
                sections.append((current_section, [spec]))
            else:
                sections[-1][1].append(spec)
        return sections


async def build_screen_registry(
    tdb: Any,
    *,
    timeout: float = 3.0,
    discovered: DiscoveryResult | None = None,
) -> ScreenRegistry:
    """Discover, validate, and merge builtin + external screen plugins.

    Uses PluginHost with graceful degradation:
    - broken_entry_point_fatal=False (log + skip)
    - tdb_unavailable_fatal=False (degraded mode)
    - Plugins with requires == [] load even when TDB is down
    - Collision check on screen_id AND key across all specs
    """
    result = HostResult()
    all_specs: list[ScreenSpec] = []
    degraded = False

    # 1. Builtin (always active)
    from firnline_tui.builtin_screens import BuiltinScreens

    builtin = BuiltinScreens()
    result.active.append(("builtin", builtin))

    # 2. Discover external plugins
    ext_discovered = discover_plugins(EXTERNAL_GROUP) if discovered is None else discovered
    result.failed = ext_discovered.failed
    for name, err in ext_discovered.failed:
        log.warning("plugin_load_failed plugin=%s error=%s", name, err.split("\n")[-1])

    # 3. Fetch TDB registry (with timeout)
    registry_docs: list[dict[str, Any]] | None = None
    if ext_discovered.active:
        try:
            registry_docs = await asyncio.wait_for(
                tdb.get_documents("SchemaModule"),
                timeout=timeout,
            )
        except Exception as exc:
            log.warning("TDB registry fetch failed — degraded mode: %s", exc)
            degraded = True

    # 4. Validate & select external plugins
    for ep_name, obj in ext_discovered.active:
        # Structural validation
        violations = validate_plugin(obj, TuiScreenPlugin)
        if violations:
            result.skipped.append((ep_name, violations))
            log.warning("plugin_skipped plugin=%s violations=%s", ep_name, violations)
            continue

        # Requirement validation
        requires = getattr(obj, "requires", [])
        if registry_docs is not None:
            from firnline_core.plugins import check_requirements

            req_violations = await check_requirements(None, requires, registry=registry_docs)
            if req_violations:
                result.skipped.append((ep_name, req_violations))
                log.warning("plugin_skipped plugin=%s violations=%s", ep_name, req_violations)
                continue
        elif requires:
            # TDB unavailable and plugin has requirements — skip
            reason = "registry unavailable: TDB unreachable at startup"
            result.skipped.append((ep_name, [reason]))
            log.warning("plugin_skipped plugin=%s reason=registry_unavailable", ep_name)
            continue

        result.active.append((ep_name, obj))
        log.info("plugin_active plugin=%s", ep_name)

    # 5. Collect ScreenSpecs with collision detection
    seen_ids: dict[str, str] = {}
    seen_keys: dict[str, str] = {}
    for plugin_name, plugin in result.active:
        try:
            specs = plugin.screens() if hasattr(plugin, "screens") else []
        except Exception as exc:
            log.error("plugin_screens_failed plugin=%s error=%s", plugin_name, exc)
            continue

        for spec in specs:
            if isinstance(spec, dict):
                spec = ScreenSpec(**spec)
            if not isinstance(spec, ScreenSpec):
                log.error("plugin_bad_screen_spec plugin=%s type=%s", plugin_name, type(spec).__name__)
                continue

            # screen_id collision
            if spec.screen_id in seen_ids:
                raise RuntimeError(
                    f"Screen id collision on {spec.screen_id!r}: "
                    f"{seen_ids[spec.screen_id]!r} and {plugin_name!r}"
                )
            seen_ids[spec.screen_id] = plugin_name

            # key collision
            if spec.key is not None:
                if spec.key in seen_keys:
                    raise RuntimeError(
                        f"Hotkey collision on {spec.key!r}: "
                        f"{seen_keys[spec.key]!r} and {plugin_name!r}"
                    )
                seen_keys[spec.key] = plugin_name

            all_specs.append(spec)

    log.info(
        "screen_registry_built active_count=%d skipped_count=%d screen_count=%d degraded=%s",
        len(result.active),
        len(result.skipped),
        len(all_specs),
        degraded,
    )

    return ScreenRegistry(specs=tuple(all_specs), result=result, degraded=degraded)
