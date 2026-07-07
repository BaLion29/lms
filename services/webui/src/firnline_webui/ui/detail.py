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
    """A right-side drawer showing pretty-printed JSON of a document.

    Args:
        doc_var: Var pointing to the selected dict.
        json_var: Var pointing to the pretty-printed JSON string.
        iri_var: Var pointing to the document IRI (for display).
        on_close: Event handler to close the drawer.
        open_var: Optional controlled-open var (defaults to doc_var != None).
    """
    is_open: rx.Var = rx.Var.create(doc_var.to(bool) if open_var is None else open_var)
    return rx.drawer.root(
        rx.drawer.content(
            rx.drawer.title(
                rx.hstack(
                    rx.icon(tag="file_json", size=18),
                    rx.text("Document Detail", size="4"),
                    rx.spacer(),
                    rx.drawer.close(
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
                        rx.code_block(
                            iri_var,
                            language="uri",
                            wrap_long_lines=True,
                            width="100%",
                        ),
                        rx.tooltip(
                            rx.icon_button(
                                rx.icon(tag="clipboard", size=14),
                                variant="ghost",
                                color_scheme="gray",
                                size="1",
                                on_click=rx.set_clipboard(iri_var),
                            ),
                            content="Copy IRI",
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
            rx.text("Raw Document", size="1", color_scheme="gray", weight="medium"),
            rx.code_block(
                json_var,
                language="json",
                wrap_long_lines=True,
                width="100%",
            ),
        ),
        open=is_open,
        direction="right",
    )
