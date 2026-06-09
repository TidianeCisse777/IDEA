"""Workspace SQL en lecture seule pour l'agent copépodes."""
from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

import pandas as pd
from langchain_core.tools import tool
from sqlalchemy import create_engine, inspect

from tools.public_url import download_url
from tools.session_store import default_store as _store

def _sqlite_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError("Only sqlite:// URLs are supported in this slice.")
    path = unquote(parsed.path or "")
    if path.startswith("//"):
        path = path[1:]
    if not path:
        raise ValueError("sqlite DATABASE_URL must include a file path.")
    return Path(path)


def _open_readonly_connection(database_url: str):
    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        path = _sqlite_path_from_url(database_url)
        uri = f"file:{path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    engine = create_engine(
        database_url,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    conn = engine.connect()
    conn._sql_workspace_engine = engine  # type: ignore[attr-defined]
    return conn


def _close_connection(conn) -> None:
    engine = getattr(conn, "_sql_workspace_engine", None)
    with contextlib.suppress(Exception):
        conn.close()
    if engine is not None:
        with contextlib.suppress(Exception):
            engine.dispose()


def _list_sql_tables(database_url: str) -> list[str]:
    """Retourne les tables visibles dans la base SQL en lecture seule."""
    conn = _open_readonly_connection(database_url)
    try:
        if isinstance(conn, sqlite3.Connection):
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            return [row[0] for row in rows]

        inspector = inspect(conn)
        return sorted(inspector.get_table_names())
    finally:
        _close_connection(conn)


def _quote_sql_identifier(identifier: str) -> str:
    parts = [part.strip() for part in identifier.split(".") if part.strip()]
    if not parts:
        raise ValueError("table_name must not be empty.")

    quoted_parts: list[str] = []
    for part in parts:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            raise ValueError(
                "table_name must be a simple SQL identifier or schema-qualified name."
            )
        quoted_parts.append(f'"{part}"')
    return ".".join(quoted_parts)


def list_sql_tables(database_url: str) -> list[str]:
    """Retourne les tables visibles dans la base SQL en lecture seule."""
    return _list_sql_tables(database_url)


def preview_sql_table(
    database_url: str,
    table_name: str,
    limit: int = 10,
) -> str:
    """Retourne un aperçu read-only d'une table SQL pour inspection rapide."""
    if limit < 1:
        raise ValueError("limit must be >= 1.")

    available_tables = set(_list_sql_tables(database_url))
    if table_name not in available_tables:
        raise ValueError(f"Unknown SQL table: {table_name}")

    conn = _open_readonly_connection(database_url)
    try:
        query = f"SELECT * FROM {_quote_sql_identifier(table_name)} LIMIT {int(limit)}"
        dataframe = pd.read_sql_query(query, conn)
    finally:
        _close_connection(conn)

    if dataframe.empty:
        preview = "Aucune ligne trouvée."
    else:
        preview = dataframe.to_markdown(index=False)

    return (
        f"Table `{table_name}` — {len(dataframe)} lignes × {len(dataframe.columns)} colonnes\n\n"
        f"{preview}"
    )


def copy_sql_query_to_workspace(
    database_url: str,
    query: str,
    workspace_dir: str | Path,
    output_stem: str,
) -> Path:
    """Exécute une requête SQL read-only et matérialise le résultat en TSV local."""
    workspace_path = Path(workspace_dir)
    workspace_path.mkdir(parents=True, exist_ok=True)

    conn = _open_readonly_connection(database_url)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        _close_connection(conn)

    output_path = workspace_path / f"{output_stem}.tsv"
    df.to_csv(output_path, sep="\t", index=False)

    downloads_dir = Path("/tmp/copepod_downloads")
    downloads_dir.mkdir(exist_ok=True)
    download_path = downloads_dir / output_path.name
    df.to_csv(download_path, sep="\t", index=False)

    return output_path


def _default_workspace_stem(thread_id: str, query: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", query.strip()).strip("_")[:32] or "query"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    digest = hashlib.md5(f"{thread_id}:{query}".encode()).hexdigest()[:8]
    return f"{thread_id}_{slug}_{stamp}_{digest}"


def make_sql_tools(thread_id: str) -> list:
    """Crée les tools SQL liés à un workspace de conversation."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for SQL tools.")

    workspace_root = Path(os.getenv("SQL_WORKSPACE_DIR", "data/sql_workspace"))
    workspace_root.mkdir(parents=True, exist_ok=True)

    @tool
    def list_sql_tables() -> str:
        """Liste les tables visibles sur le serveur SQL en lecture seule."""
        try:
            tables = _list_sql_tables(database_url)
        except Exception as exc:
            return f"Erreur : {type(exc).__name__}: {exc}"
        if not tables:
            return "Aucune table SQL trouvée."
        return "\n".join(f"- {table}" for table in tables)

    @tool("preview_sql_table")
    def _preview_sql_table(table_name: str, limit: int = 10) -> str:
        """Aperçu rapide et read-only d'une table SQL avec les premières lignes."""
        try:
            preview = preview_sql_table(
                database_url=database_url,
                table_name=table_name,
                limit=limit,
            )
        except Exception as exc:
            return f"Erreur : {type(exc).__name__}: {exc}"
        return preview

    @tool("copy_sql_query_to_workspace")
    def _copy_sql_query_to_workspace(query: str, output_stem: str | None = None) -> str:
        """Exécute un SELECT read-only et écrit le résultat dans le workspace local."""
        try:
            stem = output_stem or _default_workspace_stem(thread_id, query)
            output_path = copy_sql_query_to_workspace(
                database_url=database_url,
                query=query,
                workspace_dir=workspace_root / thread_id,
                output_stem=stem,
            )
            dataframe = pd.read_csv(output_path, sep="\t")
            _store.set(
                thread_id,
                dataframe,
                {"source": "sql_workspace", "n_rows": len(dataframe), "path": str(output_path)},
            )
            return (
                f"Copie SQL créée — {len(dataframe)} lignes, {len(dataframe.columns)} colonnes.\n"
                f"Télécharger : {download_url(output_path.name)}"
            )
        except Exception as exc:
            return f"Erreur : {type(exc).__name__}: {exc}"

    return [list_sql_tables, _preview_sql_table, _copy_sql_query_to_workspace]
