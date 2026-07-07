"""Home / dashboard page."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.health import HealthState
from firnline_webui.state.modules import ModulesState
from firnline_webui.ui.cards import chip, info_row, stat_badge, status_card
from firnline_webui.ui.nav import shell


def _service_health(name: str, status: rx.Var[str], version: rx.Var[str], td_status_var: rx.Var[str]) -> rx.Component:
    """A status card for a single service."""
    return status_card(
        name,
        rx.cond(
            status == "ok",
            stat_badge("up", True),
            rx.cond(
                status == "unreachable",
                stat_badge("down", False),
                stat_badge("degraded", False),
            ),
        ),
        info_row("Status", rx.text(status, size="2")),
        info_row("Version", rx.text(version, size="2")),
        info_row("TerminusDB", rx.text(td_status_var, size="2")),
        size="2",
    )


def home_page() -> rx.Component:
    """Dashboard page."""
    return shell(
        rx.vstack(
            # Greeting
            rx.vstack(
                rx.heading("Welcome to Firnline", size="6"),
                rx.text("Personal data capture, indexing, and browsing system.", size="2", color_scheme="gray"),
                spacing="2",
                margin_bottom="6",
            ),
            # Service health grid + quick capture
            rx.grid(
                _service_health(
                    "Captured",
                    HealthState.captured_status,
                    HealthState.captured_version,
                    HealthState.captured_terminusdb,
                ),
                _service_health(
                    "Queryd",
                    HealthState.queryd_status,
                    HealthState.queryd_version,
                    HealthState.queryd_terminusdb,
                ),
                _service_health(
                    "Indexed",
                    HealthState.indexed_status,
                    HealthState.indexed_version,
                    HealthState.indexed_terminusdb,
                ),
                # Quick capture card
                rx.card(
                    rx.hstack(
                        rx.icon(tag="pencil_line", size=18, color=rx.color("accent", 9)),
                        rx.heading("Quick Capture", size="4"),
                        align="center",
                    ),
                    rx.text(
                        "Send a note or file to the capture pipeline.", size="2", color_scheme="gray", margin_top="2"
                    ),
                    rx.link(
                        rx.button("Open Capture", size="2", margin_top="2"),
                        href="/capture",
                    ),
                    size="2",
                ),
                columns="2",
                spacing="4",
                width="100%",
            ),
            # Schema modules summary
            rx.card(
                rx.heading("Schema Modules", size="4", margin_bottom="3"),
                rx.foreach(
                    ModulesState.modules,
                    lambda m: chip(m["name"], "violet"),
                ),
                rx.text(
                    "Visit the Modules page to load and inspect schema modules.",
                    size="1",
                    color_scheme="gray",
                    margin_top="1",
                ),
                rx.link(
                    rx.button("View All Modules", size="1", variant="ghost", margin_top="2"),
                    href="/modules",
                ),
                size="2",
                margin_top="4",
            ),
            spacing="4",
            width="100%",
        ),
        active="home",
    )
