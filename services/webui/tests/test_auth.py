"""Tests for the authentication gate (pure helpers and shell integration)."""

from __future__ import annotations

from firnline_webui.state.auth import session_token


# ── session_token pure-function tests ──


def test_session_token_empty_password():
    """session_token returns empty string when password is empty."""
    assert session_token("") == ""


def test_session_token_non_empty():
    """session_token returns a hex HMAC-SHA256 when password is set."""
    tok = session_token("hunter2")
    assert isinstance(tok, str)
    assert len(tok) == 64  # SHA-256 hex digest
    assert all(c in "0123456789abcdef" for c in tok)


def test_session_token_deterministic():
    """Same password always produces the same token."""
    t1 = session_token("secret123")
    t2 = session_token("secret123")
    assert t1 == t2


def test_session_token_different_passwords():
    """Different passwords produce different tokens."""
    t1 = session_token("alpha")
    t2 = session_token("beta")
    assert t1 != t2


# ── Settings-driven auth_enabled logic ──


def test_auth_disabled_by_default():
    """When WEBUI_PASSWORD is unset, auth_enabled is False."""
    from firnline_webui.settings import Settings

    s = Settings()
    assert s.password == ""
    assert not bool(s.password)


def test_auth_enabled_when_password_set(monkeypatch):
    """When WEBUI_PASSWORD is set, auth_enabled is True."""
    monkeypatch.setenv("WEBUI_PASSWORD", "secret")
    from firnline_webui.settings import Settings

    s = Settings()
    assert s.password == "secret"
    assert bool(s.password)


# ── App shell: login route ──


def test_login_route_registered():
    """The /login page is registered with correct title."""
    from firnline_webui.firnline_webui import app

    page = app._unevaluated_pages["login"]
    assert page.title == "Firnline — Sign in"


def test_login_page_compiles():
    """The login page function must evaluate without error."""
    from firnline_webui.firnline_webui import app

    page = app._unevaluated_pages["login"]
    comp = page.component()
    assert comp is not None


def test_app_still_imports_and_compiles():
    """Full smoke-test: app imports, all pages compile (from test_shell)."""
    from firnline_webui.firnline_webui import app

    for _key, page in app._unevaluated_pages.items():
        assert page.component() is not None
