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
from sqlalchemy import create_engine, inspect, text

from tools.public_url import download_url
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.session_store import default_store as _store

_SQL_DATABASE_URL_META_KEY = "sql_database_url"

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


def _sqlite_database_overview(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT name, type
        FROM sqlite_master
        WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()

    overview: list[dict[str, object]] = []
    for name, object_type in rows:
        quoted = _quote_sql_identifier(name)
        columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
        primary_key = [row[1] for row in columns if row[5]]
        foreign_key_rows = conn.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
        foreign_keys = [
            f"{row[3]} -> {row[2]}.{row[4]}"
            for row in foreign_key_rows
            if row[3] and row[2] and row[4]
        ]

        row_count: int | str = "?"
        if object_type == "table":
            with contextlib.suppress(Exception):
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                row_count = int(row[0] if row else 0)

        overview.append(
            {
                "schema": "main",
                "name": name,
                "type": object_type,
                "columns": len(columns),
                "rows": row_count,
                "primary_key": ", ".join(primary_key) if primary_key else "-",
                "foreign_keys": "; ".join(foreign_keys) if foreign_keys else "-",
            }
        )

    return overview


def _sqlalchemy_database_overview(conn) -> list[dict[str, object]]:
    inspector = inspect(conn)
    schemas = [
        schema
        for schema in inspector.get_schema_names()
        if schema not in {"information_schema", "pg_catalog"}
    ]

    overview: list[dict[str, object]] = []
    for schema in sorted(schemas):
        objects = [
            (name, "table") for name in inspector.get_table_names(schema=schema)
        ] + [
            (name, "view") for name in inspector.get_view_names(schema=schema)
        ]
        for name, object_type in sorted(objects, key=lambda item: (item[1], item[0])):
            columns = inspector.get_columns(name, schema=schema)
            pk_constraint = inspector.get_pk_constraint(name, schema=schema) or {}
            primary_key = pk_constraint.get("constrained_columns") or []
            foreign_keys: list[str] = []
            for fk in inspector.get_foreign_keys(name, schema=schema):
                constrained = fk.get("constrained_columns") or []
                referred = fk.get("referred_columns") or []
                referred_schema = fk.get("referred_schema") or schema
                referred_table = fk.get("referred_table")
                for local_column, remote_column in zip(constrained, referred):
                    if referred_table and remote_column:
                        foreign_keys.append(
                            f"{local_column} -> {referred_schema}.{referred_table}.{remote_column}"
                        )

            row_count: int | str = "?"
            if object_type == "table":
                qualified = _quote_sql_identifier(f"{schema}.{name}")
                with contextlib.suppress(Exception):
                    row = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).fetchone()
                    row_count = int(row[0] if row else 0)

            overview.append(
                {
                    "schema": schema,
                    "name": name,
                    "type": object_type,
                    "columns": len(columns),
                    "rows": row_count,
                    "primary_key": ", ".join(primary_key) if primary_key else "-",
                    "foreign_keys": "; ".join(foreign_keys) if foreign_keys else "-",
                }
            )

    return overview


def _database_overview(database_url: str) -> list[dict[str, object]]:
    """Retourne une vue compacte des tables, vues, clés et volumes visibles."""
    conn = _open_readonly_connection(database_url)
    try:
        if isinstance(conn, sqlite3.Connection):
            return _sqlite_database_overview(conn)
        return _sqlalchemy_database_overview(conn)
    finally:
        _close_connection(conn)


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _format_database_overview(overview: list[dict[str, object]]) -> str:
    if not overview:
        return "Aucune table ou vue SQL trouvée."

    lines = [
        "| schema | name | type | columns | rows | primary key | foreign keys |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for item in overview:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(item[column])
                for column in (
                    "schema",
                    "name",
                    "type",
                    "columns",
                    "rows",
                    "primary_key",
                    "foreign_keys",
                )
            )
            + " |"
        )
    return "\n".join(lines)


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


