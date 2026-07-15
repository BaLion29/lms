"""Tests for the time-management WebUI page plugin."""

from __future__ import annotations

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import WebUIPagePlugin, validate_plugin


# ---------------------------------------------------------------------------
# Plugin conformance
# ---------------------------------------------------------------------------


def test_plugin_protocol_conformance():
    """The plugin conforms to the WebUIPagePlugin protocol."""
    from firnline_ext_time_management.webui import plugin

    violations = validate_plugin(plugin, WebUIPagePlugin)
    assert violations == [], f"Protocol violations: {violations}"


def test_plugin_metadata():
    """Plugin name and requirements are correct."""
    from firnline_ext_time_management.webui import plugin

    assert plugin.name == "time_management_webui"
    assert len(plugin.requires) == 1
    assert plugin.requires[0].name == "time_management"
    assert plugin.requires[0].range == ">=0.1.0 <0.2.0"


def test_plugin_singleton():
    """Plugin is a module-level singleton instance (not the class)."""
    from firnline_ext_time_management import webui

    from firnline_ext_time_management.webui import TimeManagementWebUIPlugin, plugin

    assert isinstance(plugin, TimeManagementWebUIPlugin)
    # Verify entry-point path resolves to the same object
    assert webui.plugin is plugin


# ---------------------------------------------------------------------------
# PageSpec fields
# ---------------------------------------------------------------------------


def test_page_spec_count():
    """Plugin returns exactly one PageSpec."""
    from firnline_ext_time_management.webui import plugin

    specs = plugin.pages()
    assert len(specs) == 1, f"Expected 1 PageSpec, got {len(specs)}"


def test_page_spec_fields():
    """PageSpec has correct route, title, nav_metadata, and on_load."""
    from firnline_ext_time_management.webui import plugin

    spec = plugin.pages()[0]

    assert isinstance(spec, PageSpec)
    assert spec.route == "/time"
    assert spec.title == "Time Management"
    assert spec.nav_section == "MAIN"
    assert spec.nav_icon == "clock"
    assert spec.nav_order == 45  # after Calendar (40), before Automations (50)
    assert spec.on_load is not None
    assert len(spec.on_load) == 2, f"Expected 2 on_load handlers, got {len(spec.on_load)}"


def test_on_load_handlers():
    """on_load contains AuthState.check + TimeManagementState.load."""
    from firnline_ext_time_management.webui import plugin

    spec = plugin.pages()[0]
    assert spec.on_load[0].fn.__name__ == "check"
    assert spec.on_load[1].fn.__name__ == "load"


def test_component_factory_returns_component():
    """The component factory returns a Reflex component."""
    from firnline_ext_time_management.webui import plugin

    spec = plugin.pages()[0]
    comp = spec.component()
    assert comp is not None


# ---------------------------------------------------------------------------
# Page registration in the app
# ---------------------------------------------------------------------------


def test_page_registered_in_app():
    """The /time route is registered in the Reflex app via the plugin registry."""
    from firnline_webui.firnline_webui import app

    page_routes = set(app._unevaluated_pages.keys())
    assert "time" in page_routes, f"Route /time not registered; routes: {sorted(page_routes)}"


def test_page_title_in_app():
    """The registered /time page has the correct title."""
    from firnline_webui.firnline_webui import app

    page = app._unevaluated_pages["time"]
    assert page.title == "Time Management", f"Title: {page.title}"
