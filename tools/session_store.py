"""SessionStore — cycle de vie des DataFrames par thread."""
from __future__ import annotations

import contextlib
import hashlib
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

    def _legacy_stem(self, thread_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(thread_id).strip())
        return cleaned or "thread"

    def _safe_thread_id(self, thread_id: str) -> str:
        logical_key = str(thread_id)
        readable_prefix = self._legacy_stem(logical_key)[:48]
        digest = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()
        return f"{readable_prefix}--{digest}"

    def _data_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._safe_thread_id(thread_id)}.pkl"

    def _meta_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._safe_thread_id(thread_id)}.json"

    def _legacy_data_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._legacy_stem(thread_id)}.pkl"

    def _legacy_meta_path(self, thread_id: str) -> Path:
        return self._storage_dir / f"{self._legacy_stem(thread_id)}.json"

    def _persist(self, thread_id: str, df: pd.DataFrame | None, meta: dict) -> None:
        data_path = self._data_path(thread_id)
        if df is not None:
            df.to_pickle(data_path)
        self._meta_path(thread_id).write_text(
            json.dumps({"session_key": thread_id, "meta": meta}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_persisted_entry(
        self,
        thread_id: str,
        data_path: Path,
        meta_path: Path,
    ) -> dict[str, Any] | None:
        try:
            if not meta_path.exists():
                return None
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("session_key") != thread_id:
                return None
            meta = payload["meta"]
            df = pd.read_pickle(data_path) if data_path.exists() else None
        except Exception:
            return None

        return {"df": df, "meta": meta}

    def _remove_matching_legacy_entry(self, thread_id: str) -> None:
        legacy_meta_path = self._legacy_meta_path(thread_id)
        try:
            payload = json.loads(legacy_meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("session_key") != thread_id:
            return
        with contextlib.suppress(FileNotFoundError):
            self._legacy_data_path(thread_id).unlink()
        with contextlib.suppress(FileNotFoundError):
            legacy_meta_path.unlink()

    def _load_from_disk(self, thread_id: str) -> dict[str, Any] | None:
        session = self._read_persisted_entry(
            thread_id,
            self._data_path(thread_id),
            self._meta_path(thread_id),
        )
        if session is None:
            session = self._read_persisted_entry(
                thread_id,
                self._legacy_data_path(thread_id),
                self._legacy_meta_path(thread_id),
            )
            if session is None:
                return None
            self._persist(thread_id, session["df"], session["meta"])
            self._remove_matching_legacy_entry(thread_id)

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

    def keys(self, prefix: str | None = None) -> list[str]:
        """List known session keys, including entries persisted on disk."""
        keys = set(self._store)
        for meta_path in self._storage_dir.glob("*.json"):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            key = payload.get("session_key") if isinstance(payload, dict) else None
            keys.add(str(key or meta_path.stem))
        if prefix is not None:
            keys = {key for key in keys if key.startswith(prefix)}
        return sorted(keys)

    def clear(self, thread_id: str) -> None:
        self._store.pop(thread_id, None)
        with contextlib.suppress(FileNotFoundError):
            self._data_path(thread_id).unlink()
        with contextlib.suppress(FileNotFoundError):
            self._meta_path(thread_id).unlink()
        self._remove_matching_legacy_entry(thread_id)

    def clear_conversation(self, thread_id: str) -> None:
        prefix = f"{thread_id}:"
        family = [
            key for key in self.keys()
            if key == thread_id or key.startswith(prefix)
        ]
        for key in family:
            self.clear(key)

    def has(self, thread_id: str) -> bool:
        if thread_id in self._store or self._data_path(thread_id).exists():
            return True
        legacy_session = self._read_persisted_entry(
            thread_id,
            self._legacy_data_path(thread_id),
            self._legacy_meta_path(thread_id),
        )
        return legacy_session is not None and legacy_session["df"] is not None


def _make_default_store() -> "SessionStore":
    dsn = os.getenv("SESSION_STORE_DATABASE_URL")
    if dsn:
        from tools.session_store_pg import SessionStorePG  # noqa: PLC0415
        return SessionStorePG(dsn)  # type: ignore[return-value]
    return SessionStore()


default_store = _make_default_store()
