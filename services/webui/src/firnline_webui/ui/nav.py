"""Shell layout — sidebar + header + content area.

Navigation items are built dynamically from the page registry
(``firnline_webui.plugin_host.get_page_specs``) so that external
``WebUIPagePlugin`` contributions appear in the sidebar automatically.
"""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.auth import AuthState
from firnline_webui.state.base import BaseState
from firnline_webui.ui.theme import (
    CONTENT_MAX_WIDTH,
    DRAWER_WIDTH,
    HEADER_BG,
    OVERLAY_BG,
    PAGE_BG,
    SIDEBAR_WIDTH,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    SPACE_6,
    SPACE_8,
)
from firnline_webui.ui.typography import card_title

# ---------------------------------------------------------------------------
# Brand wordmark — firn-line glyph + "firnline" text
# ---------------------------------------------------------------------------

_FIRN_MARK_SVG: str = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'style="display:block;width:100%;height:100%">'
    '<polygon points="3,20 12,4 21,20"/>'
    '<line x1="5.5" y1="11" x2="18.5" y2="11"/>'
    "</svg>"
)


def firn_mark(size: int = 24) -> rx.Component:
    """Firnline brand glyph only — SVG mountain icon without text.

    The SVG glyph uses ``stroke="currentColor"``, inheriting from the
    wrapping box's ``color`` set to ``accent-9`` for consistent rendering
    in both light and dark themes.
    """
    return rx.box(
        rx.html(_FIRN_MARK_SVG),
        color=rx.color("accent", 9),
        width=f"{size}px",
        height=f"{size}px",
        flex_shrink="0",
    )


def wordmark(size: int = 20) -> rx.Component:
    """Firnline brand mark: the firn-line glyph + wordmark text.

    The SVG glyph uses ``stroke="currentColor"``, inheriting from the
    wrapping box's ``color`` set to ``accent-9`` for consistent rendering
    in both light and dark themes.
    """
    return rx.hstack(
        firn_mark(size=size),
        rx.text(
            "firnline",
            size="3",
            weight="medium",
            letter_spacing="-0.01em",
        ),
        spacing="2",
        align="center",
    )


# ---------------------------------------------------------------------------
# Dynamic navigation items from the plugin registry
# ---------------------------------------------------------------------------


def _nav_items() -> list[dict]:
    """Return nav items from the plugin registry, sorted by section + order.

    Items with ``nav_section=None`` are excluded from navigation.
    """
    from firnline_webui.plugin_host import get_page_specs  # noqa: PLC0415

    items: list[dict] = []
    for spec in get_page_specs():
        if spec.nav_section is None:
            continue
        # Derive the active key from the route (matching what pages pass
        # to shell()).  "/" → "home", "/capture" → "capture", etc.
        active_key = spec.route.strip("/") or "home"
        items.append({
            "label": _nav_label(active_key),
            "icon": spec.nav_icon or "dot",
            "active": active_key,
            "route": spec.route,
            "nav_section": spec.nav_section,
            "nav_order": spec.nav_order,
        })

    # Sort by section first, then by nav_order within each section
    items.sort(key=lambda it: (it["nav_section"], it["nav_order"]))
    return items


def _nav_label(active_key: str) -> str:
    """Return the display label for a nav item given its active key.

    Falls back to the PageSpec title, then to the title-cased active key.
    """
    if active_key in _PAGE_TITLES:
        return _PAGE_TITLES[active_key]
    ps_title = _page_spec_titles().get(active_key)
    if ps_title:
        return ps_title
    return active_key.replace("_", " ").title()


_PAGE_TITLES: dict[str, str] = {
    "home": "Dashboard",
    "capture": "Capture",
    "inbox": "Inbox",
    "browse": "Browse",
    "calendar": "Calendar",
    "automations": "Automations",
    "health": "Service Health",
    "modules": "Schema Modules",
    "history": "History",
}


def _page_spec_titles() -> dict[str, str]:
    """Return ``{route_stem: title}`` from the PageSpec registry.

    The route stem is derived by stripping leading/trailing slashes
    (e.g. ``/time`` → ``time``, ``/`` → ``home``).
    PageSpec titles that match the hardcoded ``_PAGE_TITLES`` dict are
    excluded so the overrides always take priority.
    """
    from firnline_webui.plugin_host import get_page_specs  # noqa: PLC0415

    titles: dict[str, str] = {}
    for spec in get_page_specs():
        key = spec.route.strip("/") or "home"
        if key not in titles:
            titles[key] = spec.title
    return titles


