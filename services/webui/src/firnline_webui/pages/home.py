"""Home / dashboard page."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.health import HealthState
from firnline_webui.state.modules import ModulesState
from firnline_webui.ui.cards import chip, stat_badge
from firnline_webui.ui.nav import shell
from firnline_webui.ui.theme import RADIUS_MEDIUM, SHADOW_CARD, SPACE_2, SPACE_4, SPACE_6, WARM_ACCENT
from firnline_webui.ui.typography import card_title, page_heading, section_heading


def _service_row(
    name: str,
    status: rx.Var[str],
    version: rx.Var[str],
    td_status_var: rx.Var[str],
    *,
    show_extra: bool = True,
) -> rx.Component:
    """A single row inside the Service Health container."""
    status_indicator = rx.cond(
        status == "ok",
        stat_badge("up", True),
        rx.cond(
            status == "unreachable",
            stat_badge("down", False),
            stat_badge("degraded", False),
        ),
    )
    if show_extra:
        version_text = rx.hstack(
            rx.text("v", size="1", color=rx.color("gray", 10)),
            rx.text(version, size="1", color=rx.color("gray", 10)),
            rx.text(" \u00b7 TD ", size="1", color=rx.color("gray", 10)),
            rx.text(td_status_var, size="1", color=rx.color("gray", 10)),
            spacing="0",
        )
    else:
        version_text = rx.text("")

    return rx.hstack(
        rx.text(name, size="2", weight="medium"),
        rx.spacer(),
        status_indicator,
        version_text,
        align="center",
        width="100%",
        padding_y=SPACE_2,
        padding_x=SPACE_4,
        flex_wrap="wrap",
    )


def home_page() -> rx.Component:
    """Dashboard page."""
    return shell(
        rx.vstack(
            # ── Header ──────────────────────────────────────────────
            rx.box(
                width="32px",
                height="3px",
                bg=rx.color("accent", 9),
                border_radius="2px",
                margin_bottom=SPACE_2,
            ),
            page_heading("Welcome to Firnline"),
            rx.text(
                "Personal data capture, indexing, and browsing system.",
                size="2",
                color=rx.color("gray", 11),
            ),
            # ── Quick Capture (focal point) ─────────────────────────
            rx.card(
                rx.hstack(
                    rx.icon(tag="pencil_line", size=18, color=rx.color("accent", 11)),
                    rx.vstack(
                        card_title("Quick Capture"),
                        rx.text(
                            "Send a note or file to the capture pipeline.",
                            size="2",
                            color=rx.color("gray", 11),
                        ),
                        spacing="1",
                    ),
                    rx.spacer(),
                    rx.link(
                        rx.button("Open Capture", size="3", color_scheme=WARM_ACCENT, variant="solid"),
                        href="/capture",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                padding=SPACE_6,
                background=rx.color("gray", 1),
                border=f"1px solid {rx.color('gray', 5)}",
                border_radius=RADIUS_MEDIUM,
                _hover={"box_shadow": SHADOW_CARD},
                transition="box-shadow 0.2s ease",
                width="100%",
            ),
            # ── Service Health ──────────────────────────────────────
            section_heading("Service Health"),
            rx.box(
                _service_row(
                    "Captured",
                    HealthState.captured_status,
                    HealthState.captured_version,
                    HealthState.captured_terminusdb,
                ),
                rx.divider(),
                _service_row(
                    "Queryd",
                    HealthState.queryd_status,
                    HealthState.queryd_version,
                    HealthState.queryd_terminusdb,
                ),
                rx.divider(),
                _service_row(
                    "Indexd",
                    HealthState.indexed_status,
                    HealthState.indexed_version,
                    HealthState.indexed_terminusdb,
                ),
                rx.divider(),
                _service_row(
                    "MCPD",
                    HealthState.mcpd_status,
                    rx.Var.create("\u2014"),
                    rx.Var.create("\u2014"),
                    show_extra=False,
                ),
                border=f"1px solid {rx.color('gray', 4)}",
                border_radius=RADIUS_MEDIUM,
                background=rx.color("gray", 1),
                width="100%",
            ),
            # ── Schema Modules ──────────────────────────────────────
            section_heading("Schema Modules"),
            rx.flex(
                rx.foreach(
                    ModulesState.modules,
                    lambda m: chip(m["name"]),
                ),
                wrap="wrap",
                gap="1",
            ),
            rx.text(
                "Visit the Modules page to load and inspect schema modules.",
                size="1",
                color=rx.color("gray", 11),
                margin_top="4px",
            ),
            rx.link(
                rx.button("View All Modules", size="1", variant="ghost", margin_top="8px"),
                href="/modules",
            ),
            spacing="5",
            width="100%",
        ),
        active="home",
    )
