"""Page contract for WebUI page plugins.

Pages registered via :class:`WebUIPagePlugin` are discovered by the WebUI
service and mounted as reflex pages at their declared route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PageSpec:
    """A page that can be mounted in the WebUI.

    Fields:
        route: URL route, e.g. ``"/calendar"`` or ``"/browse/[class_name]"``.
            Must start with ``"/"``.
        title: Page title. Must be non-empty.
        component: Zero-arg factory returning the page component
            (``rx.Component``; typed as ``Any`` to keep firnline-core free of
            a reflex dependency).
        nav_section: Sidebar section grouping (``None`` = hidden from nav).
        nav_icon: Lucide icon tag (``None`` = no icon).
        nav_order: Sort key within the nav section.
        on_load: Event handler spec passed to the framework's ``add_page``.
    """

    route: str
    title: str
    component: Callable[[], Any]
    nav_section: str | None = None
    nav_icon: str | None = None
    nav_order: int = 100
    on_load: Any | None = None

    def __post_init__(self) -> None:
        if not self.route.startswith("/"):
            raise ValueError(f"route must start with '/': {self.route!r}")
        if not self.title:
            raise ValueError("title must be non-empty")
