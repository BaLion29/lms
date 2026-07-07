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

SIDEBAR_WIDTH = "230px"


def _nav_link(icon_tag: str, label: str, route: str, is_active: bool) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.icon(tag=icon_tag, size=18),
            rx.text(label, size="2", weight="medium"),
            spacing="3",
            align="center",
            padding_x="3",
            padding_y="2",
            border_radius="md",
            bg=rx.cond(is_active, rx.color("accent", 3), "transparent"),
            color=rx.cond(is_active, rx.color("accent", 11), rx.color("gray", 11)),
            _hover={"bg": rx.color("accent", 3)},
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
            rx.icon(tag="snowflake", size=22, color=rx.color("accent", 9)),
            rx.text("firnline", size="4", weight="bold", color=rx.color("accent", 9)),
            spacing="2",
            align="center",
            padding_x="3",
            padding_y="4",
        ),
        rx.divider(),
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
            padding_x="2",
            width="100%",
        ),
        rx.spacer(),
        # Bottom: color mode toggle (sidebar)
        rx.hstack(
            rx.icon_button(
                rx.icon(tag="sun_moon", size=16),
                on_click=rx.toggle_color_mode,
                variant="ghost",
                color_scheme="gray",
                size="1",
            ),
            padding_x="3",
            padding_y="2",
        ),
        height="100vh",
        width=SIDEBAR_WIDTH,
        position="fixed",
        left="0",
        top="0",
        border_right=f"1px solid {rx.color('gray', 5)}",
        background=rx.color("gray", 1),
        z_index="40",
        spacing="1",
    )


def page_header(title: str) -> rx.Component:
    """Top header bar with page title, env badge, logout button, and color-mode toggle."""
    return rx.hstack(
        rx.heading(title, size="5"),
        rx.spacer(),
        # Logout button — only visible when auth is enabled
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
        rx.badge(
            rx.text(
                f"{BaseState.org}/{BaseState.db}@{BaseState.branch}",
                size="1",
            ),
            variant="soft",
            color_scheme="violet",
        ),
        rx.icon_button(
            rx.icon(tag="sun_moon", size=18),
            on_click=rx.toggle_color_mode,
            variant="ghost",
            color_scheme="gray",
        ),
        spacing="3",
        align="center",
        padding_y="3",
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
                    max_width="1100px",
                    padding="4",
                ),
                flex="1",
            ),
            flex="1",
            margin_left=SIDEBAR_WIDTH,
            min_height="100vh",
            spacing="0",
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
