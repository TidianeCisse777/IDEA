"""
Pure-Python session key helpers — no heavy dependencies.

These functions are imported by app.py so they can also be tested in isolation
without loading the full FastAPI application stack.
"""
from __future__ import annotations

from pathlib import Path


def make_session_key(user_id: "str | int", session_id: str, agent_type: str = "generic") -> str:
    """Return a colon-separated session key: ``{user_id}:{session_id}:{agent_type}``."""
    return f"{user_id}:{session_id}:{agent_type}"


def parse_session_key(session_key: str) -> tuple[str, str, str]:
    """
    Split a session key into its three components.

    Supports both the new 3-segment format ``user_id:session_id:agent_type``
    and the legacy 2-segment format ``user_id:session_id`` (agent_type defaults
    to ``"generic"`` in that case).

    Returns (user_id, session_id, agent_type).
    """
    parts = session_key.split(":")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], "generic"
    raise ValueError(f"Invalid session key format: {session_key!r}")


def session_dir_path(session_key: str, static_dir: Path) -> Path:
    """
    Return the filesystem path for a session's static directory.

    Uses only ``user_id`` and ``session_id`` — the ``agent_type`` segment is
    intentionally ignored so that sessions of different types that share the
    same user+session pair map to the same directory.
    """
    user_id, session_id, _agent_type = parse_session_key(session_key)
    return static_dir / user_id / session_id


def resolve_agent_type(header_value: "str | None", valid_types: "list[str]") -> str:
    """
    Validate *header_value* against *valid_types* and return a safe agent type.

    Returns ``"generic"`` when *header_value* is ``None``, empty, or not in
    *valid_types*.
    """
    if not header_value or header_value not in valid_types:
        return "generic"
    return header_value
