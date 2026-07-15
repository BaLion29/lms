"""Tests for firnline_core.toolspec — ToolSpec, ToolContext, and ToolSpecPlugin."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from firnline_core.plugins import ModuleRequirement, ToolSpecPlugin, validate_plugin
from firnline_core.toolspec import ToolContext, ToolSpec


# ---------------------------------------------------------------------------
# sample args model
# ---------------------------------------------------------------------------


class CreateItemArgs(BaseModel):
    """Sample model for tool arguments."""

    title: str
    description: str | None = None
    priority: int = 1


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------


class TestToolSpec:
    async def _ok_handler(self, args: CreateItemArgs, ctx: ToolContext) -> dict[str, object]:
        return {"ok": True, "fallback": True}

    async def test_input_schema_generation(self) -> None:
        spec = ToolSpec(
            name="create_item",
            description="Create a new item",
            args_model=CreateItemArgs,
            handler=self._ok_handler,
        )
        schema = spec.input_schema
        assert schema["type"] == "object"
        assert "title" in schema["properties"]
        assert schema["properties"]["title"]["type"] == "string"
        assert "description" in schema["properties"]
        assert schema["properties"]["priority"]["default"] == 1
        # optional fields should not be in "required"
        required = schema.get("required", [])
        assert "title" in required
        assert "description" not in required

    async def test_handler_returns_ok_dict(self) -> None:
        async def my_handler(args: CreateItemArgs, ctx: ToolContext) -> dict[str, object]:
            return {"ok": True, "id": "item/42", "title": args.title}

        spec = ToolSpec(
            name="create_item",
            description="Create item",
            args_model=CreateItemArgs,
            handler=my_handler,
        )
        ctx = ToolContext(tdb=None)
        args = CreateItemArgs(title="test item")
        result = await spec.handler(args, ctx)
        assert result == {"ok": True, "id": "item/42", "title": "test item"}

    async def test_handler_returns_error_dict(self) -> None:
        async def failing_handler(args: CreateItemArgs, ctx: ToolContext) -> dict[str, object]:
            return {"ok": False, "error": "title already exists"}

        spec = ToolSpec(
            name="create_item",
            description="Create item",
            args_model=CreateItemArgs,
            handler=failing_handler,
        )
        ctx = ToolContext(tdb=None)
        args = CreateItemArgs(title="duplicate")
        result = await spec.handler(args, ctx)
        assert result == {"ok": False, "error": "title already exists"}


# ---------------------------------------------------------------------------
# ToolContext
# ---------------------------------------------------------------------------


class TestToolContext:
    def test_default_branch(self) -> None:
        ctx = ToolContext(tdb="fake_tdb")
        assert ctx.tdb == "fake_tdb"
        assert ctx.branch == "main"

    def test_explicit_branch(self) -> None:
        ctx = ToolContext(tdb="fake_tdb", branch="staging")
        assert ctx.branch == "staging"

    def test_frozen(self) -> None:
        ctx = ToolContext(tdb="x", branch="b")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError or AttributeError
            ctx.branch = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ToolSpecPlugin protocol
# ---------------------------------------------------------------------------


class TestToolSpecPluginProtocol:
    def test_isinstance_check_passes(self) -> None:
        class MyPlugin:
            name = "my_plugin"
            requires: list[ModuleRequirement] = []

            def tool_specs(self) -> list[Any]:
                return []

        plugin = MyPlugin()
        assert isinstance(plugin, ToolSpecPlugin)

    def test_isinstance_check_fails_missing_tool_specs(self) -> None:
        class BadPlugin:
            name = "bad"
            requires: list[ModuleRequirement] = []

        plugin = BadPlugin()
        assert not isinstance(plugin, ToolSpecPlugin)

    def test_isinstance_check_fails_missing_name(self) -> None:
        class BadPlugin:
            requires: list[ModuleRequirement] = []

            def tool_specs(self) -> list[Any]:
                return []

        plugin = BadPlugin()
        assert not isinstance(plugin, ToolSpecPlugin)

    def test_validate_plugin_passes(self) -> None:
        class MyPlugin:
            name = "my_plugin"
            requires: list[ModuleRequirement] = []

            def tool_specs(self) -> list[Any]:
                return []

        violations = validate_plugin(MyPlugin(), ToolSpecPlugin)
        assert violations == []

    def test_validate_plugin_detects_missing_method(self) -> None:
        class BadPlugin:
            name = "bad"
            requires: list[ModuleRequirement] = []

        violations = validate_plugin(BadPlugin(), ToolSpecPlugin)
        assert any("missing method 'tool_specs'" in v for v in violations)

    def test_validate_plugin_detects_missing_attribute(self) -> None:
        class BadPlugin:
            requires: list[ModuleRequirement] = []

            def tool_specs(self) -> list[Any]:
                return []

        violations = validate_plugin(BadPlugin(), ToolSpecPlugin)
        assert any("missing attribute 'name'" in v for v in violations)


# ---------------------------------------------------------------------------
# ToolPlugin is NOT broken by ToolSpecPlugin
# ---------------------------------------------------------------------------


class TestToolPluginUnaffected:
    """Existing ToolPlugin protocol is unchanged — legacy plugins still work."""

    def test_existing_plugin_still_passes_tool_plugin_isinstance(self) -> None:
        from firnline_core.plugins import ToolPlugin

        class LegacyPlugin:
            name = "legacy_tool"
            requires: list[ModuleRequirement] = []

            def tools(self, deps: Any) -> list[Any]:
                return []

        plugin = LegacyPlugin()
        # Legacy plugins should still pass ToolPlugin isinstance check
        assert isinstance(plugin, ToolPlugin)

    def test_existing_plugin_not_tool_spec_plugin(self) -> None:
        """A plugin with only tools() is NOT a ToolSpecPlugin — no false positive."""
        class LegacyPlugin:
            name = "legacy_tool"
            requires: list[ModuleRequirement] = []

            def tools(self, deps: Any) -> list[Any]:
                return []

        plugin = LegacyPlugin()
        assert not isinstance(plugin, ToolSpecPlugin)


# ---------------------------------------------------------------------------
# tool_specs returns actual ToolSpec objects
# ---------------------------------------------------------------------------


class TestToolSpecPluginIntegration:
    async def test_tool_spec_plugin_with_real_specs(self) -> None:
        class MyPlugin:
            name = "item_tools"
            requires: list[ModuleRequirement] = []

            def tool_specs(self) -> list[Any]:
                async def create_handler(args: CreateItemArgs, ctx: ToolContext) -> dict[str, object]:
                    return {"ok": True, "id": "item/new"}

                return [
                    ToolSpec(
                        name="create_item",
                        description="Create an item",
                        args_model=CreateItemArgs,
                        handler=create_handler,
                    )
                ]

        plugin = MyPlugin()
        specs = plugin.tool_specs()
        assert len(specs) == 1
        spec = specs[0]
        assert isinstance(spec, ToolSpec)
        assert spec.name == "create_item"
        assert spec.args_model is CreateItemArgs

        # Check input_schema
        schema = spec.input_schema
        assert schema["type"] == "object"
        assert "title" in schema["properties"]

        # Check handler invocation
        ctx = ToolContext(tdb=None)
        result = await spec.handler(CreateItemArgs(title="hello"), ctx)
        assert result == {"ok": True, "id": "item/new"}
