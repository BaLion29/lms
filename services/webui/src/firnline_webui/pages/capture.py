"""Capture page — note and file capture."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.capture import CaptureState
from firnline_webui.ui.cards import chip
from firnline_webui.ui.nav import shell


def _note_tab() -> rx.Component:
    """Note capture form."""
    return rx.card(
        rx.vstack(
            # Kind field
            rx.hstack(
                rx.text("Kind", size="2", weight="medium", width="60px"),
                rx.input(
                    value=CaptureState.kind,
                    on_change=CaptureState.set_kind,
                    placeholder="note",
                    size="2",
                    width="200px",
                ),
                spacing="3",
                align="center",
            ),
            # Text area
            rx.text_area(
                value=CaptureState.note_text,
                on_change=CaptureState.set_note_text,
                placeholder="Type your note here…",
                rows="6",
                width="100%",
                auto_focus=True,
            ),
            # Metadata accordion
            _metadata_section(),
            # Submit button
            rx.hstack(
                rx.button(
                    rx.cond(
                        CaptureState.submitting,
                        rx.spinner(size="3"),
                        rx.icon(tag="send", size=16),
                    ),
                    " Capture",
                    on_click=CaptureState.submit_note,
                    disabled=CaptureState.submitting,
                    size="2",
                ),
                width="100%",
                justify="end",
            ),
            # Result callout
            rx.cond(
                CaptureState.result_message != "",
                rx.callout(
                    rx.hstack(
                        rx.cond(
                            CaptureState.result_ok,
                            rx.icon(tag="circle_check", size=16, color="var(--green-9)"),
                            rx.icon(tag="circle_alert", size=16, color="var(--red-9)"),
                        ),
                        rx.text(CaptureState.result_message, size="2"),
                        rx.spacer(),
                        rx.icon_button(
                            rx.icon(tag="x", size=14),
                            variant="ghost",
                            size="1",
                            on_click=CaptureState.clear_result,
                        ),
                        align="center",
                        width="100%",
                    ),
                    color_scheme=rx.cond(CaptureState.result_ok, "green", "red"),
                    size="1",
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
        ),
        size="3",
    )


def _file_tab() -> rx.Component:
    """File capture form."""
    return rx.card(
        rx.vstack(
            # Kind field
            rx.hstack(
                rx.text("Kind", size="2", weight="medium", width="60px"),
                rx.input(
                    value=CaptureState.kind,
                    on_change=CaptureState.set_kind,
                    placeholder="file",
                    size="2",
                    width="200px",
                ),
                spacing="3",
                align="center",
            ),
            # Upload dropzone
            rx.upload(
                rx.vstack(
                    rx.icon(tag="upload", size=28, color=rx.color("accent", 9)),
                    rx.text("Drag and drop a file here, or click to browse", size="2"),
                    rx.text("Max 25 MB", size="1", color_scheme="gray"),
                    spacing="2",
                    align="center",
                    padding="32px",
                ),
                id="capture_upload",
                multiple=False,
                max_size=25 * 1024 * 1024,
                on_drop=CaptureState.handle_upload,
                width="100%",
                border=f"2px dashed {rx.color('gray', 6)}",
                border_radius="12px",
                _hover={
                    "border_color": rx.color("accent", 8),
                    "background": rx.color("accent", 2),
                },
                transition="all 0.2s ease",
                cursor="pointer",
            ),
            # Metadata accordion
            _metadata_section(),
            spacing="4",
            width="100%",
        ),
        size="3",
    )


def _metadata_section() -> rx.Component:
    """Collapsible metadata JSON section."""
    return rx.accordion.root(
        rx.accordion.item(
            header="Metadata (JSON)",
            content=rx.text_area(
                value=CaptureState.metadata_json,
                on_change=CaptureState.set_metadata_json,
                placeholder='{"key": "value"}',
                rows="4",
                width="100%",
                size="1",
            ),
        ),
        collapsible=True,
        width="100%",
        variant="soft",
        color_scheme="gray",
    )


def capture_page() -> rx.Component:
    """Capture page with Note and File tabs."""
    return shell(
        rx.vstack(
            # Header row
            rx.hstack(
                rx.heading("Capture", size="6"),
                rx.spacer(),
                # Handler names display
                rx.cond(
                    CaptureState.handler_names.length() > 0,
                    rx.hstack(
                        rx.text("Handlers:", size="1", color_scheme="gray"),
                        rx.foreach(
                            CaptureState.handler_names,
                            lambda name: chip(name, "blue"),
                        ),
                        spacing="1",
                        align="center",
                    ),
                ),
                spacing="3",
                align="center",
                width="100%",
                margin_bottom="8px",
            ),
            # Tabs
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Note", value="note", on_click=CaptureState.set_mode("note")),
                    rx.tabs.trigger("File", value="file", on_click=CaptureState.set_mode("file")),
                ),
                rx.tabs.content(
                    _note_tab(),
                    value="note",
                ),
                rx.tabs.content(
                    _file_tab(),
                    value="file",
                ),
                value=CaptureState.mode,
                width="100%",
            ),
            spacing="5",
            width="100%",
        ),
        active="capture",
    )
