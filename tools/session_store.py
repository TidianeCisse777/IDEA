"""SessionStore — cycle de vie des DataFrames par thread."""
from typing import Any
import pandas as pd


class SessionStore:
    """Stocke les DataFrames et métadonnées par thread_id."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def set(self, thread_id: str, df: pd.DataFrame, meta: dict) -> None:
        self._store[thread_id] = {"df": df, "meta": meta}

    def get(self, thread_id: str) -> dict[str, Any] | None:
        return self._store.get(thread_id)

    def clear(self, thread_id: str) -> None:
        self._store.pop(thread_id, None)

    def has(self, thread_id: str) -> bool:
        return thread_id in self._store


default_store = SessionStore()
