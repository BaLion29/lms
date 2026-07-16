"""Entry point for firnline-tui."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from firnline_tui.app import FirnlineApp
from firnline_tui.clients import make_tdb_browser
from firnline_tui.screen_registry import build_screen_registry
from firnline_tui.settings import get_settings

log = logging.getLogger(__name__)


def _mask(value: str) -> str:
    """Mask a secret value, showing only first/last 3 chars."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}…{value[-3:]}"


def _debug_settings() -> None:
    """Print all resolved settings with secrets masked."""
    s = get_settings()
    print("═" * 60)
    print("  firnline-tui — resolved settings")
    print("═" * 60)
    print()
    print("  TerminusDB:")
    print(f"    tdb_url:              {s.tdb_url}")
    print(f"    tdb_org:              {s.tdb_org}")
    print(f"    tdb_db:               {s.tdb_db}")
    print(f"    tdb_branch:           {s.tdb_branch}")
    print(f"    tdb_user:             {s.tdb_user}")
    print(f"    tdb_password:         {_mask(s.tdb_password)}")
    print()
    print("  Capture service:")
    print(f"    captured_url:         {s.captured_url}")
    print(f"    captured_api_token:   {_mask(s.captured_api_token)}")
    print()
    print("  Queryd service:")
    print(f"    queryd_url:           {s.queryd_url}")
    print(f"    queryd_api_token:     {_mask(s.queryd_api_token)}")
    print()
    print("  Indexed service:")
    print(f"    indexed_url:          {s.indexed_url}")
    print(f"    indexed_api_token:    {_mask(s.indexed_api_token)}")
    print()
    print("  MCPd service:")
    print(f"    mcpd_url:             {s.mcpd_url}")
    print()
    print("  Operational:")
    print(f"    request_timeout:      {s.request_timeout_seconds}s")
    print(f"    registry_timeout:     {s.plugin_registry_timeout_seconds}s")
    print(f"    start_screen:         {s.start_screen}")
    print()
    print("═" * 60)


async def _debug_connections() -> None:
    """Try to connect to each service and report success/failure."""
    s = get_settings()
    print("═" * 60)
    print("  firnline-tui — connection test")
    print("═" * 60)
    print()

    # Test TDB
    print("  TerminusDB:")
    tdb = make_tdb_browser()
    try:
        schema = await asyncio.wait_for(tdb.get_schema(), timeout=s.request_timeout_seconds)
        classes = [e for e in schema if e.get("@type") == "Class"]
        print(f"    ✓ Connected — {len(classes)} schema classes found")
    except Exception as exc:
        print(f"    ✗ FAILED: {exc}")
    finally:
        await tdb.aclose()
    print()

    # Test health endpoints
    from firnline_tui.clients import make_health_clients
    c_cap, c_qry, c_idx, c_mcpd = make_health_clients()

    print("  Captured:")
    try:
        data = await asyncio.wait_for(c_cap.healthz(), timeout=s.request_timeout_seconds)
        print(f"    ✓ Connected — status={data.get('status', '?')}")
    except Exception as exc:
        print(f"    ✗ FAILED: {exc}")
    print()

    print("  Queryd:")
    try:
        data = await asyncio.wait_for(c_qry.healthz(), timeout=s.request_timeout_seconds)
        print(f"    ✓ Connected — status={data.get('status', '?')}")
    except Exception as exc:
        print(f"    ✗ FAILED: {exc}")
    print()

    print("  Indexed:")
    try:
        data = await asyncio.wait_for(c_idx.healthz(), timeout=s.request_timeout_seconds)
        print(f"    ✓ Connected — status={data.get('status', '?')}")
    except Exception as exc:
        print(f"    ✗ FAILED: {exc}")
    print()

    print("  MCPd:")
    try:
        data = await asyncio.wait_for(c_mcpd.healthz(), timeout=s.request_timeout_seconds)
        print(f"    ✓ Connected — status={data.get('status', '?')}")
    except Exception as exc:
        print(f"    ✗ FAILED: {exc}")
    print()

    print("═" * 60)


def main() -> None:
    """Build registry and launch the TUI."""
    parser = argparse.ArgumentParser(prog="firnline-tui", description="Firnline terminal UI")
    parser.add_argument(
        "--debug-settings",
        action="store_true",
        help="Print resolved settings (secrets masked) and exit",
    )
    parser.add_argument(
        "--debug-connections",
        action="store_true",
        help="Test connections to all services and exit",
    )
    args = parser.parse_args()

    if args.debug_settings:
        _debug_settings()
        return

    if args.debug_connections:
        asyncio.run(_debug_connections())
        return

    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    settings = get_settings()
    tdb = make_tdb_browser()

    async def _build():
        try:
            return await build_screen_registry(
                tdb,
                timeout=settings.plugin_registry_timeout_seconds,
            )
        finally:
            await tdb.aclose()

    registry = asyncio.run(_build())

    app = FirnlineApp(registry=registry)
    app.run()


if __name__ == "__main__":
    main()
