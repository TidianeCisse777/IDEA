"""Single pending heavy-operation confirmation per conversation."""

from __future__ import annotations

from typing import Any, Literal

from tools.session_store import SessionStore
from tools.user_turn_scope import current_user_turn_marker

ConfirmationDecision = Literal[
    "allowed",
    "missing",
    "operation_mismatch",
    "plan_mismatch",
    "not_confirmable",
    "fresh_user_confirmation_required",
]

_KEY_SUFFIX = "pending_confirmation"


def _key(thread_id: str) -> str:
    return f"{thread_id}:{_KEY_SUFFIX}"


def record_confirmation_preflight(
    store: SessionStore,
    thread_id: str,
    *,
    operation: str,
    plan: dict[str, Any],
    confirmable: bool,
) -> None:
    """Replace any older pending action with the latest visible preflight."""
    store.set(
        _key(thread_id),
        None,
        {
            "pending_confirmation": {
                "operation": str(operation),
                "plan": dict(plan),
                "preflight_user_turn_marker": current_user_turn_marker(),
                "confirmable": bool(confirmable),
            }
        },
    )


def pending_confirmation(
    store: SessionStore,
    thread_id: str,
) -> dict[str, Any] | None:
    """Return the latest pending confirmation, if one exists."""
    entry = store.get(_key(thread_id)) or {}
    value = (entry.get("meta") or {}).get("pending_confirmation")
    return dict(value) if isinstance(value, dict) else None


def check_confirmation(
    store: SessionStore,
    thread_id: str,
    *,
    operation: str,
    plan: dict[str, Any],
) -> ConfirmationDecision:
    """Validate operation, exact plan and a later user turn."""
    pending = pending_confirmation(store, thread_id)
    if pending is None:
        return "missing"
    if pending.get("operation") != operation:
        return "operation_mismatch"
    if pending.get("plan") != plan:
        return "plan_mismatch"
    if not pending.get("confirmable"):
        return "not_confirmable"
    preflight_turn = pending.get("preflight_user_turn_marker")
    confirmation_turn = current_user_turn_marker()
    if (
        not preflight_turn
        or not confirmation_turn
        or preflight_turn == confirmation_turn
    ):
        return "fresh_user_confirmation_required"
    return "allowed"


def clear_confirmation(store: SessionStore, thread_id: str) -> None:
    """Consume the pending action before its heavy operation starts."""
    store.clear(_key(thread_id))
