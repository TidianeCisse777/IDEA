"""Persistent on-disk cache for ERDDAP fetches.

SQLite-backed key/value store. Used by `tools/bio_oracle_sources.py` and
`tools/amundsen_sources.py` to avoid re-fetching the same point/bbox across
sessions. Bio-ORACLE climatology is essentially static; Amundsen bbox responses
are stable as well for a given (bbox, time_window, variables, pres_range) key.

Cross-process safe: each connection acquires a file lock before any read or
write. Required because the cache is shared between the warmup script (host),
the agent (container), and any ad-hoc python scripts — concurrent SQLite
writes without coordination corrupt the database header.

Cache path: env `ERDDAP_CACHE_PATH`, default `data/erddap_cache.sqlite`.
Disable globally: set env `ERDDAP_CACHE_DISABLED=1`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from filelock import FileLock

_DEFAULT_PATH = Path("data/erddap_cache.sqlite")
_lock = threading.Lock()
_initialized: dict[Path, bool] = {}


def _file_lock(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock", timeout=60)


def cache_path() -> Path:
    raw = os.environ.get("ERDDAP_CACHE_PATH")
    return Path(raw) if raw else _DEFAULT_PATH


def cache_disabled() -> bool:
    return os.environ.get("ERDDAP_CACHE_DISABLED", "").lower() in ("1", "true", "yes", "on")


def _ensure_schema(path: Path) -> None:
    if _initialized.get(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "namespace TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "value BLOB NOT NULL, "
                "ts REAL NOT NULL, "
                "PRIMARY KEY (namespace, key))"
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
        finally:
            conn.close()
    _initialized[path] = True


def _hash_key(key: Any) -> str:
    if isinstance(key, str):
        return hashlib.sha256(key.encode()).hexdigest()
    payload = json.dumps(key, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def cache_get(namespace: str, key: Any) -> Any:
    """Return cached value for (namespace, key) or `None` if missing/disabled."""
    if cache_disabled():
        return None
    path = cache_path()
    _ensure_schema(path)
    digest = _hash_key(key)
    with _lock, _file_lock(path):
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            row = conn.execute(
                "SELECT value FROM cache WHERE namespace=? AND key=?",
                (namespace, digest),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    try:
        return pickle.loads(row[0])
    except Exception:
        return None


def cache_set(namespace: str, key: Any, value: Any) -> None:
    """Write `value` to cache under (namespace, key). No-op if disabled."""
    if cache_disabled():
        return
    path = cache_path()
    _ensure_schema(path)
    digest = _hash_key(key)
    blob = pickle.dumps(value)
    with _lock, _file_lock(path):
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache (namespace, key, value, ts) "
                "VALUES (?, ?, ?, ?)",
                (namespace, digest, blob, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def cache_clear(namespace: str | None = None) -> None:
    """Drop all entries (or one namespace). Test/admin helper."""
    path = cache_path()
    if not path.exists():
        return
    _ensure_schema(path)
    with _lock, _file_lock(path):
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            if namespace is None:
                conn.execute("DELETE FROM cache")
            else:
                conn.execute("DELETE FROM cache WHERE namespace=?", (namespace,))
            conn.commit()
        finally:
            conn.close()
