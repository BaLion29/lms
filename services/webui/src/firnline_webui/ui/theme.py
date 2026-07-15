"""Design tokens shared across the webui — spacing, shadows, colours, row styles.

All tokens are plain module-level constants.  Import from ``firnline_webui.ui.theme``.
"""

from __future__ import annotations

import reflex as rx

# ---------------------------------------------------------------------------
# Geometry / layout
# ---------------------------------------------------------------------------

SIDEBAR_WIDTH = "240px"
DRAWER_WIDTH = "260px"
CONTENT_MAX_WIDTH = "1200px"

# ---------------------------------------------------------------------------
# Radius
# ---------------------------------------------------------------------------

RADIUS_MEDIUM = "6px"

# ---------------------------------------------------------------------------
# Spacing scale
# ---------------------------------------------------------------------------

SPACE_1 = "4px"
SPACE_1_5 = "6px"
SPACE_2 = "8px"
SPACE_3 = "12px"
SPACE_4 = "16px"
SPACE_6 = "24px"
SPACE_8 = "32px"

# Vertical padding for centred empty / loading states.
SPACING_EMPTY_STATE_Y = "64px"

# Monospace font stack for IDs, IRIs, and code-like values.
FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"

# Warm accent reserved for the single primary action per screen ("alpenglow");
# apply locally via color_scheme, never in the global theme.
WARM_ACCENT = "tomato"

# ---------------------------------------------------------------------------
# Calendar event palette
# ---------------------------------------------------------------------------

EVENT_PALETTE = [
    rx.color("cyan", 9),
    rx.color("orange", 9),
    rx.color("green", 9),
    rx.color("purple", 9),
    rx.color("pink", 9),
    rx.color("blue", 9),
    rx.color("amber", 9),
    rx.color("teal", 9),
]

# ---------------------------------------------------------------------------
# Dark-mode-safe shadows (color-mix on --gray-12 so they adapt to theme)
# ---------------------------------------------------------------------------

SHADOW_CARD = (
    "0 1px 2px color-mix(in srgb, black 4%, transparent),"
    " 0 1px 3px color-mix(in srgb, black 6%, transparent)"
)

SHADOW_RAISED = (
    "0 4px 12px color-mix(in srgb, black 8%, transparent),"
    " 0 12px 32px color-mix(in srgb, black 6%, transparent)"
)

# ---------------------------------------------------------------------------
# Overlay / backdrop
# ---------------------------------------------------------------------------

# Semi-transparent black — always dims regardless of theme.
OVERLAY_BG = "color-mix(in srgb, black 50%, transparent)"

# ---------------------------------------------------------------------------
# Shell backgrounds
# ---------------------------------------------------------------------------

# Semi-translucent header background (adapts to light/dark via gray-1).
HEADER_BG = rx.color("gray", 1)

# Subtle page background gradient — gray-1 fading to gray-2.
PAGE_BG = rx.color("gray", 1)

# Login-page background — flat gray-1.
LOGIN_BG = rx.color("gray", 1)

# ---------------------------------------------------------------------------
# Shared table-row pseudo-props
# ---------------------------------------------------------------------------

TABLE_ROW_STYLE: dict = {
    "_hover": {"bg": rx.color("accent", 2)},
    "_odd": {"background": rx.color("gray", 2)},
}
