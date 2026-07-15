"""Smoke tests for the firnline_webui Reflex app."""

from __future__ import annotations

import pytest


def test_app_imports():
    """The app module must be importable."""
    from firnline_webui.firnline_webui import app

    assert app is not None


def test_pages_registered():
    """All expected routes must be registered."""
    from firnline_webui.firnline_webui import app

    page_routes = list(app._unevaluated_pages.keys())
    expected = {
        "index",
        "capture",
        "inbox",
        "browse",
        "browse/[class_name]",
        "calendar",
        "automations",
        "health",
        "modules",
        "login",
    }
    assert set(page_routes) == expected


@pytest.mark.parametrize(
    "route,title",
    [
        ("index", "Firnline — Dashboard"),
        ("capture", "Firnline — Capture"),
        ("inbox", "Firnline — Inbox"),
        ("browse", "Firnline — Browse"),
        ("browse/[class_name]", "Firnline — Browse"),
        ("calendar", "Firnline — Calendar"),
        ("automations", "Firnline — Automations"),
        ("health", "Firnline — Health"),
        ("modules", "Firnline — Modules"),
        ("login", "Firnline — Sign in"),
    ],
)
def test_page_titles(route: str, title: str):
    """Each page must have the correct title."""
    from firnline_webui.firnline_webui import app

    page = app._unevaluated_pages[route]
    assert page.title == title


def test_all_pages_compile():
    """Calling each page component function must succeed without error."""
    from firnline_webui.firnline_webui import app

    for key, page in app._unevaluated_pages.items():
        comp = page.component()
        assert comp is not None, f"Page '{key}' returned None"


def test_on_load_events():
    """Verify on_load handlers — each data page has [AuthState.check, Data.load]. Login has AuthState.check_login."""
    from firnline_webui.firnline_webui import app

    from firnline_webui.state.automations import AutomationsState
    from firnline_webui.state.browse import BrowseClassState, BrowseState
    from firnline_webui.state.calendar import CalendarState
    from firnline_webui.state.capture import CaptureState
    from firnline_webui.state.health import HealthState
    from firnline_webui.state.inbox import InboxState
    from firnline_webui.state.modules import ModulesState

    # Login page: single handler (not wrapped in a list)
    login = app._unevaluated_pages["login"].on_load
    assert login is not None
    from reflex_base.event import EventHandler

    assert isinstance(login, EventHandler)
    assert login.fn.__name__ == "check_login"

    # Data pages: [AuthState.check, DataState.load/refresh]
    pages: dict[str, tuple[type, str]] = {
        "index": (HealthState, "refresh"),
        "capture": (CaptureState, "load"),
        "inbox": (InboxState, "load"),
        "browse": (BrowseState, "load"),
        "browse/[class_name]": (BrowseClassState, "load"),
        "calendar": (CalendarState, "load"),
        "automations": (AutomationsState, "load"),
        "health": (HealthState, "refresh"),
        "modules": (ModulesState, "load"),
    }

    for route, (state_cls, method_name) in pages.items():
        on_load = app._unevaluated_pages[route].on_load
        assert isinstance(on_load, list), f"{route}: on_load should be a list"
        assert len(on_load) == 2, f"{route}: expected 2 handlers, got {len(on_load)}"
        assert on_load[0].fn.__name__ == "check", f"{route}: first handler should be check"
        assert on_load[1].fn.__name__ == method_name, f"{route}: second handler should be {method_name}"
