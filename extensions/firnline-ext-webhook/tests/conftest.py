"""Shared fixtures for firnline-ext-webhook tests."""

from __future__ import annotations

import pytest


_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _mock_dns_resolution(monkeypatch):
    """Mock _resolve_addrs to return a public IP so tests don't hit real DNS."""
    from firnline_ext_webhook import executor as exec_mod

    async def fake_resolve(hostname: str, port: int):
        return [(2, 1, 6, "", (_PUBLIC_IP, port))]

    monkeypatch.setattr(exec_mod, "_resolve_addrs", fake_resolve)
