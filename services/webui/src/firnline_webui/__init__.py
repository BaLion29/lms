"""firnline-webui — Reflex-based web UI for the Firnline system."""

from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("firnline-webui")
except PackageNotFoundError:
    __version__ = "0.0.0"
