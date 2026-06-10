"""Stores the latest LangSmith run_id per thread_id."""
from __future__ import annotations


class RunStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(self, thread_id: str, run_id: str) -> None:
        self._data[thread_id] = run_id

    def get(self, thread_id: str) -> str | None:
        return self._data.get(thread_id)


default_run_store = RunStore()
