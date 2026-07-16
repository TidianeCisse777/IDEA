"""Typed per-turn state reconstruction (harness step 5).

`TurnContext` is the single, typed snapshot of the conversation state the agent
should read at the start of a turn instead of re-inferring it from the message
history: the loaded/active dataset, the live zone-derived subsets, and the
authorized source scope for the turn. It is rebuilt every turn (ephemeral); the
underlying data lives in the session store / checkpoint (persistent).

The rendered `capsule` is the model-facing projection of this context, injected
into the system message by the middleware.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.session_context import (
    _live_zone_subsets,
    build_dataset_state_capsule,
)
from tools.session_store import SessionStore
from tools.source_scope import is_file_loaded, source_decision_for_turn


@dataclass(frozen=True)
class TurnContext:
    """Authoritative, typed state for one conversation turn."""

    thread_id: str
    file_loaded: bool
    active_variable: str | None
    active_source: str | None
    derived_zone_subsets: tuple[tuple[str, str, str], ...]
    authorized_sources: tuple[str, ...]
    primary_source: str | None
    explicit_sources: tuple[str, ...]
    capsule: str


def build_turn_context(
    store: SessionStore,
    thread_id: str,
    messages: object,
    *,
    persist_source: bool = False,
) -> TurnContext:
    """Reconstruct the typed turn state from the store and current messages.

    `persist_source=False` keeps this a pure read; the runtime persists the
    source decision once, in the model-call middleware.
    """
    active = store.get(thread_id)
    has_active = bool(active and active.get("df") is not None)
    meta = (active or {}).get("meta") or {} if has_active else {}
    active_variable = meta.get("variable_name") if has_active else None
    active_source = meta.get("source") if has_active else None

    subsets = tuple(_live_zone_subsets(store, thread_id))

    try:
        decision = source_decision_for_turn(
            store, thread_id, list(messages or []), persist=persist_source
        )
        authorized = decision.authorized_sources
        primary = decision.primary_source
        explicit = decision.explicit_sources
    except Exception:
        authorized, primary, explicit = (), None, ()

    capsule = build_dataset_state_capsule(store, thread_id, messages)

    return TurnContext(
        thread_id=thread_id,
        file_loaded=is_file_loaded(store, thread_id),
        active_variable=active_variable,
        active_source=active_source,
        derived_zone_subsets=subsets,
        authorized_sources=authorized,
        primary_source=primary,
        explicit_sources=explicit,
        capsule=capsule,
    )
