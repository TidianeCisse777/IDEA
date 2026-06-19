"""Resolve the source dataframe to enrich, by name or active session df."""
from __future__ import annotations

import pandas as pd


def resolve_source_dataframe(
    store,
    thread_id: str,
    source_variable: str | None,
) -> pd.DataFrame | None:
    """Return the dataframe to enrich for one thread.

    If `source_variable` is given, search the per-thread dataset registry for
    a named dataset whose `meta.variable_name` matches. Otherwise fall back
    to the active session `df`. Returns `None` when nothing usable is found.
    """
    if source_variable:
        for key in store.keys(f"{thread_id}:dataset:"):
            named = store.get(key)
            if not named:
                continue
            var_name = (named.get("meta") or {}).get("variable_name") or key.rsplit(":", 1)[-1]
            if var_name == source_variable:
                candidate = named.get("df")
                if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                    return candidate
        return None

    session = store.get(thread_id)
    dataframe = session.get("df") if session else None
    return dataframe if isinstance(dataframe, pd.DataFrame) and not dataframe.empty else None
