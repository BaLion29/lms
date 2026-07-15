"""Tests for firnline_core.pagespec — PageSpec and WebUIPagePlugin."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from firnline_core.pagespec import PageSpec
from firnline_core.plugins import ModuleRequirement, WebUIPagePlugin, validate_plugin


# ---------------------------------------------------------------------------
# PageSpec validation
# ---------------------------------------------------------------------------


class TestPageSpecValidation:
    def test_valid_pagespec(self) -> None:
        def my_component() -> Any:
            return "fake_component"

        spec = PageSpec(
            route="/calendar",
            title="Calendar",
            component=my_component,
        )
        assert spec.route == "/calendar"
        assert spec.title == "Calendar"
        assert spec.component is my_component
        assert spec.nav_section is None
        assert spec.nav_icon is None
        assert spec.nav_order == 100
        assert spec.on_load is None

    def test_route_must_start_with_slash(self) -> None:
        def my_component() -> Any:
            return None

        with pytest.raises(ValueError, match="route must start with"):
            PageSpec(route="calendar", title="Calendar", component=my_component)

    def test_title_must_be_non_empty(self) -> None:
        def my_component() -> Any:
            return None

        with pytest.raises(ValueError, match="title must be non-empty"):
            PageSpec(route="/cal", title="", component=my_component)

    def test_all_fields_custom(self) -> None:
        def my_component() -> Any:
            return None

        spec = PageSpec(
            route="/browse/[class_name]",
            title="Browser",
            component=my_component,
            nav_section="Tools",
            nav_icon="folder",
            nav_order=50,
            on_load="some_event_handler",
        )
        assert spec.nav_section == "Tools"
        assert spec.nav_icon == "folder"
        assert spec.nav_order == 50
        assert spec.on_load == "some_event_handler"

    def test_frozen(self) -> None:
        def my_component() -> Any:
            return None

        spec = PageSpec(route="/x", title="X", component=my_component)
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.route = "/y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WebUIPagePlugin protocol
# ---------------------------------------------------------------------------


class TestWebUIPagePluginProtocol:
    def test_isinstance_check_passes(self) -> None:
        class MyPlugin:
            name = "my_page_plugin"
            requires: list[ModuleRequirement] = []

            def pages(self) -> list[Any]:
                return []

        plugin = MyPlugin()
        assert isinstance(plugin, WebUIPagePlugin)

    def test_isinstance_check_fails_missing_pages(self) -> None:
        class BadPlugin:
            name = "bad"
            requires: list[ModuleRequirement] = []

        plugin = BadPlugin()
        assert not isinstance(plugin, WebUIPagePlugin)

    def test_isinstance_check_fails_missing_name(self) -> None:
        class BadPlugin:
            requires: list[ModuleRequirement] = []

            def pages(self) -> list[Any]:
                return []

        plugin = BadPlugin()
        assert not isinstance(plugin, WebUIPagePlugin)

    def test_validate_plugin_passes(self) -> None:
        class MyPlugin:
            name = "my_page_plugin"
            requires: list[ModuleRequirement] = []

            def pages(self) -> list[Any]:
                return []

        violations = validate_plugin(MyPlugin(), WebUIPagePlugin)
        assert violations == []

    def test_validate_plugin_detects_missing_method(self) -> None:
        class BadPlugin:
            name = "bad"
            requires: list[ModuleRequirement] = []

        violations = validate_plugin(BadPlugin(), WebUIPagePlugin)
        assert any("missing method 'pages'" in v for v in violations)

    def test_validate_plugin_detects_missing_attribute(self) -> None:
        class BadPlugin:
            requires: list[ModuleRequirement] = []

            def pages(self) -> list[Any]:
                return []

        violations = validate_plugin(BadPlugin(), WebUIPagePlugin)
        assert any("missing attribute 'name'" in v for v in violations)

    def test_pages_returns_pagespecs(self) -> None:
        def my_component() -> Any:
            return None

        class MyPlugin:
            name = "calendar_plugin"
            requires: list[ModuleRequirement] = []

            def pages(self) -> list[Any]:
                return [
                    PageSpec(
                        route="/calendar",
                        title="Calendar",
                        component=my_component,
                        nav_section="Productivity",
                        nav_icon="calendar",
                    )
                ]

        plugin = MyPlugin()
        specs = plugin.pages()
        assert len(specs) == 1
        spec = specs[0]
        assert isinstance(spec, PageSpec)
        assert spec.route == "/calendar"
        assert spec.title == "Calendar"
        assert spec.nav_section == "Productivity"
        assert spec.nav_icon == "calendar"


# ---------------------------------------------------------------------------
# Top-level export
# ---------------------------------------------------------------------------


class TestTopLevelExports:
    def test_pagespec_importable_from_firnline_core(self) -> None:
        import firnline_core
        assert hasattr(firnline_core, "PageSpec")

    def test_webui_page_plugin_importable_from_firnline_core(self) -> None:
        import firnline_core
        assert hasattr(firnline_core, "WebUIPagePlugin")
