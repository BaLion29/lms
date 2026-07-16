"""Screen contract for TUI screen plugins.

Screens registered via :class:`TuiScreenPlugin` are discovered by the TUI
service and installed as Textual screens under their declared screen_id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

_ID_RE = r"^[a-z][a-z0-9_-]*$"


@dataclass(frozen=True)
class ScreenSpec:
    """A screen that can be installed in the TUI.

    Fields:
        screen_id: Unique identifier (slug regex ^[a-z][a-z0-9_-]*$).
        title: Human title shown in the header and nav. Non-empty.
        screen_factory: Zero-arg factory returning the screen instance
            (typed Any to keep firnline-core textual-free).
        nav_section: Sidebar section grouping (None = hidden from nav).
        nav_icon: Short glyph string (1-2 chars, e.g. "◉").
        nav_order: Sort key within the nav section.
        key: Optional single-character global hotkey.
    """

    screen_id: str
    title: str
    screen_factory: Callable[[], Any]
    nav_section: str | None = None
    nav_icon: str | None = None
    nav_order: int = 100
    key: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(_ID_RE, self.screen_id):
            raise ValueError(f"screen_id must match {_ID_RE}: {self.screen_id!r}")
        if not self.title:
            raise ValueError("title must be non-empty")
        if self.key is not None and len(self.key) != 1:
            raise ValueError(f"key must be a single character: {self.key!r}")
