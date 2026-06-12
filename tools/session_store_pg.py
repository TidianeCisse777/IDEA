"""SessionStorePG — métadonnées dans PostgreSQL, DataFrames sur volume Docker.

Même interface que SessionStore (duck-typed).
Activé automatiquement si SESSION_STORE_DATABASE_URL est défini.
Utilise SQLAlchemy Core pour la portabilité (psycopg2 ou psycopg3 selon driver).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_key  TEXT PRIMARY KEY,
        storage_path TEXT,
        meta         JSONB NOT NULL DEFAULT '{}',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at   TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS sessions_prefix_idx
        ON sessions (session_key text_pattern_ops)
    """,
]

_UPSERT = text("""
    INSERT INTO sessions (session_key, storage_path, meta, updated_at)
    VALUES (:key, :path, CAST(:meta AS JSONB), NOW())
    ON CONFLICT (session_key) DO UPDATE
      SET storage_path = EXCLUDED.storage_path,
          meta         = EXCLUDED.meta,
          updated_at   = NOW()
""")


class SessionStorePG:
    """PostgreSQL-backed session store. DataFrames persisted as .pkl on disk."""

    def __init__(
        self,
        dsn: str,
        storage_dir: str | Path | None = None,
    ) -> None:
        self._engine = create_engine(dsn, pool_pre_ping=True)
        self._storage_dir = Path(
            storage_dir or os.getenv("SESSION_STORE_DIR", "data/session_store")
        )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}
        self._ensure_schema()

    # ── schema ─────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            for stmt in _DDL:
                conn.execute(text(stmt))

    # ── path helpers ───────────────────────────────────────────────────────────

    def _pkl_path(self, session_key: str) -> Path:
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_key).strip())
        return self._storage_dir / f"{stem}.pkl"

    # ── writes ─────────────────────────────────────────────────────────────────

    def set(self, session_key: str, df: pd.DataFrame | None, meta: dict) -> None:
        storage_path: str | None = None
        if df is not None:
            path = self._pkl_path(session_key)
            df.to_pickle(path)
            storage_path = str(path)
        with self._engine.begin() as conn:
            conn.execute(
                _UPSERT,
                {"key": session_key, "path": storage_path, "meta": json.dumps(meta)},
            )
        self._cache[session_key] = {"df": df, "meta": meta}

    def update_meta(self, session_key: str, meta_updates: dict) -> None:
        session = self.get(session_key) or {"df": None, "meta": {}}
        meta = dict(session.get("meta") or {})
        meta.update(meta_updates)
        self.set(session_key, session.get("df"), meta)

    def clear(self, session_key: str) -> None:
        self._cache.pop(session_key, None)
        with contextlib.suppress(FileNotFoundError):
            self._pkl_path(session_key).unlink()
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM sessions WHERE session_key = :key"),
                {"key": session_key},
            )

    # ── reads ──────────────────────────────────────────────────────────────────

    def get(self, session_key: str) -> dict[str, Any] | None:
        if session_key in self._cache:
            return self._cache[session_key]
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT storage_path, meta FROM sessions WHERE session_key = :key"),
                {"key": session_key},
            ).fetchone()
        if row is None:
            return None
        storage_path, meta_raw = row
        meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw)
        df: pd.DataFrame | None = None
        if storage_path:
            pkl = Path(storage_path)
            if pkl.exists():
                with contextlib.suppress(Exception):
                    df = pd.read_pickle(pkl)
        session = {"df": df, "meta": meta}
        self._cache[session_key] = session
        return session

    def has(self, session_key: str) -> bool:
        if session_key in self._cache:
            return True
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM sessions WHERE session_key = :key"),
                {"key": session_key},
            ).fetchone()
        return row is not None

    def keys(self, prefix: str | None = None) -> list[str]:
        if prefix is not None:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT session_key FROM sessions"
                        " WHERE session_key LIKE :prefix ORDER BY session_key"
                    ),
                    {"prefix": prefix + "%"},
                ).fetchall()
        else:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT session_key FROM sessions ORDER BY session_key")
                ).fetchall()
        return [row[0] for row in rows]
