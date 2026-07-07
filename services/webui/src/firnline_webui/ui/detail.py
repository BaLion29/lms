"""Shared JSON detail drawer component."""

from __future__ import annotations

import reflex as rx


def json_detail_drawer(
    doc_var: rx.Var[dict | None],
    json_var: rx.Var[str],
    iri_var: rx.Var[str],
    on_close,
    open_var: rx.Var[bool] | None = None,
) -> rx.Component:
    """A dialog showing pretty-printed JSON of a document.

    Args:
        doc_var: Var pointing to the selected dict.
        json_var: Var pointing to the pretty-printed JSON string.
        iri_var: Var pointing to the document IRI (for display).
        on_close: Event handler to close the dialog.
        open_var: Optional controlled-open var (defaults to doc_var != None).
    """
    is_open: rx.Var = rx.Var.create(doc_var.to(bool) if open_var is None else open_var)
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.box(
                        rx.icon(tag="file_json", size=14, color=rx.color("accent", 11)),
                        background=rx.color("accent", 3),
                        border_radius="6px",
                        width="26px",
                        height="26px",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    ),
                    rx.text("Document Detail", size="4"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.icon_button(
                            rx.icon(tag="x", size=16),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            on_click=on_close,
                        ),
                    ),
                    align="center",
                ),
            ),
            # IRI display
            rx.cond(
                (iri_var != ""),
                rx.vstack(
                    rx.text("IRI", size="1", color_scheme="gray", weight="medium"),
                    rx.hstack(
                        rx.box(
                            rx.text(
                                iri_var,
                                size="1",
                                font_family="mono",
                                word_break="break-all",
                            ),
                            background=rx.color("gray", 2),
                            border=f"1px solid {rx.color('gray', 4)}",
                            border_radius="6px",
                            padding="2",
                            width="100%",
                        ),
                        rx.icon_button(
                            rx.icon(tag="clipboard", size=14),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            on_click=[
                                rx.set_clipboard(iri_var),
                                rx.toast.success("Copied IRI"),
                            ],
                        ),
                        align="start",
                        width="100%",
                    ),
                    spacing="1",
                    width="100%",
                    margin_bottom="3",
                ),
            ),
            # Pretty JSON
            rx.text(
                "Raw Document", size="1", color_scheme="gray", weight="medium"
            ),
            rx.box(
                rx.code_block(
                    json_var,
                    language="json",
                    wrap_long_lines=True,
                    width="100%",
                ),
                max_height="55vh",
                overflow="auto",
                width="100%",
                font_size="12px",
            ),
            # Footer
            rx.hstack(
                rx.spacer(),
                rx.button(
                    rx.icon(tag="clipboard", size=14),
                    "Copy JSON",
                    variant="soft",
                    size="1",
                    on_click=[
                        rx.set_clipboard(json_var),
                        rx.toast.success("Copied JSON"),
                    ],
                ),
                rx.dialog.close(
                    rx.button(
                        "Close",
                        variant="outline",
                        size="1",
                        on_click=on_close,
                    ),
                ),
                width="100%",
                justify="end",
                spacing="2",
                padding_top="3",
            ),
            max_width="720px",
            max_height="85vh",
            overflow_y="auto",
        ),
        open=is_open,
        on_open_change=on_close,
    )
