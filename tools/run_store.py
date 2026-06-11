"""Stores the latest LangSmith run_id per thread_id, message_id, and chat_id.

Persisted to disk so run_ids survive server restarts.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path
from typing import NamedTuple


class _RunEntry(NamedTuple):
    ts: float
    run_id: str
    thread_id: str
    chat_id: str | None


_DEFAULT_PATH = Path(os.getenv("RUN_STORE_PATH", "logs/feedback/run_store.json"))


class RunStore:
    def __init__(self, max_history: int = 200, persist_path: Path | None = None) -> None:
        self._data: dict[str, str] = {}
        self._message_data: dict[str, str] = {}
        self._chat_data: dict[str, str] = {}
        self._history: deque[_RunEntry] = deque(maxlen=max_history)
        self._path = persist_path

    # ── persistence ────────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = raw.get("data", {})
            self._message_data = raw.get("message_data", {})
            self._chat_data = raw.get("chat_data", {})
            for e in raw.get("history", []):
                self._history.append(_RunEntry(**e))
        except Exception:
            pass

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "data": self._data,
                "message_data": self._message_data,
                "chat_data": self._chat_data,
                "history": [e._asdict() for e in self._history],
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            pass

    # ── writes ─────────────────────────────────────────────────────────────────

    def set(self, thread_id: str, run_id: str, *, chat_id: str | None = None) -> None:
        self._data[thread_id] = run_id
        if chat_id:
            self._chat_data[chat_id] = run_id
        self._history.append(_RunEntry(ts=time.time(), run_id=run_id, thread_id=thread_id, chat_id=chat_id))
        self._save()

    def set_for_message(self, message_id: str, run_id: str) -> None:
        self._message_data[message_id] = run_id
        self._save()

    # ── reads ──────────────────────────────────────────────────────────────────

    def get(self, thread_id: str) -> str | None:
        return self._data.get(thread_id)

    def get_for_message(self, message_id: str) -> str | None:
        return self._message_data.get(message_id)

    def get_for_chat_id(self, chat_id: str) -> str | None:
        return self._chat_data.get(chat_id)

    def get_nearest_before(self, vote_ts: float, max_age_seconds: float = 3600) -> str | None:
        best: _RunEntry | None = None
        for entry in self._history:
            if entry.ts <= vote_ts and (vote_ts - entry.ts) <= max_age_seconds:
                if best is None or entry.ts > best.ts:
                    best = entry
        return best.run_id if best else None

    def get_most_recent(self, max_age_seconds: float = 3600) -> str | None:
        now = time.time()
        for entry in reversed(self._history):
            if (now - entry.ts) <= max_age_seconds:
                return entry.run_id
        return None


default_run_store = RunStore(persist_path=_DEFAULT_PATH)
default_run_store.load()
