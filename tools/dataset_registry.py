"""Stable names and persistence for downloaded DataFrames."""
from __future__ import annotations

import re
from numbers import Real

import pandas as pd

from tools.session_store import SessionStore


def _identifier_part(value: object) -> str:
    if isinstance(value, Real) and not isinstance(value, bool):
        number = f"{value:g}"
        if number.startswith("-"):
            number = f"m{number[1:]}"
        text = number
    else:
        text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def dataset_variable_name(source: str, *parts: object) -> str:
    """Return a predictable valid Python variable for one downloaded dataset."""
    tokens = [_identifier_part(source), *(_identifier_part(part) for part in parts)]
    tokens = [token for token in tokens if token]
    return f"df_{'_'.join(tokens)}"


def store_dataset(
    store: SessionStore,
    thread_id: str,
    dataframe: pd.DataFrame,
    *,
    variable_name: str,
    meta: dict,
    latest_alias: str | None = None,
) -> None:
    """Persist a stable dataset and refresh current/latest aliases."""
    dataset_meta = {**meta, "variable_name": variable_name}
    store.set(thread_id, dataframe, dataset_meta)
    if latest_alias:
        store.set(f"{thread_id}:{latest_alias}", dataframe, dataset_meta)
    store.set(f"{thread_id}:dataset:{variable_name}", dataframe, dataset_meta)
