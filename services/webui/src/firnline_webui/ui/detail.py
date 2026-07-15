"""Shared JSON detail drawer component."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.theme import FONT_MONO, RADIUS_MEDIUM, SHADOW_RAISED, SPACE_1_5, SPACE_2, SPACE_3


def iri_var(selected_doc: rx.Var[dict | None]) -> rx.Var[str]:
    """Derive an IRI Var from a selected_doc Var for use with :func:`json_detail_drawer`.

    Args:
        selected_doc: Var pointing to the currently selected document dict.
    """
    return rx.Var.create(
        rx.cond(
            selected_doc.to(bool) & (selected_doc["@id"].to(str) != ""),  # type: ignore[index]
            selected_doc["@id"].to(str),  # type: ignore[index]
            "",
        )
    )


def json_detail_drawer(
    doc_var: rx.Var[dict | None],
    json_var: rx.Var[str],
    iri_var: rx.Var[str],
    on_close,
    open_var: rx.Var[bool] | None = None,
    references: rx.Var[list[dict]] | None = None,
    on_navigate=None,
) -> rx.Component:
    """A dialog showing pretty-printed JSON of a document.

    Args:
        doc_var: Var pointing to the selected dict.
        json_var: Var pointing to the pretty-printed JSON string.
        iri_var: Var pointing to the document IRI (for display).
        on_close: Event handler to close the dialog.
        open_var: Optional controlled-open var (defaults to doc_var != None).
        references: Optional Var of ``[{prop, target, target_label}, …]``.
            When provided together with *on_navigate*, a "References" section
            with clickable link buttons is rendered between the IRI and raw
            JSON blocks.  If *on_navigate* is ``None`` the references section
            is suppressed entirely to avoid runtime errors.
        on_navigate: Optional event handler called with the target IRI when a
            reference link is clicked.  Required for the references section to
            appear.
    """
    is_open: rx.Var = rx.Var.create(doc_var.to(bool) if open_var is None else open_var)

    # Build references section only when both references and on_navigate are provided.
    # We must avoid compiling rx.foreach with a null iterable, so we build
    # the section conditionally at Python time.
    if references is not None and on_navigate is not None:
        refs_section: rx.Component = rx.cond(
            references.length() > 0,  # type: ignore[union-attr]
            rx.vstack(
                rx.text("References", size="1", color_scheme="gray", weight="medium"),
                rx.box(
                    rx.foreach(
                        references,  # type: ignore[arg-type]
                        lambda ref: rx.button(
                            rx.hstack(
                                rx.icon(tag="link", size=12, color=rx.color("accent", 9)),
                                rx.text(
                                    ref["target_label"].to(str),
                                    size="1",
                                    font_family=FONT_MONO,
                                ),
                                rx.badge(
                                    ref["prop"].to(str),
                                    size="1",
                                    variant="surface",
                                    color_scheme="gray",
                                ),
                                spacing="2",
                                align="center",
                            ),
                            variant="ghost",
                            size="1",
                            on_click=on_navigate(ref["target"].to(str)),
                            width="100%",
                            justify="start",
                            cursor="pointer",
                        ),
                    ),
                    background=rx.color("gray", 2),
                    border=f"1px solid {rx.color('gray', 4)}",
                    border_radius=RADIUS_MEDIUM,
                    padding=SPACE_1_5,
                    max_height="180px",
                    overflow="auto",
                    width="100%",
                ),
                spacing="1",
                width="100%",
                margin_bottom="12px",
            ),
        )
    else:
        refs_section = rx.fragment()

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
                            custom_attrs={"aria-label": "Close detail"},
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
                                font_family=FONT_MONO,
                                word_break="break-all",
                            ),
                            background=rx.color("gray", 2),
                            border=f"1px solid {rx.color('gray', 4)}",
                            border_radius=RADIUS_MEDIUM,
                            padding=SPACE_2,
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
                            custom_attrs={"aria-label": "Copy IRI to clipboard"},
                        ),
                        align="start",
                        width="100%",
                    ),
                    spacing="1",
                    width="100%",
                margin_bottom=SPACE_3,
                ),
            ),
            # References section (only when references Var is provided)
            refs_section,
            # Pretty JSON
            rx.text("Raw Document", size="1", color_scheme="gray", weight="medium"),
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
                font_size=SPACE_3,
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
                        variant="soft",
                        size="1",
                        on_click=on_close,
                    ),
                ),
                width="100%",
                justify="end",
                spacing="2",
                padding_top=SPACE_3,
            ),
            max_width="720px",
            max_height="85vh",
            overflow_y="auto",
            border_radius=RADIUS_MEDIUM,
            box_shadow=SHADOW_RAISED,
        ),
        open=is_open,
        on_open_change=on_close,
    )
