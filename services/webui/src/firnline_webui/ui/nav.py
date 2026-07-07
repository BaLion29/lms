"""Shell layout — sidebar + header + content area."""

from __future__ import annotations

from typing import Literal

import reflex as rx

from firnline_webui.state.auth import AuthState
from firnline_webui.state.base import BaseState

NavActive = Literal["home", "capture", "inbox", "browse", "health", "modules"]

NAV_ITEMS: list[dict] = [
    {"label": "Home", "icon": "house", "active": "home", "route": "/"},
    {"label": "Capture", "icon": "pencil_line", "active": "capture", "route": "/capture"},
    {"label": "Inbox", "icon": "inbox", "active": "inbox", "route": "/inbox"},
    {"label": "Browse", "icon": "database", "active": "browse", "route": "/browse"},
    {"label": "Health", "icon": "activity", "active": "health", "route": "/health"},
    {"label": "Modules", "icon": "blocks", "active": "modules", "route": "/modules"},
]

SIDEBAR_WIDTH = "240px"


def _nav_link(icon_tag: str, label: str, route: str, is_active: bool) -> rx.Component:
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
        width="100%",
        text_decoration="none",
    )


def sidebar(active: str) -> rx.Component:
    """Fixed left sidebar."""
    return rx.vstack(
        # Wordmark
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
            padding_x="16px",
            padding_top="32px",
            padding_bottom="16px",
        ),
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
        # Nav links
        rx.vstack(
            *[
                _nav_link(
                    item["icon"],
                    item["label"],
                    item["route"],
                    item["active"] == active,
                )
                for item in NAV_ITEMS
            ],
            spacing="1",
            padding_x="8px",
            width="100%",
        ),
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
    )


def page_header(title: str) -> rx.Component:
    """Sticky top header bar with page title and env badge."""
    return rx.hstack(
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
        padding_x="32px",
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
        rx.vstack(
            page_header(_page_title_for(active)),
            rx.scroll_area(
                rx.container(
                    content,
                    max_width="1200px",
                    padding="32px",
                ),
                flex="1",
            ),
            flex="1",
            margin_left=SIDEBAR_WIDTH,
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
        "health": "Service Health",
        "modules": "Schema Modules",
    }
    return titles.get(active, "Firnline")
