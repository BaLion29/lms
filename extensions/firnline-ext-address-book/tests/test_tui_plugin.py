"""Tests for the address-book TUI screen plugin."""

from __future__ import annotations

from firnline_core.screenspec import ScreenSpec


def test_plugin_singleton_exists():
    """The module-level ``plugin`` singleton is loadable."""
    from firnline_ext_address_book.tui import plugin

    assert plugin is not None
    assert plugin.name == "address_book_tui"


def test_plugin_name():
    from firnline_ext_address_book.tui import plugin

    assert plugin.name == "address_book_tui"


def test_plugin_requires():
    """The requires list specifies the address_book module."""
    from firnline_ext_address_book.tui import plugin

    assert len(plugin.requires) == 1
    req = plugin.requires[0]
    assert req.name == "address_book"
    assert req.range == ">=0.1.0 <0.2.0"


def test_screens_returns_single_spec():
    """screens() returns exactly one ScreenSpec."""
    from firnline_ext_address_book.tui import plugin

    screens = plugin.screens()
    assert len(screens) == 1
    spec = screens[0]
    assert isinstance(spec, ScreenSpec)


def test_screenspec_attributes():
    """The ScreenSpec has correct metadata values."""
    from firnline_ext_address_book.tui import plugin

    spec = plugin.screens()[0]
    assert spec.screen_id == "address-book"
    assert spec.title == "Address Book"
    assert spec.nav_section == "EXTENSIONS"
    assert spec.nav_icon == "👥"
    assert spec.nav_order == 10
    assert spec.key == "p"


def test_screen_factory_callable():
    """The screen_factory is callable (without requiring Textual)."""
    from firnline_ext_address_book.tui import plugin

    spec = plugin.screens()[0]
    assert callable(spec.screen_factory)


def test_screen_id_validation():
    """The screen_id is a valid slug."""
    spec = ScreenSpec(
        screen_id="address-book",
        title="Address Book",
        screen_factory=lambda: None,
        nav_section="EXTENSIONS",
        nav_icon="👥",
        nav_order=10,
        key="p",
    )
    assert spec.screen_id == "address-book"
    # Should not raise ValueError
