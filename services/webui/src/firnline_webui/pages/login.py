"""Login page — centered password-gate card."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.auth import AuthState
from firnline_webui.ui.nav import wordmark
from firnline_webui.ui.theme import LOGIN_BG, RADIUS_MEDIUM, SHADOW_RAISED, SPACE_3


def login_page() -> rx.Component:
    """Centered login card with wordmark, password input, and error callout.

    Pressing Enter in the password field submits the form.
    """
    return rx.center(
        rx.card(
            rx.vstack(
                # Wordmark
                rx.center(
                    wordmark(size=24),
                    width="100%",
                ),
                rx.divider(),
                rx.text("Sign in", size="5", weight="bold"),
                # Login form (submits on Enter)
                rx.form.root(
                    rx.vstack(
                        rx.input(
                            type="password",
                            value=AuthState.password_input,
                            on_change=AuthState.set_password_input,
                            placeholder="Password",
                            width="100%",
                            auto_focus=True,
                            size="3",
                        ),
                        rx.button(
                            "Log in",
                            type="submit",
                            width="100%",
                            size="3",
                            disabled=(AuthState.password_input == ""),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    on_submit=AuthState.login,
                    reset_on_submit=False,
                    width="100%",
                ),
                # Error callout
                rx.cond(
                    AuthState.error != "",
                    rx.callout(
                        rx.hstack(
                            rx.icon(tag="triangle_alert", size=14, color=rx.color("red", 9)),
                            rx.text(AuthState.error, size="2"),
                            align="center",
                            spacing="2",
                        ),
                        color_scheme="red",
                        size="1",
                        width="100%",
                    ),
                ),
                spacing="5",
                width="100%",
                padding=SPACE_3,
            ),
            size="3",
            max_width="380px",
            width="100%",
            box_shadow=SHADOW_RAISED,
            border_radius=RADIUS_MEDIUM,
            border=f"1px solid {rx.color('gray', 4)}",
        ),
        min_height="100vh",
        width="100%",
        background=LOGIN_BG,
    )
