"""Bind tool execution to the HumanMessage that opened the current turn."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from langchain_core.messages import HumanMessage

_USER_TURN_MARKER: ContextVar[str | None] = ContextVar(
    "idea_user_turn_marker",
    default=None,
)


def user_turn_marker(messages: list[object]) -> str | None:
    """Return a stable marker for the latest user turn in a message sequence."""
    humans = [message for message in messages if isinstance(message, HumanMessage)]
    if not humans:
        return None
    latest = humans[-1]
    return str(getattr(latest, "id", None) or f"human-{len(humans)}")


@contextmanager
def bind_user_turn(marker: str | None) -> Iterator[None]:
    """Expose one user-turn marker only while its tool call is executing."""
    token = _USER_TURN_MARKER.set(marker)
    try:
        yield
    finally:
        _USER_TURN_MARKER.reset(token)


def current_user_turn_marker() -> str | None:
    """Return the marker bound by the agent middleware for this tool call."""
    return _USER_TURN_MARKER.get()
