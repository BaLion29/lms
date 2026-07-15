"""Automations page — trigger firings and action executions."""

from __future__ import annotations

import reflex as rx

from firnline_webui.pages.automations_components import executions_section, firings_section
from firnline_webui.state.automations import AutomationsState
from firnline_webui.ui.detail import json_detail_drawer
from firnline_webui.ui.feedback import empty_state as _empty_state, error_callout
from firnline_webui.ui.nav import shell
from firnline_webui.ui.typography import page_heading


def automations_page() -> rx.Component:
    """Automations page — trigger firings and action executions."""
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                page_heading("Automations"),
                rx.spacer(),
                rx.cond(AutomationsState.loading, rx.spinner(size="3")),
                rx.button(
                    rx.icon(tag="refresh_cw", size=16),
                    "Refresh",
                    on_click=AutomationsState.load,
                    size="2",
                    variant="soft",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Error callout
            rx.cond(
                AutomationsState.error != "",
                error_callout(AutomationsState.error),
            ),
            # Main content
            rx.cond(
                (~AutomationsState.loading) & (AutomationsState.error == ""),
                rx.cond(
                    (AutomationsState.triggers_available | AutomationsState.actions_available),
                    rx.vstack(
                        # Firings section
                        rx.cond(
                            AutomationsState.triggers_available,
                            rx.card(
                                firings_section(),
                                size="2",
                                width="100%",
                            ),
                        ),
                        # Executions section
                        rx.cond(
                            AutomationsState.actions_available,
                            rx.card(
                                executions_section(),
                                size="2",
                                width="100%",
                            ),
                        ),
                        spacing="5",
                        width="100%",
                    ),
                    # Neither module installed
                    _empty_state(
                        "zap",
                        "Automations modules not installed",
                        hint="The triggers/actions modules are not present in this schema.",
                    ),
                ),
            ),
            # Detail drawer (shared)
            json_detail_drawer(
                doc_var=AutomationsState.selected_doc,
                json_var=AutomationsState.selected_json,
                iri_var=AutomationsState.selected_iri,
                on_close=AutomationsState.clear_selection,
                open_var=AutomationsState.has_selection,
            ),
            spacing="5",
            width="100%",
        ),
        active="automations",
    )
