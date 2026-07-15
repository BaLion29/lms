"""Schema Modules page."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.modules import ModulesState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.feedback import empty_state as _empty_state, error_callout
from firnline_webui.ui.nav import shell
from firnline_webui.ui.theme import TABLE_ROW_STYLE
from firnline_webui.ui.typography import page_heading, section_heading


def _plugin_section(name: str, plugins_var: rx.Var) -> rx.Component:
    """Card showing a list of plugin names for a service."""
    return rx.card(
        rx.hstack(
            rx.center(
                rx.icon(tag="puzzle", size=14, color=rx.color("accent", 11)),
                background=rx.color("accent", 3),
                border_radius="6px",
                width="26px",
                height="26px",
            ),
            rx.text(name, size="3", weight="medium"),
            spacing="2",
            align="center",
            margin_bottom="8px",
        ),
        rx.cond(
            plugins_var.length() > 0,
            rx.hstack(
                rx.foreach(plugins_var, lambda p: chip(p, "blue")),
                spacing="1",
                wrap="wrap",
            ),
            rx.text("No plugins reported", size="2", color_scheme="gray"),
        ),
        size="2",
    )


def _webui_plugin_card(plugin: rx.Var) -> rx.Component:
    """Card for a single WebUI page plugin entry."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.center(
                    rx.icon(tag="layout_dashboard", size=14, color=rx.color("accent", 11)),
                    background=rx.color("accent", 3),
                    border_radius="6px",
                    width="26px",
                    height="26px",
                ),
                rx.text(plugin["name"], size="3", weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.hstack(
                rx.text("Pages:", size="1", weight="medium", color_scheme="gray"),
                rx.text(plugin["page_count"], size="2"),
                spacing="1",
            ),
            rx.text(plugin["routes"], size="1", color_scheme="gray"),
            spacing="1",
        ),
        size="2",
    )


def modules_page() -> rx.Component:
    """Schema modules and active plugins page."""
    return shell(
        rx.vstack(
            # Header row
            rx.vstack(
                rx.hstack(
                    page_heading("Schema Modules"),
                    rx.spacer(),
                    rx.hstack(
                        rx.cond(
                            ModulesState.loading,
                            rx.spinner(size="3"),
                            rx.text(""),
                        ),
                        rx.button(
                            rx.icon(tag="refresh_cw", size=16),
                            "Load",
                            on_click=ModulesState.load,
                            size="2",
                            variant="soft",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    align="center",
                    width="100%",
                ),
                spacing="2",
                margin_bottom="16px",
            ),
            # Error message
            rx.cond(
                ModulesState.error != "",
                error_callout(ModulesState.error),
                rx.text(""),
            ),
            # Modules table
            rx.cond(
                (~ModulesState.loading) & (ModulesState.error == ""),
                rx.cond(
                    ModulesState.modules.length() > 0,
                    rx.card(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Name"),
                                    rx.table.column_header_cell("Version"),
                                    rx.table.column_header_cell("Description"),
                                    rx.table.column_header_cell("Exports"),
                                    rx.table.column_header_cell("Depends On"),
                                ),
                            ),
                            rx.table.body(
                                rx.foreach(
                                    ModulesState.modules,
                                    lambda mod: rx.table.row(
                                        rx.table.cell(rx.text(mod["name"], size="2", weight="medium")),
                                        rx.table.cell(rx.text(mod["version"], size="2")),
                                        rx.table.cell(rx.text(mod["description"], size="2")),
                                        rx.table.cell(rx.text(mod["exports_str"], size="2")),
                                        rx.table.cell(rx.text(mod["depends_on_str"], size="2")),
                                        **TABLE_ROW_STYLE,
                                    ),
                                ),
                            ),
                            variant="surface",
                            size="2",
                            width="100%",
                        ),
                        size="2",
                        width="100%",
                    ),
                    _empty_state("blocks", "No modules found."),
                ),
                rx.text(""),
            ),
            # Active plugins by service
            section_heading("Active Plugins by Service"),
            rx.grid(
                _plugin_section("Captured", ModulesState.captured_plugins),
                _plugin_section("Queryd", ModulesState.queryd_plugins),
                _plugin_section("Indexed", ModulesState.indexed_plugins),
                columns={"initial": "1", "md": "3"},
                spacing="4",
                width="100%",
            ),
            # WebUI page plugins (in-process)
            section_heading("WebUI Page Plugins"),
            rx.cond(
                ModulesState.webui_page_plugins.length() > 0,
                rx.grid(
                    rx.foreach(
                        ModulesState.webui_page_plugins,
                        lambda p: _webui_plugin_card(p),
                    ),
                    columns={"initial": "1", "md": "3"},
                    spacing="4",
                    width="100%",
                ),
                rx.text("No WebUI page plugins loaded", size="2", color_scheme="gray"),
            ),
            spacing="5",
            width="100%",
        ),
        active="modules",
    )