def _table_schema(database_url: str, table_name: str) -> list[dict[str, object]]:
    conn = _open_readonly_connection(database_url)
    try:
        if isinstance(conn, sqlite3.Connection):
            quoted = _quote_sql_identifier(table_name)
            rows = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            return [
                {
                    "column": row[1],
                    "type": row[2] or "—",
                    "nullable": "no" if row[3] else "yes",
                    "pk": "yes" if row[5] else "no",
                }
                for row in rows
            ]

        inspector = inspect(conn)
        columns = inspector.get_columns(table_name)
        return [
            {
                "column": column["name"],
                "type": str(column.get("type") or "—"),
                "nullable": "yes" if column.get("nullable", True) else "no",
                "pk": "yes" if column.get("primary_key") else "no",
            }
            for column in columns
        ]
    finally:
        _close_connection(conn)


def _table_row_count(database_url: str, table_name: str) -> int:
    conn = _open_readonly_connection(database_url)
    try:
        if isinstance(conn, sqlite3.Connection):
            quoted = _quote_sql_identifier(table_name)
            row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
            return int(row[0] if row else 0)

        quoted = _quote_sql_identifier(table_name)
        row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
        return int(row[0] if row else 0)
    finally:
        _close_connection(conn)


def list_sql_tables(database_url: str) -> list[str]:
    """Retourne les tables visibles dans la base SQL en lecture seule."""
    return _list_sql_tables(database_url)


def extract_sql_workspace_database_url(text: str) -> str | None:
    """Extrait un DATABASE_URL d'un message de configuration Open WebUI."""
    text = (text or "").strip()
    if not text:
        return None

    patterns = [
        r"(?im)^\s*DATABASE_URL\s*[:=]\s*(\S+)\s*$",
        r"(?im)^\s*sql_database_url\s*[:=]\s*(\S+)\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1).strip()

    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*://\S+", text):
        return text
    return None


def set_sql_workspace_database_url(thread_id: str, database_url: str) -> None:
    """Persiste DATABASE_URL dans la métadonnée de session du thread."""
    _store.update_meta(thread_id, {_SQL_DATABASE_URL_META_KEY: database_url.strip()})


def resolve_sql_database_url(thread_id: str) -> str:
    """Résout DATABASE_URL depuis la session du thread, puis l'environnement."""
    session = _store.get(thread_id) or {}
    meta = session.get("meta") or {}
    database_url = str(meta.get(_SQL_DATABASE_URL_META_KEY, "")).strip()
    if database_url:
        return database_url

    env_database_url = os.getenv("DATABASE_URL", "").strip()
    if env_database_url:
        return env_database_url

    raise ValueError(
        "DATABASE_URL is required for SQL tools. Paste the SQLAlchemy URL in the conversation or set it in the local .env."
    )


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

    total_rows = _table_row_count(database_url, table_name)
    schema = _table_schema(database_url, table_name)

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

    if schema:
        schema_lines = ["| column | type | nullable | pk |", "|---|---|---|---|"]
        schema_lines.extend(
            f"| {col['column']} | {col['type']} | {col['nullable']} | {col['pk']} |"
            for col in schema
        )
        schema_block = "\n".join(schema_lines)
    else:
        schema_block = "Aucune colonne trouvée."

    return (
        f"Table `{table_name}`\n"
        f"Row count: {total_rows}\n"
        f"Preview limit: {limit}\n\n"
        f"## Columns\n\n"
        f"{schema_block}\n\n"
        f"## Preview\n\n"
        f"{preview}\n\n"
        f"{len(dataframe)} lignes × {len(dataframe.columns)} colonnes"
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
    database_url = resolve_sql_database_url(thread_id)

    workspace_root = Path(os.getenv("SQL_WORKSPACE_DIR", "data/sql_workspace"))
    workspace_root.mkdir(parents=True, exist_ok=True)

    @tool
    def list_sql_tables() -> str:
        """Cartographie les tables et vues visibles sur le serveur SQL en lecture seule."""
        try:
            overview = _database_overview(database_url)
        except Exception as exc:
            return f"Erreur : {type(exc).__name__}: {exc}"
        return _format_database_overview(overview)

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
            variable_name = dataset_variable_name("sql", output_path.stem)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={"source": "sql_workspace", "n_rows": len(dataframe), "path": str(output_path)},
            )
            return (
                f"Copie SQL créée — {len(dataframe)} lignes, {len(dataframe.columns)} colonnes.\n"
                f"Données disponibles dans `{variable_name}`.\n"
                f"Télécharger : {download_url(output_path.name)}"
            )
        except Exception as exc:
            return f"Erreur : {type(exc).__name__}: {exc}"

    return [list_sql_tables, _preview_sql_table, _copy_sql_query_to_workspace]
