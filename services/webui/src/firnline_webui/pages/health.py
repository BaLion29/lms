"""Health detail page."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.health import HealthState
from firnline_webui.ui.cards import chip, info_row, stat_badge, status_card
from firnline_webui.ui.nav import shell
from firnline_webui.ui.typography import page_heading


def _blob_indicator(available: rx.Var[bool], writable: rx.Var[bool]) -> rx.Component:
    return rx.cond(
        available,
        rx.cond(
            writable,
            chip("writable", "green"),
            chip("read-only", "orange"),
        ),
        chip("n/a", "gray"),
    )


def _service_detail(
    name: str,
    status: rx.Var[str],
    version: rx.Var[str],
    td_status: rx.Var[str],
    handlers: rx.Var[list],
    blob_available: rx.Var[bool] | None = None,
    blob_writable: rx.Var[bool] | None = None,
    store: rx.Var[str] | None = None,
    poller: rx.Var[str] | None = None,
) -> rx.Component:
    return status_card(
        name,
        rx.cond(
            status == "ok",
            stat_badge("healthy", True),
            rx.cond(
                status == "unreachable",
                stat_badge("unreachable", False),
                stat_badge(status, False),
            ),
        ),
        info_row("Status", rx.text(status, size="2")),
        info_row("Version", rx.text(version, size="2")),
        info_row("TerminusDB", rx.text(td_status, size="2")),
        rx.cond(
            handlers.length() > 0,
            rx.vstack(
                rx.text("Handlers / Plugins:", size="2", weight="medium"),
                rx.hstack(
                    rx.foreach(handlers, lambda h: chip(h, "blue")),
                    spacing="1",
                    wrap="wrap",
                ),
                spacing="1",
                margin_top="4px",
            ),
            rx.text(""),
        ),
        rx.cond(
            blob_available is not None,
            info_row("Blob Store", _blob_indicator(blob_available, blob_writable)),  # type: ignore[arg-type]
            rx.text(""),
        ),
        rx.cond(
            store is not None,
            info_row("Store", rx.text(store, size="2")),  # type: ignore[arg-type]
            rx.text(""),
        ),
        rx.cond(
            poller is not None,
            info_row("Poller", rx.text(poller, size="2")),  # type: ignore[arg-type]
            rx.text(""),
        ),
    )


def _mcpd_detail(
    name: str,
    status: rx.Var[str],
) -> rx.Component:
    """Minimal status card for mcpd (status only)."""
    return status_card(
        name,
        rx.cond(
            status == "ok",
            stat_badge("healthy", True),
            rx.cond(
                status == "unreachable",
                stat_badge("unreachable", False),
                stat_badge(status, False),
            ),
        ),
        info_row("Status", rx.text(status, size="2")),
    )


def health_page() -> rx.Component:
    """Health detail page with per-service information."""
    return shell(
        rx.vstack(
            # Header row
            rx.vstack(
                rx.hstack(
                    page_heading("Service Health"),
                    rx.spacer(),
                    rx.hstack(
                        rx.cond(
                            HealthState.loading,
                            rx.spinner(size="3"),
                            rx.text(""),
                        ),
                        rx.button(
                            rx.icon(tag="refresh_cw", size=16),
                            "Refresh",
                            on_click=HealthState.refresh,
                            size="2",
                            variant="soft",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    HealthState.last_refresh != "",
                    rx.hstack(
                        rx.icon(tag="clock", size=12, color=rx.color("gray", 11)),
                        rx.text(f"Last refreshed: {HealthState.last_refresh}", size="1", color_scheme="gray"),
                        spacing="1",
                    ),
                    rx.text(""),
                ),
                spacing="2",
                margin_bottom="16px",
            ),
            # Service detail cards
            rx.grid(
                _service_detail(
                    "Captured",
                    HealthState.captured_status,
                    HealthState.captured_version,
                    HealthState.captured_terminusdb,
                    HealthState.captured_handlers,
                    blob_available=HealthState.captured_blob_root_writable_available,
                    blob_writable=HealthState.captured_blob_root_writable,
                ),
                _service_detail(
                    "Queryd",
                    HealthState.queryd_status,
                    HealthState.queryd_version,
                    HealthState.queryd_terminusdb,
                    HealthState.queryd_plugins,
                ),
                _service_detail(
                    "Indexed",
                    HealthState.indexed_status,
                    HealthState.indexed_version,
                    HealthState.indexed_terminusdb,
                    HealthState.indexed_plugins,
                    store=HealthState.indexed_store,
                    poller=HealthState.indexed_poller,
                ),
                _mcpd_detail(
                    "MCPD",
                    HealthState.mcpd_status,
                ),
                columns={"initial": "1", "md": "2"},
                spacing="4",
                width="100%",
            ),
            spacing="5",
            width="100%",
        ),
        active="health",
    )
