"""Schema Modules page."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.modules import ModulesState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.feedback import empty_state as _empty_state, error_callout
from firnline_webui.ui.nav import shell


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


def modules_page() -> rx.Component:
    """Schema modules and active plugins page."""
    return shell(
        rx.vstack(
            # Header row
            rx.vstack(
                rx.hstack(
                    rx.heading("Schema Modules", size="6"),
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
                            variant="outline",
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
                                        _odd={"background": rx.color("gray", 2)},
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
            rx.heading("Active Plugins by Service", size="4", margin_top="24px", margin_bottom="12px"),
            rx.grid(
                _plugin_section("Captured", ModulesState.captured_plugins),
                _plugin_section("Queryd", ModulesState.queryd_plugins),
                _plugin_section("Indexed", ModulesState.indexed_plugins),
                columns={"initial": "1", "md": "3"},
                spacing="4",
                width="100%",
            ),
            spacing="5",
            width="100%",
        ),
        active="modules",
    )
