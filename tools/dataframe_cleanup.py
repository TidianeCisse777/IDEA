"""Bound and archive derived DataFrames without deleting durable payloads."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from tools.dataset_registry import DERIVED_DATAFRAME_SOURCES
from tools.session_store import SessionStore

_STATE_SUFFIX = "dataframe_usage"
_TRANSIENT_SOURCES = DERIVED_DATAFRAME_SOURCES
TRANSIENT_HIDE_AFTER_TURNS = 6
DEFAULT_MAX_LIVE_DERIVED_DATAFRAMES = 20


def _key(thread_id: str) -> str:
    return f"{thread_id}:{_STATE_SUFFIX}"


def _load(store: SessionStore, thread_id: str) -> dict[str, Any]:
    entry = store.get(_key(thread_id)) or {}
    value = ((entry.get("meta") or {}).get("dataframe_usage"))
    if not isinstance(value, dict):
        return {
            "turn": 0,
            "marker": None,
            "last_used": {},
            "capacity_hidden": [],
            "hidden": [],
        }
    return {
        "turn": int(value.get("turn") or 0),
        "marker": value.get("marker"),
        "last_used": dict(value.get("last_used") or {}),
        "capacity_hidden": list(value.get("capacity_hidden") or []),
        "hidden": list(value.get("hidden") or []),
    }


def _save(store: SessionStore, thread_id: str, state: dict[str, Any]) -> None:
    store.set(_key(thread_id), None, {"dataframe_usage": state})


def _datasets(
    store: SessionStore,
    thread_id: str,
) -> list[tuple[str, str, dict[str, Any]]]:
    prefix = f"{thread_id}:dataset:"
    datasets = []
    for key in store.keys(prefix):
        entry = store.get(key) or {}
        if not isinstance(entry.get("df"), pd.DataFrame):
            continue
        meta = dict(entry.get("meta") or {})
        variable = str(meta.get("variable_name") or key.removeprefix(prefix))
        datasets.append((key, variable, meta))
    return datasets


def _reanchor_if_needed(
    store: SessionStore,
    thread_id: str,
    hidden: set[str],
    datasets: list[tuple[str, str, dict[str, Any]]],
) -> None:
    active = store.get(thread_id) or {}
    active_name = str(((active.get("meta") or {}).get("variable_name")) or "")
    if active_name not in hidden:
        return
    for key, variable, meta in datasets:
        if variable not in hidden and str(meta.get("source") or "") not in _TRANSIENT_SOURCES:
            store.set_reference(thread_id, key, meta)
            return


def _set_lifecycle_state(
    store: SessionStore,
    key: str,
    *,
    state: str,
    reason: str | None = None,
) -> None:
    """Persist one lifecycle transition without changing the DataFrame payload."""

    entry = store.get(key) or {}
    dataframe = entry.get("df")
    if not isinstance(dataframe, pd.DataFrame):
        return
    meta = dict(entry.get("meta") or {})
    if (
        meta.get("lifecycle_state") == state
        and meta.get("archived_reason") == reason
    ):
        return
    meta["retention_class"] = "derived"
    meta["lifecycle_state"] = state
    if reason:
        meta["archived_reason"] = reason
    else:
        meta.pop("archived_reason", None)
    store.set(key, dataframe, meta)


def _declared_parents(meta: dict[str, Any]) -> tuple[str, ...]:
    """Return exact lineage parents declared by a producing operation."""
    parents: list[str] = []
    for key in ("parent_variable", "parent_variables", "source_variable"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            parents.append(value)
        elif isinstance(value, (list, tuple, set)):
            parents.extend(str(item) for item in value if item)
    return tuple(dict.fromkeys(parents))


def _is_identifier_character(character: str) -> bool:
    return character == "_" or character.isalnum()


def _is_exact_reference(text: str, variable: str) -> bool:
    """Return whether ``variable`` occurs as one complete identifier."""

    start = 0
    while True:
        position = text.find(variable, start)
        if position < 0:
            return False
        before_ok = (
            position == 0
            or not _is_identifier_character(text[position - 1])
        )
        end = position + len(variable)
        after_ok = end == len(text) or not _is_identifier_character(text[end])
        if before_ok and after_ok:
            return True
        start = position + 1


def _max_live_derived_dataframes() -> int:
    try:
        configured = int(
            os.getenv(
                "MAX_LIVE_DERIVED_DATAFRAMES",
                str(DEFAULT_MAX_LIVE_DERIVED_DATAFRAMES),
            )
        )
    except ValueError:
        configured = DEFAULT_MAX_LIVE_DERIVED_DATAFRAMES
    return max(1, configured)


def _visible_lineage_parents(
    datasets: list[tuple[str, str, dict[str, Any]]],
    stale: set[str],
) -> set[str]:
    """Return all ancestors required by a currently visible DataFrame."""
    known = {variable for _key_name, variable, _meta in datasets}
    parents_by_child = {
        variable: tuple(
            parent for parent in _declared_parents(meta) if parent in known
        )
        for _key_name, variable, meta in datasets
    }
    queue = [variable for variable in known if variable not in stale]
    protected: set[str] = set()
    while queue:
        child = queue.pop()
        for parent in parents_by_child.get(child, ()):
            if parent in protected:
                continue
            protected.add(parent)
            queue.append(parent)
    return protected


def advance_dataframe_cleanup(
    store: SessionStore,
    thread_id: str,
    *,
    marker: str,
    referenced_text: str = "",
) -> set[str]:
    """Bound live derivatives, then archive unused ones outside model context.

    At most ``MAX_LIVE_DERIVED_DATAFRAMES`` (20 by default) automatic
    derivatives remain visible to the runtime. Capacity-hidden tables stay in
    ``SessionStore`` and can be revived by an exact user/tool reference. Hidden
    tables are archived in place and never deleted by automatic cleanup.
    Source/file/export/enrichment DataFrames never count toward this capacity.
    """
    state = _load(store, thread_id)
    previously_hidden = set(state.get("hidden") or ())
    if marker != state["marker"]:
        state["turn"] += 1
        state["marker"] = marker
    turn = state["turn"]
    datasets = _datasets(store, thread_id)
    known = {variable for _key_name, variable, _meta in datasets}
    transient = {
        variable
        for _key_name, variable, meta in datasets
        if str(meta.get("source") or "") in _TRANSIENT_SOURCES
    }
    capacity_hidden = {
        variable
        for variable in state.get("capacity_hidden", [])
        if variable in transient
    }
    exact_references = {
        variable
        for variable in known
        if _is_exact_reference(referenced_text, variable)
    }
    for variable in known:
        state["last_used"].setdefault(variable, turn)
        if variable in exact_references:
            state["last_used"][variable] = turn
            capacity_hidden.discard(variable)

    stale = {
        variable
        for variable in transient
        if turn - int(state["last_used"].get(variable, turn))
        >= TRANSIENT_HIDE_AFTER_TURNS
    }
    protected = _visible_lineage_parents(datasets, stale)
    for variable in protected & stale:
        state["last_used"][variable] = turn
    age_hidden = {
        variable
        for variable in transient
        if turn - int(state["last_used"].get(variable, turn))
        >= TRANSIENT_HIDE_AFTER_TURNS
    }
    visible_transient = transient - age_hidden - capacity_hidden
    capacity_protected_parents = (
        _visible_lineage_parents(
            datasets,
            age_hidden | capacity_hidden,
        )
        & visible_transient
    )
    overflow = max(
        0,
        len(visible_transient) - _max_live_derived_dataframes(),
    )
    newly_capacity_hidden: set[str] = set()
    if overflow:
        eviction_order = sorted(
            visible_transient
            - exact_references
            - capacity_protected_parents,
            key=lambda variable: (
                int(state["last_used"].get(variable, turn)),
                variable,
            ),
        )
        # A single request can theoretically name more than the configured
        # capacity. Preserve as many exact current references as possible, but
        # keep the hard bound deterministic if non-referenced candidates do not
        # suffice.
        if len(eviction_order) < overflow:
            eviction_order.extend(
                sorted(
                    (
                        (visible_transient - exact_references)
                        & capacity_protected_parents
                    ),
                    key=lambda variable: (
                        int(state["last_used"].get(variable, turn)),
                        variable,
                    ),
                )
            )
        if len(eviction_order) < overflow:
            eviction_order.extend(
                sorted(
                    exact_references & visible_transient,
                    key=lambda variable: (
                        int(state["last_used"].get(variable, turn)),
                        variable,
                    ),
                )
            )
        newly_capacity_hidden = set(eviction_order[:overflow])
        capacity_hidden.update(newly_capacity_hidden)

    hidden = age_hidden | capacity_hidden
    _reanchor_if_needed(store, thread_id, hidden, datasets)
    for key, variable, meta in datasets:
        if variable not in transient:
            continue
        if variable in hidden:
            reason = "capacity" if variable in capacity_hidden else "unused"
            _set_lifecycle_state(
                store,
                key,
                state="archived",
                reason=reason,
            )
        elif str(meta.get("lifecycle_state") or "current") != "current":
            _set_lifecycle_state(store, key, state="current")
    state["capacity_hidden"] = sorted(capacity_hidden)
    state["hidden"] = sorted(hidden)
    _save(store, thread_id, state)
    if hidden - previously_hidden:
        # The executor is only a hot cache. Closing it is the safest way to
        # guarantee that capacity-hidden intermediates do not remain alive in
        # its Python namespace; durable tables are reloaded on demand.
        try:
            from tools.persistent_executor import default_executor

            default_executor.close(thread_id)
        except Exception:
            pass
    return hidden


def touch_dataframe_names(
    store: SessionStore,
    thread_id: str,
    variable_names: tuple[str, ...] | list[str] | set[str],
) -> None:
    """Refresh exact live variables selected by structured runtime evidence."""

    state = _load(store, thread_id)
    changed = False
    for variable in dict.fromkeys(str(name) for name in variable_names if name):
        if variable in state["last_used"]:
            state["last_used"][variable] = state["turn"]
            changed = True
    if changed:
        _save(store, thread_id, state)


def touch_dataframes(store: SessionStore, thread_id: str, text: str) -> None:
    state = _load(store, thread_id)
    touch_dataframe_names(
        store,
        thread_id,
        [variable for variable in state["last_used"] if variable in text],
    )


def hidden_dataframes(store: SessionStore, thread_id: str) -> set[str]:
    state = _load(store, thread_id)
    turn = state["turn"]
    transient = {
        variable
        for _key_name, variable, meta in _datasets(store, thread_id)
        if str(meta.get("source") or "") in _TRANSIENT_SOURCES
    }
    age_hidden = {
        variable
        for variable, last_used in state["last_used"].items()
        if variable in transient
        and turn - int(last_used) >= TRANSIENT_HIDE_AFTER_TURNS
    }
    capacity_hidden = {
        str(variable)
        for variable in state.get("capacity_hidden", [])
        if str(variable) in transient
    }
    lifecycle_hidden = {
        variable
        for _key_name, variable, meta in _datasets(store, thread_id)
        if variable in transient
        and str(meta.get("lifecycle_state") or "current")
        in {"archived", "superseded"}
    }
    return age_hidden | capacity_hidden | lifecycle_hidden


def dataframe_cleanup_metrics(
    store: SessionStore,
    thread_id: str,
) -> dict[str, int]:
    """Expose stable lifecycle counters for the context/harness audit."""

    state = _load(store, thread_id)
    turn = state["turn"]
    datasets = _datasets(store, thread_id)
    transient = {
        variable
        for _key_name, variable, meta in datasets
        if str(meta.get("source") or "") in _TRANSIENT_SOURCES
    }
    age_hidden = {
        variable
        for variable, last_used in state["last_used"].items()
        if variable in transient
        and turn - int(last_used) >= TRANSIENT_HIDE_AFTER_TURNS
    }
    capacity_hidden = {
        str(variable)
        for variable in state.get("capacity_hidden", [])
        if str(variable) in transient
    }
    lifecycle_hidden = {
        variable
        for _key_name, variable, meta in datasets
        if variable in transient
        and str(meta.get("lifecycle_state") or "current")
        in {"archived", "superseded"}
    }
    hidden = age_hidden | capacity_hidden | lifecycle_hidden
    anchors = {
        variable
        for _key_name, variable, meta in datasets
        if str(meta.get("source") or "") not in _TRANSIENT_SOURCES
    }
    superseded_versions = len(store.keys(f"{thread_id}:archive:dataset:"))
    return {
        "max_live_derived_dataframes": _max_live_derived_dataframes(),
        "dataframes_stored_total": len(datasets) + superseded_versions,
        "dataframe_anchors_total": len(anchors),
        "derived_dataframes_total": len(transient),
        "derived_dataframes_visible": len(transient - hidden),
        "derived_dataframes_hidden": len(hidden),
        "derived_dataframes_archived": len(lifecycle_hidden),
        "derived_versions_superseded": superseded_versions,
        "derived_dataframes_capacity_hidden": len(capacity_hidden),
        "derived_dataframes_age_hidden": len(age_hidden),
    }


def dataframe_usage_ages(
    store: SessionStore,
    thread_id: str,
) -> dict[str, int]:
    """Return non-negative turns since each live DataFrame was referenced."""
    state = _load(store, thread_id)
    turn = state["turn"]
    live = {
        variable for _key_name, variable, _meta in _datasets(store, thread_id)
    }
    return {
        variable: max(0, turn - int(last_used))
        for variable, last_used in state["last_used"].items()
        if variable in live
    }
