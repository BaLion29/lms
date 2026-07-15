"""Shell layout — sidebar + header + content area."""

from __future__ import annotations

from typing import Literal

import reflex as rx

from firnline_webui.state.auth import AuthState
from firnline_webui.state.base import BaseState

NavActive = Literal["home", "capture", "inbox", "browse", "calendar", "automations", "health", "modules"]

NAV_ITEMS: list[dict] = [
    {"label": "Home", "icon": "house", "active": "home", "route": "/"},
    {"label": "Capture", "icon": "pencil_line", "active": "capture", "route": "/capture"},
    {"label": "Inbox", "icon": "inbox", "active": "inbox", "route": "/inbox"},
    {"label": "Browse", "icon": "database", "active": "browse", "route": "/browse"},
    {"label": "Calendar", "icon": "calendar_days", "active": "calendar", "route": "/calendar"},
    {"label": "Automations", "icon": "zap", "active": "automations", "route": "/automations"},
    {"label": "Health", "icon": "activity", "active": "health", "route": "/health"},
    {"label": "Modules", "icon": "blocks", "active": "modules", "route": "/modules"},
]

SIDEBAR_WIDTH = "240px"


class MobileNavState(rx.State):
    """Tiny UI-only state for the mobile navigation drawer."""

    drawer_open: bool = False

    def toggle_drawer(self):
        self.drawer_open = not self.drawer_open

    def close_drawer(self):
        self.drawer_open = False


def _nav_link(icon_tag: str, label: str, route: str, is_active: bool, on_click=None) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.icon(tag=icon_tag, size=16),
            rx.text(label, size="2", weight="medium"),
            spacing="2",
            align="center",
            padding_x="12px",
            padding_y="8px",
            border_radius="8px",
            border_left=rx.cond(
                is_active,
                f"3px solid {rx.color('accent', 9)}",
                "3px solid transparent",
            ),
            bg=rx.cond(is_active, rx.color("accent", 3), "transparent"),
            color=rx.cond(is_active, rx.color("accent", 11), rx.color("gray", 11)),
            _hover={"bg": rx.color("accent", 2)},
        ),
        href=route,
        on_click=on_click,
        width="100%",
        text_decoration="none",
        custom_attrs={"aria-current": rx.cond(is_active, "page", "false")},
    )


def _nav_links(active: str, on_navigate=None) -> rx.Component:
    """Reusable nav-links list — shared by sidebar and mobile drawer.

    If *on_navigate* is provided, it is attached as ``on_click`` to each link
    (used by the mobile drawer to close on navigation).
    """
    return rx.vstack(
        *[
            _nav_link(
                item["icon"],
                item["label"],
                item["route"],
                item["active"] == active,
                on_click=on_navigate,
            )
            for item in NAV_ITEMS
        ],
        spacing="1",
        padding_x="8px",
        width="100%",
    )


def sidebar(active: str) -> rx.Component:
    """Fixed left sidebar — hidden on small screens (visible >= md)."""
    return rx.vstack(
        # Top spacer (replaces logo+wordmark moved to header)
        rx.box(height="16px"),
        rx.divider(),
        # Section label
        rx.text(
            "MAIN",
            size="1",
            weight="medium",
            color=rx.color("gray", 9),
            letter_spacing="0.08em",
            padding_x="16px",
            padding_y="4px",
        ),
        # Nav links (shared component)
        _nav_links(active),
        rx.spacer(),
        # Bottom: footer with divider, color-mode toggle and logout
        rx.divider(),
        rx.hstack(
            rx.icon_button(
                rx.icon(tag="sun_moon", size=16),
                on_click=rx.toggle_color_mode,
                variant="ghost",
                color_scheme="gray",
                size="1",
                custom_attrs={"aria-label": "Toggle color mode"},
            ),
            rx.spacer(),
            rx.cond(
                AuthState.auth_enabled,
                rx.icon_button(
                    rx.icon(tag="log_out", size=16),
                    on_click=AuthState.logout,
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    custom_attrs={"aria-label": "Log out"},
                ),
            ),
            padding_x="16px",
            padding_y="8px",
            width="100%",
        ),
        height="100vh",
        width=SIDEBAR_WIDTH,
        position="fixed",
        left="0",
        top="0",
        background=rx.color("gray", 2),
        border_right=f"1px solid {rx.color('gray', 4)}",
        backdrop_filter="blur(8px)",
        z_index="40",
        spacing="1",
        display=rx.breakpoints({"initial": "none", "md": "flex"}),
    )