# ---------------------------------------------------------------------------
# Mobile nav state & link components
# ---------------------------------------------------------------------------


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
            rx.text(
                label,
                size="2",
                weight=rx.cond(is_active, "medium", "regular"),
            ),
            spacing="2",
            align="center",
            padding_x=SPACE_3,
            padding_y=SPACE_2,
            border_radius="medium",
            bg=rx.cond(is_active, rx.color("accent", 3), "transparent"),
            color=rx.cond(is_active, rx.color("accent", 11), rx.color("gray", 11)),
            _hover={"bg": rx.color("gray", 3)},
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

    Items are grouped by nav_section and rendered with section labels.
    """
    items = _nav_items()
    sections: list[tuple[str, list[dict]]] = []
    current_section: str | None = None
    for item in items:
        sec = item["nav_section"]
        if sec != current_section:
            current_section = sec
            sections.append((sec, [item]))
        else:
            sections[-1][1].append(item)

    children: list[rx.Component] = []
    for sec_label, sec_items in sections:
        # Section heading
        children.append(
            rx.text(
                sec_label,
                size="1",
                weight="medium",
                color=rx.color("gray", 9),
                letter_spacing="0.08em",
                text_transform="uppercase",
                padding_x=SPACE_4,
                padding_top=SPACE_3,
                padding_bottom="2px",
            )
        )
        for item in sec_items:
            children.append(
                _nav_link(
                    item["icon"],
                    item["label"],
                    item["route"],
                    item["active"] == active,
                    on_click=on_navigate,
                )
            )

    return rx.vstack(
        *children,
        spacing="1",
        padding_x=SPACE_2,
        width="100%",
    )


# ---------------------------------------------------------------------------
# Sidebar (desktop)
# ---------------------------------------------------------------------------


def sidebar(active: str) -> rx.Component:
    """Fixed left sidebar — hidden on small screens (visible >= md)."""
    return rx.vstack(
        # Wordmark
        rx.box(
            wordmark(),
            padding_x=SPACE_4,
            padding_y=SPACE_3,
        ),
        rx.divider(),
        # Nav links with automatic section labels
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
            padding_x=SPACE_4,
            padding_y=SPACE_2,
            width="100%",
        ),
        height="100vh",
        width=SIDEBAR_WIDTH,
        position="fixed",
        left="0",
        top="0",
        background=rx.color("gray", 2),
        border_right=f"1px solid {rx.color('gray', 4)}",
        z_index="40",
        spacing="1",
        display=rx.breakpoints({"initial": "none", "md": "flex"}),
    )


# ---------------------------------------------------------------------------
# Mobile drawer
# ---------------------------------------------------------------------------


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
                background=OVERLAY_BG,
                display=rx.breakpoints({"initial": "block", "md": "none"}),
            ),
            # Slide-in panel from the left
            rx.vstack(
                rx.hstack(
                    wordmark(),
                    rx.spacer(),
                    rx.icon_button(
                        rx.icon(tag="x", size=16),
                        on_click=MobileNavState.close_drawer,
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        custom_attrs={"aria-label": "Close navigation menu"},
                    ),
                    padding_x=SPACE_4,
                    padding_y=SPACE_3,
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
                    padding_x=SPACE_4,
                    padding_y=SPACE_2,
                    width="100%",
                ),
                position="fixed",
                top="0",
                left="0",
                height="100vh",
                width=DRAWER_WIDTH,
                background=rx.color("gray", 2),
                overflow_y="auto",
                z_index="60",
                spacing="1",
                display=rx.breakpoints({"initial": "flex", "md": "none"}),
                custom_attrs={"role": "dialog", "aria-modal": "true", "aria-label": "Navigation"},
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Page header & shell
# ---------------------------------------------------------------------------


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
        wordmark(),
        rx.divider(orientation="vertical", height="20px"),
        card_title(title),
        rx.spacer(),
        rx.badge(
            rx.text(
                f"{BaseState.org}/{BaseState.db}@{BaseState.branch}",
                size="1",
            ),
            variant="surface",
            color_scheme="gray",
        ),
        spacing="3",
        align="center",
        padding_x=rx.breakpoints({"initial": SPACE_4, "md": SPACE_6}),
        padding_y=SPACE_3,
        position="sticky",
        top="0",
        z_index="30",
        background=HEADER_BG,
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
                    max_width=CONTENT_MAX_WIDTH,
                    padding=SPACE_8,
                    custom_attrs={"role": "main"},
                ),
                flex="1",
            ),
            flex="1",
            margin_left=rx.breakpoints({"initial": "0", "md": SIDEBAR_WIDTH}),
            min_height="100vh",
            spacing="0",
            background=PAGE_BG,
        ),
    )


def _page_title_for(active: str) -> str:
    """Return the page heading given an active nav key.

    Uses the same override → PageSpec → fallback chain as :func:`_nav_label`,
    but falls back to ``"Firnline"`` instead of a title-cased key.
    """
    if active in _PAGE_TITLES:
        return _PAGE_TITLES[active]
    ps_title = _page_spec_titles().get(active)
    if ps_title:
        return ps_title
    return "Firnline"
