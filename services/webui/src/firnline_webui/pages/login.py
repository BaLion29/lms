"""Login page — centered password-gate card."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.auth import AuthState


def login_page() -> rx.Component:
    """Centered login card with wordmark, password input, and error callout.

    Pressing Enter in the password field submits the form.
    """
    return rx.center(
        rx.card(
            rx.vstack(
                # Wordmark
                rx.hstack(
                    rx.icon(tag="snowflake", size=22, color=rx.color("accent", 9)),
                    rx.text("firnline", size="4", weight="bold", color=rx.color("accent", 9)),
                    spacing="2",
                    align="center",
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
                        ),
                        rx.button(
                            "Log in",
                            type="submit",
                            width="100%",
                            color_scheme="violet",
                            disabled=rx.cond(
                                AuthState.password_input == "", True, False  # type: ignore[arg-type]
                            ),
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
                            rx.icon(tag="triangle_alert", size=14, color="var(--red-9)"),
                            rx.text(AuthState.error, size="2"),
                            align="center",
                            spacing="2",
                        ),
                        color_scheme="red",
                        size="1",
                        width="100%",
                    ),
                ),
                spacing="4",
                width="100%",
                padding="2",
            ),
            size="3",
            max_width="380px",
            width="100%",
        ),
        min_height="100vh",
        width="100%",
    )
