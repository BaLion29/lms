"""Auth state for password-gated UI access.

Session model: one shared password.  The session token is an HMAC-SHA256
derived from the password — deterministic, so a password change invalidates
all existing cookies.  No user DB, no expiry logic beyond the cookie max_age.
Good enough for a LAN password gate.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import reflex as rx

from firnline_webui.settings import get_settings
from firnline_webui.state.base import BaseState

_settings = get_settings()
_SESSION_MSG = b"firnline-webui-session"


def session_token(password: str) -> str:
    """Derive a deterministic session token from the shared password via HMAC-SHA256.

    Pure helper — testable without Reflex state instantiation.
    Returns the empty string when *password* is empty.
    """
    if not password:
        return ""
    return hmac.new(key=password.encode(), msg=_SESSION_MSG, digestmod=hashlib.sha256).hexdigest()


class AuthState(BaseState):
    """Authentication state — password gate for all pages."""

    # Cookie-based session token (30 day max age)
    token: str = rx.Cookie(name="firnline_webui_session", max_age=60 * 60 * 24 * 30)

    # Login form fields
    password_input: str = ""
    error: str = ""

    @rx.var
    def auth_enabled(self) -> bool:
        """True when WEBUI_PASSWORD is non-empty."""
        return bool(_settings.password)

    @rx.var
    def is_authed(self) -> bool:
        """True when the cookie token matches the expected session value."""
        if not self.auth_enabled:
            return True
        expected = session_token(_settings.password)
        return secrets.compare_digest(self.token, expected)

    @rx.event
    def login(self):
        """Validate the entered password and set the session cookie on success."""
        if not secrets.compare_digest(self.password_input, _settings.password):
            self.error = "Invalid password."
            self.password_input = ""
            return
        self.error = ""
        self.token = session_token(_settings.password)
        self.password_input = ""
        return rx.redirect("/")

    @rx.event
    def logout(self):
        """Clear the session cookie and redirect to the login page."""
        self.token = ""
        self.error = ""
        return rx.redirect("/login")

    @rx.event
    async def check(self):
        """on_load guard: redirect to /login when auth is enabled but not authed.

        Note: when multiple on_load handlers are specified (e.g.
        ``[AuthState.check, DataState.load]``), Reflex 0.9.6 runs *both*.
        The data-loading handler will still execute server-side even when
        ``check`` fires a redirect — this is acceptable because data-loading
        handlers only *read* data and the redirect response takes precedence
        on the wire.
        """
        if self.auth_enabled and not self.is_authed:
            yield rx.redirect("/login")
        yield

    @rx.event
    async def check_login(self):
        """on_load for /login: redirect to / when auth is disabled or already authed."""
        if not self.auth_enabled or self.is_authed:
            yield rx.redirect("/")
        yield

    @rx.event
    def set_password_input(self, value: str):
        """Update the password input field."""
        self.password_input = value
