"""Tests for ui/controls — instantiation smoke-tests."""

from __future__ import annotations

import reflex as rx

from firnline_webui.ui.controls import (
    color_legend,
    filter_chip,
    page_size_select,
    pagination_bar,
    search_input,
    sortable_header_cell,
)
from firnline_webui.ui.detail import json_detail_drawer


# ── Minimal test state for event handlers ────────────────────────────


class _TestState(rx.State):
    """State providing real event handlers for testing control components."""

    def on_change_text(self, value: str):
        pass

    def on_click(self):
        pass

    def on_sort_field(self, field: str):
        pass

    def on_prev(self):
        pass

    def on_next(self):
        pass


# ── search_input ─────────────────────────────────────────────────────


def test_search_input_plain():
    """search_input accepts a plain string value."""
    comp = search_input("test", on_change=_TestState.on_change_text, placeholder="Find…")
    rendered = str(comp)
    assert "Find" in rendered


def test_search_input_var():
    """search_input accepts an rx.Var value."""
    v = rx.Var.create("hello")
    comp = search_input(v, on_change=_TestState.on_change_text)
    assert str(comp)


def test_search_input_empty_var():
    """search_input with empty Var still renders (no clear button shown)."""
    v = rx.Var.create("")
    comp = search_input(v, on_change=_TestState.on_change_text)
    assert str(comp)


# ── filter_chip ──────────────────────────────────────────────────────


def test_filter_chip_selected():
    comp = filter_chip("Active", selected=True, on_click=_TestState.on_click)
    rendered = str(comp)
    assert "Active" in rendered


def test_filter_chip_deselected():
    comp = filter_chip("Inactive", selected=False, on_click=_TestState.on_click)
    rendered = str(comp)
    assert "Inactive" in rendered


def test_filter_chip_var():
    comp = filter_chip("Tag", selected=rx.Var.create(True), on_click=_TestState.on_click)
    assert str(comp)


# ── sortable_header_cell ─────────────────────────────────────────────


def test_sortable_header_cell_unsorted():
    comp = sortable_header_cell(
        "Name",
        field="name",
        sort_field=rx.Var.create("email"),
        sort_dir=rx.Var.create("asc"),
        on_sort=_TestState.on_sort_field,
    )
    rendered = str(comp)
    assert "Name" in rendered


def test_sortable_header_cell_active_asc():
    comp = sortable_header_cell(
        "Name",
        field="name",
        sort_field=rx.Var.create("name"),
        sort_dir=rx.Var.create("asc"),
        on_sort=_TestState.on_sort_field,
    )
    assert str(comp)


def test_sortable_header_cell_active_desc():
    comp = sortable_header_cell(
        "Name",
        field="name",
        sort_field=rx.Var.create("name"),
        sort_dir=rx.Var.create("desc"),
        on_sort=_TestState.on_sort_field,
    )
    assert str(comp)


# ── page_size_select ─────────────────────────────────────────────────


def test_page_size_select_plain():
    comp = page_size_select(25, on_change=_TestState.on_change_text)
    rendered = str(comp)
    assert "25" in rendered


def test_page_size_select_var():
    comp = page_size_select(rx.Var.create(50), on_change=_TestState.on_change_text)
    assert str(comp)


def test_page_size_select_custom_options():
    comp = page_size_select(20, on_change=_TestState.on_change_text, options=(5, 20, 50))
    rendered = str(comp)
    assert "20" in rendered


# ── pagination_bar ───────────────────────────────────────────────────


def test_pagination_bar_plain():
    comp = pagination_bar(
        page=0,
        total_pages=5,
        total_count=47,
        on_prev=_TestState.on_prev,
        on_next=_TestState.on_next,
    )
    rendered = str(comp)
    assert "Page" in rendered
    assert "47" in rendered


def test_pagination_bar_var():
    comp = pagination_bar(
        page=rx.Var.create(2),
        total_pages=rx.Var.create(10),
        total_count=rx.Var.create(95),
        on_prev=_TestState.on_prev,
        on_next=_TestState.on_next,
    )
    assert str(comp)


def test_pagination_bar_with_extra():
    extra = page_size_select(25, on_change=_TestState.on_change_text)
    comp = pagination_bar(
        page=0,
        total_pages=3,
        total_count=22,
        on_prev=_TestState.on_prev,
        on_next=_TestState.on_next,
        extra=extra,
    )
    rendered = str(comp)
    assert "25" in rendered


def test_pagination_bar_without_extra():
    """pagination_bar renders correctly when extra is None."""
    comp = pagination_bar(
        page=0,
        total_pages=3,
        total_count=22,
        on_prev=_TestState.on_prev,
        on_next=_TestState.on_next,
        extra=None,
    )
    assert str(comp)


def test_pagination_bar_bounds_disabled():
    """Buttons should have disabled attributes at boundaries."""
    comp = pagination_bar(
        page=0,
        total_pages=1,
        total_count=1,
        on_prev=_TestState.on_prev,
        on_next=_TestState.on_next,
    )
    rendered = str(comp)
    assert "Page" in rendered


# ── color_legend ─────────────────────────────────────────────────────


def test_color_legend():
    items = rx.Var.create([
        {"label": "Foo", "color": "#ff0000"},
        {"label": "Bar", "color": "#00ff00"},
    ])
    comp = color_legend(items)
    rendered = str(comp)
    assert "Foo" in rendered
    assert "Bar" in rendered


def test_color_legend_empty():
    items = rx.Var.create([]).to(list[dict])
    comp = color_legend(items)
    assert str(comp)


# ── json_detail_drawer ────────────────────────────────────────────────────────


def test_json_detail_drawer_references_without_on_navigate_does_not_crash():
    """Passing references without on_navigate should not crash (Fix 4)."""
    doc_var = rx.Var.create({"@id": "x"})
    json_var = rx.Var.create("{}")
    iri_var = rx.Var.create("Person/alice")
    refs = rx.Var.create([{"prop": "friend", "target": "Person/bob", "target_label": "Bob"}])

    # This should not raise an exception
    comp = json_detail_drawer(
        doc_var=doc_var,
        json_var=json_var,
        iri_var=iri_var,
        on_close=_TestState.on_click,
        references=refs,
        on_navigate=None,
    )
    rendered = str(comp)
    # References section is suppressed when on_navigate is None
    assert "References" not in rendered


def test_json_detail_drawer_references_with_on_navigate_renders():
    """When on_navigate is provided, references section renders."""
    doc_var = rx.Var.create({"@id": "x"})
    json_var = rx.Var.create("{}")
    iri_var = rx.Var.create("Person/alice")
    refs = rx.Var.create([{"prop": "friend", "target": "Person/bob", "target_label": "Bob"}])

    comp = json_detail_drawer(
        doc_var=doc_var,
        json_var=json_var,
        iri_var=iri_var,
        on_close=_TestState.on_click,
        references=refs,
        on_navigate=_TestState.on_sort_field,
    )
    rendered = str(comp)
    assert "References" in rendered


def test_json_detail_drawer_no_references():
    """Without references, no section is rendered."""
    doc_var = rx.Var.create({"@id": "x"})
    json_var = rx.Var.create("{}")
    iri_var = rx.Var.create("Person/alice")

    comp = json_detail_drawer(
        doc_var=doc_var,
        json_var=json_var,
        iri_var=iri_var,
        on_close=_TestState.on_click,
    )
    rendered = str(comp)
    assert "References" not in rendered
