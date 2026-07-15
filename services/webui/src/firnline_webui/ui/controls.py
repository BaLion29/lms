"""Reusable control components — search, filters, sort, pagination."""

from __future__ import annotations

import reflex as rx


def search_input(
    value: rx.Var[str],
    on_change,
    placeholder: str = "Search…",
    **props,
) -> rx.Component:
    """Search input with magnifying-glass icon, clear button, and debounce.

    Args:
        value: Current search text Var.
        on_change: Event handler called with the new text value.
        placeholder: Placeholder text.
        **props: Extra props forwarded to the root element.
    """
    v = rx.Var.create(value)
    return rx.debounce_input(
        rx.input(
            rx.input.slot(
                rx.icon(tag="search", size=14, color=rx.color("gray", 9)),
            ),
            rx.cond(
                v != "",
                rx.input.slot(
                    rx.icon_button(
                        rx.icon(tag="x", size=14),
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        on_click=on_change(""),
                        custom_attrs={"aria-label": "Clear search"},
                    ),
                ),
            ),
            placeholder=placeholder,
            value=v,
            on_change=on_change,
            size="2",
            **props,
        ),
        debounce_timeout=300,
    )


def filter_chip(
    label: str,
    selected: rx.Var[bool] | bool,
    on_click,
) -> rx.Component:
    """Toggleable filter chip — solid accent when selected, soft grey otherwise.

    Args:
        label: Chip label text.
        selected: Whether the chip is currently active.
        on_click: Event handler to toggle selection.
    """
    return rx.badge(
        label,
        variant=rx.cond(selected, "solid", "surface"),
        color_scheme=rx.cond(selected, "cyan", "gray"),
        cursor="pointer",
        on_click=on_click,
        size="2",
    )


def sortable_header_cell(
    label: str,
    field: str,
    sort_field: rx.Var[str],
    sort_dir: rx.Var[str],
    on_sort,
) -> rx.Component:
    """Clickable table column header cell with sort-direction arrows.

    Args:
        label: Display text for the column header.
        field: Identifier for this column (passed to *on_sort*).
        sort_field: Currently active sort field Var.
        sort_dir: Current sort direction Var (``"asc"`` or ``"desc"``).
        on_sort: Event handler receiving *field* when clicked.
    """
    is_active: rx.Var = (sort_field == field)
    return rx.table.column_header_cell(
        rx.hstack(
            rx.text(label, size="2"),
            rx.cond(
                is_active & (sort_dir == "asc"),
                rx.icon(tag="chevron_up", size=14, color=rx.color("accent", 9)),
                rx.cond(
                    is_active & (sort_dir == "desc"),
                    rx.icon(tag="chevron_down", size=14, color=rx.color("accent", 9)),
                    rx.icon(tag="chevrons_up_down", size=14, color=rx.color("gray", 7)),
                ),
            ),
            spacing="1",
            align="center",
        ),
        cursor="pointer",
        on_click=on_sort(field),
    )


def page_size_select(
    value: rx.Var[int] | int,
    on_change,
    options: tuple[int, ...] = (10, 25, 50, 100),
) -> rx.Component:
    """Compact row-per-page selector.

    Args:
        value: Current page size.
        on_change: Event handler receiving the new size string.
        options: Available page sizes.
    """
    return rx.select(
        [str(o) for o in options],
        value=rx.Var.create(value).to(str),
        on_change=on_change,
        size="1",
        width="90px",
    )


def pagination_bar(
    page: rx.Var[int] | int,
    total_pages: rx.Var[int] | int,
    total_count: rx.Var[int] | int,
    on_prev,
    on_next,
    extra: rx.Component | None = None,
) -> rx.Component:
    """Prev/next buttons + page count caption; buttons disabled at bounds.

    Generalises the private ``_pagination_bar`` from ``pages/browse.py``.

    Args:
        page: Zero-based current page index.
        total_pages: Total number of pages.
        total_count: Total number of items.
        on_prev: Event handler for previous page.
        on_next: Event handler for next page.
        extra: Optional extra component placed between caption and buttons
            (e.g. a :func:`page_size_select`).  **Must be a static component**
            (e.g. a :func:`page_size_select`), **not** a state-dependent value
            — the decision to include it is made at Python time, not in the
            browser.
    """
    pv = rx.Var.create(page)
    tpv = rx.Var.create(total_pages)
    tcv = rx.Var.create(total_count)
    return rx.hstack(
        rx.text(
            f"Page {(pv + 1)} of {tpv} ({tcv} total)",
            size="2",
            color_scheme="gray",
        ),
        extra if extra is not None else rx.fragment(),
        rx.spacer(),
        rx.hstack(
            rx.icon_button(
                rx.icon(tag="chevron_left", size=16),
                variant="ghost",
                size="1",
                on_click=on_prev,
                disabled=pv <= 0,
                custom_attrs={"aria-label": "Previous page"},
            ),
            rx.icon_button(
                rx.icon(tag="chevron_right", size=16),
                variant="ghost",
                size="1",
                on_click=on_next,
                disabled=(pv + 1) >= tpv,
                custom_attrs={"aria-label": "Next page"},
            ),
            spacing="1",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def color_legend(
    items: rx.Var[list[dict]],
) -> rx.Component:
    """Horizontal wrap of colour swatch + label pairs.

    Args:
        items: A Var holding a list of dicts with keys ``"label"`` and
            ``"color"`` (CSS colour strings).
    """
    # Ensure the items var is typed for foreach safety.
    # _var_type is private; wrap in try/except in case a Reflex upgrade
    # removes or renames it.
    from typing import Any as _Any

    try:
        typed = items.to(list[dict]) if items._var_type is _Any else items
    except AttributeError:
        typed = items.to(list[dict])
    return rx.flex(
        rx.foreach(
            typed,
            lambda item: rx.hstack(
                rx.box(
                    width="12px",
                    height="12px",
                    border_radius="3px",
                    background=item["color"],
                    border=f"1px solid {rx.color('gray', 5)}",
                ),
                rx.text(item["label"].to(str), size="1", color_scheme="gray"),
                spacing="1",
                align="center",
            ),
        ),
        wrap="wrap",
        gap_x="3",
        gap_y="1",
        width="100%",
    )