def _mobile_nav_drawer(active: str) -> rx.Component:
    """SSR-safe mobile navigation overlay (conditional, no vaul dependency)."""
    return rx.cond(
        MobileNavState.drawer_open,
        rx.fragment(
            # Backdrop overlay — closes drawer on click
            rx.box(
                on_click=MobileNavState.close_drawer,
                position="fixed",
                inset="0",
                z_index="50",
                background="rgba(0,0,0,0.5)",
                display=rx.breakpoints({"initial": "block", "md": "none"}),
            ),
            # Slide-in panel from the left
            rx.vstack(
                rx.hstack(
                    rx.hstack(
                        rx.icon(tag="mountain_snow", size=16, color=rx.color("accent", 11)),
                        rx.text("firnline", size="4", weight="bold"),
                        spacing="2",
                    ),
                    rx.spacer(),
                    rx.icon_button(
                        rx.icon(tag="x", size=16),
                        on_click=MobileNavState.close_drawer,
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        custom_attrs={"aria-label": "Close navigation menu"},
                    ),
                    padding_x="16px",
                    padding_y="12px",
                    width="100%",
                ),
                rx.divider(),
                _nav_links(active, on_navigate=MobileNavState.close_drawer),
                rx.spacer(),
                rx.divider(),
                rx.hstack(
                    rx.icon_button(
                        rx.icon(tag="sun_moon", size=16),
                        on_click=rx.toggle_color_mode,
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        custom_attrs={"aria-label": "Toggle color mode"},
                    ),
                    rx.spacer(),
                    rx.cond(
                        AuthState.auth_enabled,
                        rx.icon_button(
                            rx.icon(tag="log_out", size=16),
                            on_click=AuthState.logout,
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            custom_attrs={"aria-label": "Log out"},
                        ),
                    ),
                    padding_x="16px",
                    padding_y="8px",
                    width="100%",
                ),
                position="fixed",
                top="0",
                left="0",
                height="100vh",
                width="260px",
                background=rx.color("gray", 2),
                overflow_y="auto",
                z_index="60",
                spacing="1",
                display=rx.breakpoints({"initial": "flex", "md": "none"}),
                custom_attrs={"role": "dialog", "aria-modal": "true", "aria-label": "Navigation"},
            ),
        ),
    )


def page_header(title: str) -> rx.Component:
    """Sticky top header bar with page title, env badge, and mobile hamburger."""
    return rx.hstack(
        # Hamburger — visible only on small screens
        rx.icon_button(
            rx.icon(tag="menu", size=16),
            variant="ghost",
            color_scheme="gray",
            size="2",
            display=rx.breakpoints({"initial": "flex", "md": "none"}),
            custom_attrs={"aria-label": "Open navigation menu"},
            on_click=MobileNavState.toggle_drawer,
        ),
        # Logo + wordmark
        rx.hstack(
            rx.box(
                rx.icon(tag="mountain_snow", size=16, color="white"),
                background=rx.color("accent", 9),
                border_radius="8px",
                width="28px",
                height="28px",
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            rx.text("firnline", size="4", weight="bold", color=rx.color("gray", 12)),
            spacing="2",
            align="center",
        ),
        rx.divider(orientation="vertical", height="20px"),
        rx.heading(title, size="4", weight="medium"),
        rx.spacer(),
        rx.badge(
            rx.text(
                f"{BaseState.org}/{BaseState.db}@{BaseState.branch}",
                size="1",
            ),
            variant="surface",
            color_scheme="cyan",
        ),
        spacing="3",
        align="center",
        padding_x=rx.breakpoints({"initial": "16px", "md": "32px"}),
        padding_y="12px",
        position="sticky",
        top="0",
        z_index="30",
        backdrop_filter="blur(8px)",
        background=rx.color("gray", 1),
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        width="100%",
    )


def shell(content: rx.Component, active: str) -> rx.Component:
    """Full-page layout: sidebar + header + scrollable content area."""
    return rx.flex(
        sidebar(active),
        _mobile_nav_drawer(active),
        rx.vstack(
            page_header(_page_title_for(active)),
            rx.scroll_area(
                rx.container(
                    content,
                    max_width="1200px",
                    padding="32px",
                    custom_attrs={"role": "main"},
                ),
                flex="1",
            ),
            flex="1",
            margin_left=rx.breakpoints({"initial": "0", "md": SIDEBAR_WIDTH}),
            min_height="100vh",
            spacing="0",
            background=f"linear-gradient(to bottom, {rx.color('gray', 1)}, {rx.color('gray', 2)})",
        ),
    )


def _page_title_for(active: str) -> str:
    titles = {
        "home": "Dashboard",
        "capture": "Capture",
        "inbox": "Inbox",
        "browse": "Browse",
        "calendar": "Calendar",
        "automations": "Automations",
        "health": "Service Health",
        "modules": "Schema Modules",
    }
    return titles.get(active, "Firnline")
