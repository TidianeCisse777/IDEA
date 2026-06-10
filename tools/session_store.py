"""SessionStore — cycle de vie des DataFrames par thread."""
from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd


class SessionStore:
    """Stocke les DataFrames et métadonnées par thread_id.

    Le contenu reste en mémoire pour l'accès rapide, mais est aussi
    persistant sur disque pour survivre aux redémarrages du process.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._storage_dir = Path(storage_dir or os.getenv("SESSION_STORE_DIR", "data/session_store"))
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _safe_thread_id(self, thread_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(thread_id).strip())
        return cleaned or "thread"

    def _data_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._safe_thread_id(thread_id)}.pkl"

    def _meta_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._safe_thread_id(thread_id)}.json"

    def _persist(self, thread_id: str, df: pd.DataFrame | None, meta: dict) -> None:
        data_path = self._data_path(thread_id)
        if df is not None:
            df.to_pickle(data_path)
        self._meta_path(thread_id).write_text(
            json.dumps(meta, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_disk(self, thread_id: str) -> dict[str, Any] | None:
        data_path = self._data_path(thread_id)
        meta_path = self._meta_path(thread_id)
        if not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            df = pd.read_pickle(data_path) if data_path.exists() else None
        except Exception:
            return None

        session = {"df": df, "meta": meta}
        self._store[thread_id] = session
        return session

    def set(self, thread_id: str, df: pd.DataFrame | None, meta: dict) -> None:
        session = {"df": df, "meta": meta}
        self._store[thread_id] = session
        self._persist(thread_id, df, meta)

    def update_meta(self, thread_id: str, meta_updates: dict) -> None:
        session = self.get(thread_id) or {"df": None, "meta": {}}
        meta = dict(session.get("meta") or {})
        meta.update(meta_updates)
        self.set(thread_id, session.get("df"), meta)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        session = self._store.get(thread_id)
        if session is not None:
            return session
        return self._load_from_disk(thread_id)

    def clear(self, thread_id: str) -> None:
        self._store.pop(thread_id, None)
        with contextlib.suppress(FileNotFoundError):
            self._data_path(thread_id).unlink()
        with contextlib.suppress(FileNotFoundError):
            self._meta_path(thread_id).unlink()

    def has(self, thread_id: str) -> bool:
        return thread_id in self._store or self._data_path(thread_id).exists()


default_store = SessionStore()
