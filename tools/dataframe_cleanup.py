"""Small session registry for aging automatic derived DataFrames."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.session_store import SessionStore

_STATE_SUFFIX = "dataframe_usage"
_TRANSIENT_SOURCES = {
    "analysis:derived",
    "analysis:join",
    "analysis:graph-plot",
    "analysis:plot_df",
}


def _key(thread_id: str) -> str:
    return f"{thread_id}:{_STATE_SUFFIX}"


def _load(store: SessionStore, thread_id: str) -> dict[str, Any]:
    entry = store.get(_key(thread_id)) or {}
    value = ((entry.get("meta") or {}).get("dataframe_usage"))
    if not isinstance(value, dict):
        return {"turn": 0, "marker": None, "last_used": {}}
    return {
        "turn": int(value.get("turn") or 0),
        "marker": value.get("marker"),
        "last_used": dict(value.get("last_used") or {}),
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


def _delete_family(store: SessionStore, thread_id: str, variable: str) -> None:
    keys = []
    for key in store.keys():
        if key != thread_id and not key.startswith(f"{thread_id}:"):
            continue
        entry = store.get(key) or {}
        if str(((entry.get("meta") or {}).get("variable_name")) or "") == variable:
            keys.append(key)
    canonical = f"{thread_id}:dataset:{variable}"
    for key in sorted(set(keys), key=lambda item: item == canonical):
        store.clear(key)


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
    """Hide automatic derivatives after 3 unused turns and delete after 10."""
    state = _load(store, thread_id)
    if marker != state["marker"]:
        state["turn"] += 1
        state["marker"] = marker
    turn = state["turn"]
    datasets = _datasets(store, thread_id)
    transient = {
        variable
        for _key_name, variable, meta in datasets
        if str(meta.get("source") or "") in _TRANSIENT_SOURCES
    }
    for variable in transient:
        state["last_used"].setdefault(variable, turn)
        if variable in referenced_text:
            state["last_used"][variable] = turn

    stale = {
        variable
        for variable in transient
        if turn - int(state["last_used"].get(variable, turn)) >= 3
    }
    protected = _visible_lineage_parents(datasets, stale)
    for variable in protected & stale:
        state["last_used"][variable] = turn
    hidden = {
        variable
        for variable in transient
        if turn - int(state["last_used"].get(variable, turn)) >= 3
    }
    _reanchor_if_needed(store, thread_id, hidden, datasets)
    for variable in tuple(hidden):
        if turn - int(state["last_used"].get(variable, turn)) >= 10:
            _delete_family(store, thread_id, variable)
            state["last_used"].pop(variable, None)
            hidden.remove(variable)
    _save(store, thread_id, state)
    return hidden


def touch_dataframes(store: SessionStore, thread_id: str, text: str) -> None:
    state = _load(store, thread_id)
    changed = False
    for variable in state["last_used"]:
        if variable in text:
            state["last_used"][variable] = state["turn"]
            changed = True
    if changed:
        _save(store, thread_id, state)


def hidden_dataframes(store: SessionStore, thread_id: str) -> set[str]:
    state = _load(store, thread_id)
    turn = state["turn"]
    return {
        variable
        for variable, last_used in state["last_used"].items()
        if turn - int(last_used) >= 3
    }
