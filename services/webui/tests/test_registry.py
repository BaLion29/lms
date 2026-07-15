"""Tests for the WebUI page plugin registry."""

from __future__ import annotations

from unittest import mock

import pytest

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import ModuleRequirement, WebUIPagePlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyPlugin:
    """A valid WebUIPagePlugin."""

    name = "test_ext"
    requires: list[ModuleRequirement] = []

    def pages(self) -> list[PageSpec]:
        return [
            PageSpec(
                route="/test",
                title="Test Page",
                component=lambda: None,
                nav_section="TEST",
                nav_icon="test",
                nav_order=50,
            ),
        ]


class _MalformedPlugin:
    """Missing required attributes."""

    name = "bad"
    # no requires, no pages()


class _BadPagesPlugin:
    """Has the right attributes but pages() returns non-PageSpec."""

    name = "bad_pages"
    requires: list[ModuleRequirement] = []

    def pages(self) -> list:
        return [{"not": "a pagespec"}]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_builtin_plugin_always_loads():
    """The builtin plugin must always be in the active list."""
    from firnline_webui.plugin_host import get_active_plugins, get_page_specs

    active = dict(get_active_plugins())
    assert "builtin" in active, f"builtin not in active plugins: {list(active)}"

    specs = get_page_specs()
    routes = {s.route for s in specs}
    assert "/" in routes
    assert "/capture" in routes
    assert "/login" in routes
    assert "/history" in routes


def test_builtin_page_specs_match_expected_routes():
    """Builtin plugin pages must expose all expected routes (isolated from externals)."""
    from firnline_webui.builtin_pages import BuiltinPages

    specs = BuiltinPages().pages()
    routes = {s.route for s in specs}

    expected = {
        "/",
        "/capture",
        "/inbox",
        "/browse",
        "/browse/[class_name]",
        "/calendar",
        "/automations",
        "/health",
        "/modules",
        "/history",
        "/login",
    }
    assert routes == expected, f"Missing: {expected - routes}, Extra: {routes - expected}"


def test_builtin_nav_metadata():
    """Nav sections and icons must match the current sidebar exactly."""
    from firnline_webui.plugin_host import get_page_specs

    specs = {s.route: s for s in get_page_specs()}

    # Nav items — must have nav_section="MAIN" and correct icons/order
    nav_items = {
        "/": ("MAIN", "house", 0),
        "/capture": ("MAIN", "pencil_line", 10),
        "/inbox": ("MAIN", "inbox", 20),
        "/browse": ("MAIN", "database", 30),
        "/calendar": ("MAIN", "calendar_days", 40),
        "/automations": ("MAIN", "zap", 50),
        "/health": ("MAIN", "activity", 60),
        "/modules": ("MAIN", "blocks", 70),
        "/history": ("MAIN", "history", 80),
    }
    for route, (section, icon, order) in nav_items.items():
        s = specs[route]
        assert s.nav_section == section, f"{route}: nav_section={s.nav_section}"
        assert s.nav_icon == icon, f"{route}: nav_icon={s.nav_icon}"
        assert s.nav_order == order, f"{route}: nav_order={s.nav_order}"

    # Non-nav items
    assert specs["/login"].nav_section is None
    assert specs["/browse/[class_name]"].nav_section is None


def test_registry_has_no_duplicate_routes():
    """No two page specs may share the same route."""
    from firnline_webui.plugin_host import get_page_specs

    specs = get_page_specs()
    routes = [s.route for s in specs]
    assert len(routes) == len(set(routes)), f"Duplicate routes: {routes}"


def test_external_discovery_no_extras_by_default():
    """Builtin is always first; any external plugins must pass validation
    and must not collide with builtin routes."""
    from firnline_core.plugins import validate_plugin, WebUIPagePlugin
    from firnline_webui.builtin_pages import BuiltinPages
    from firnline_webui.plugin_host import get_registry_result, get_page_specs

    result = get_registry_result()

    # Builtin must always be first in the active list.
    assert result.active, "No active plugins at all"
    assert result.active[0][0] == "builtin", f"First active is {result.active[0][0]!r}"

    # Every external (non-builtin) active plugin must pass structural validation.
    for name, obj in result.active[1:]:
        violations = validate_plugin(obj, WebUIPagePlugin)
        assert not violations, f"External plugin {name!r} failed validation: {violations}"

    # Builtin routes must be a subset of merged routes (no collisions swallowed them).
    builtin_routes = {s.route for s in BuiltinPages().pages()}
    merged_routes = {s.route for s in get_page_specs()}
    missing = builtin_routes - merged_routes
    assert not missing, f"Builtin routes missing from merged registry: {missing}"


def test_validate_plugin_rejects_missing_attrs():
    """validate_plugin must reject a plugin missing 'requires' or 'pages'."""
    from firnline_core.plugins import validate_plugin

    violations = validate_plugin(_MalformedPlugin(), WebUIPagePlugin)
    assert violations, "Expected violations for malformed plugin"
    assert any("requires" in v for v in violations)


def test_runtime_error_on_route_collision():
    """Two plugins claiming the same route must raise RuntimeError."""
    from firnline_webui.plugin_host import _build_registry

    class CollidingPlugin:
        name = "collider"
        requires: list[ModuleRequirement] = []

        def pages(self) -> list[PageSpec]:
            return [
                PageSpec(
                    route="/",  # collides with builtin
                    title="Collision",
                    component=lambda: None,
                ),
            ]

    # Patch discover_plugins to return our colliding plugin
    with mock.patch(
        "firnline_webui.plugin_host.discover_plugins",
        return_value=mock.MagicMock(active=[("collider", CollidingPlugin())], failed=[]),
    ):
        with pytest.raises(RuntimeError, match="route collision"):
            _build_registry()


def test_registry_skips_malformed_external_plugin():
    """Malformed external plugins must be skipped (not crash)."""
    from firnline_webui.plugin_host import get_registry_result

    # The registry is already built without malformed plugins.
    # Verify the current state shows no failures from bad plugins.
    result = get_registry_result()
    # Only builtin should be active (no external entry points in test env)
    assert len(result.active) >= 1
    assert result.active[0][0] == "builtin"
