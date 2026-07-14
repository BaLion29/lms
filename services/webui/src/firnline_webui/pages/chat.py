"""Chat page — AI chat interface powered by queryd."""

from __future__ import annotations

import reflex as rx

from firnline_webui.state.chat import ChatState
from firnline_webui.ui.feedback import error_callout
from firnline_webui.ui.nav import shell


def _message_bubble(msg: rx.Var[dict]) -> rx.Component:
    """Render a single chat message bubble — user right, assistant left."""
    return rx.cond(
        msg["role"] == "user",
        # User message — right-aligned, accent background
        rx.hstack(
            rx.spacer(),
            rx.card(
                rx.text(msg["content"], size="2"),
                max_width="70%",
                background=rx.color("accent", 3),
                size="1",
            ),
            width="100%",
            padding_y="4px",
        ),
        # Assistant message — left-aligned, gray background
        rx.hstack(
            rx.card(
                rx.text(msg["content"], size="2"),
                max_width="70%",
                background=rx.color("gray", 3),
                size="1",
            ),
            rx.spacer(),
            width="100%",
            padding_y="4px",
        ),
    )


def chat_page() -> rx.Component:
    """Chat page with message list and input area."""
    return shell(
        rx.vstack(
            # Header row with Clear button
            rx.hstack(
                rx.heading("Chat", size="6"),
                rx.spacer(),
                rx.cond(
                    ChatState.messages.length() > 0,
                    rx.button(
                        "Clear",
                        variant="ghost",
                        size="1",
                        color_scheme="gray",
                        on_click=ChatState.clear,
                    ),
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            # Error callout
            rx.cond(
                ChatState.error != "",
                error_callout(ChatState.error),
            ),
            # Message list area (scrollable fill)
            rx.scroll_area(
                rx.vstack(
                    rx.cond(
                        ChatState.messages.length() == 0,
                        # Empty state
                        rx.center(
                            rx.vstack(
                                rx.icon(
                                    tag="message_circle",
                                    size=40,
                                    color=rx.color("gray", 8),
                                ),
                                rx.text(
                                    "Ask a question about your data.",
                                    size="2",
                                    color_scheme="gray",
                                ),
                                spacing="3",
                                align="center",
                            ),
                            width="100%",
                            padding_y="80px",
                        ),
                        # Messages
                        rx.foreach(
                            ChatState.messages,
                            _message_bubble,
                        ),
                    ),
                    width="100%",
                    spacing="2",
                ),
                flex="1",
                width="100%",
            ),
            # Input row at the bottom
            rx.hstack(
                rx.text_area(
                    value=ChatState.input_text,
                    on_change=ChatState.set_input,
                    placeholder="Ask about your data…",
                    rows="2",
                    width="100%",
                ),
                rx.button(
                    rx.cond(
                        ChatState.sending,
                        rx.spinner(size="3"),
                        rx.icon(tag="send", size=16),
                    ),
                    on_click=ChatState.send,
                    disabled=ChatState.sending,
                ),
                spacing="3",
                align="end",
                width="100%",
            ),
            spacing="4",
            width="100%",
        ),
        active="chat",
    )
