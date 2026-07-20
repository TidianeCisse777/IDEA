"""Read-only SQL exploration over the EcoTaxa SQLite cache.

Shared between the FastMCP server (core/mcp/ecotaxa_server.py) and
the LangChain @tool layer (tools/copepod_sources.py). Pure functions —
no LangChain, no FastMCP imports.
"""

from __future__ import annotations

import sqlite3

_HARD_CAP = 500

# Ordered for presentation: most useful table first.
CACHE_TABLES: dict[str, str] = {
    "samples_cache": (
        "EcoTaxa sample-level positions, date/time envelopes, depth envelopes, "
        "instruments, authoritative sample-stat counts, and metadata completeness. "
        "Table principale pour l'exploration géographique et temporelle."
    ),
    "objects_cache": (
        "Index optionnel des objets EcoTaxa pour les agrégations par taxon, "
        "statut, sample, date ou profondeur. Présent dans les caches enrichis."
    ),
    "project_schemas_cache": (
        "Snapshot JSON des schémas de projets EcoTaxa "
        "(title, instrument, colonnes sample/acquisition/object, free fields). "
        "Interroger schema_json pour voir les champs disponibles par projet."
    ),
    "project_signatures_cache": (
        "Statistiques de classification par projet "
        "(objcount total, pctvalidated, pctclassified). "
        "Mise à jour à chaque sync — bonne mesure de maturité d'annotation."
    ),
    "sync_runs": (
        "Historique des synchronisations du cache "
        "(started_at, ended_at, status, projects_synced, samples_synced, error_message). "
        "Utile pour diagnostiquer la fraîcheur du cache."
    ),
}


def list_tables(conn: sqlite3.Connection) -> list[dict]:
    """Return one row per table with row count and description."""
    result = []
    for name, description in CACHE_TABLES.items():
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        except Exception:
            count = None
        result.append({"table": name, "rows": count, "description": description})
    return result


def describe_table(conn: sqlite3.Connection, table_name: str) -> dict:
    """Return column definitions and indexes for one table.

    Returns ``{"ok": False, "error": ...}`` for unknown table names.
    """
    if table_name not in CACHE_TABLES:
        return {
            "ok": False,
            "error": (
                f"Table inconnue : {table_name!r}. "
                f"Tables disponibles : {list(CACHE_TABLES)}"
            ),
        }
    columns = [
        {
            "cid": int(row[0]),
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        }
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    ]
    indexes = [
        {
            "seq": int(row[0]),
            "name": row[1],
            "unique": bool(row[2]),
            "origin": row[3],
        }
        for row in conn.execute(f"PRAGMA index_list({table_name})")
    ]
    return {
        "ok": True,
        "table": table_name,
        "description": CACHE_TABLES[table_name],
        "columns": columns,
        "indexes": indexes,
    }


def run_select(
    conn: sqlite3.Connection,
    sql: str,
    cap: int | None = _HARD_CAP,
) -> dict:
    """Execute a read-only SELECT and return structured result.

    Enforces SELECT-only and no statement chaining. ``cap`` limits rows only
    when supplied. ``None`` fetches the complete result set; this is used by
    the agent path so display limits cannot silently discard data. The MCP
    path keeps its defensive default of 500 rows.
    Returns ``{"ok": False, "error": ...}`` on validation failure or SQL error.
    """
    stripped = (sql or "").strip()
    tokens = stripped.split()
    first = tokens[0].upper() if tokens else ""
    if first != "SELECT":
        return {
            "ok": False,
            "error": f"Only SELECT statements are allowed (got {first!r}).",
        }
    if ";" in stripped:
        return {
            "ok": False,
            "error": "Statement chaining (;) is not allowed — use a single SELECT.",
        }

    try:
        cur = conn.execute(stripped)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    columns = [desc[0] for desc in (cur.description or [])]
    if cap is None:
        raw_rows = cur.fetchall()
        truncated = False
    else:
        raw_rows = cur.fetchmany(cap + 1)
        truncated = len(raw_rows) > cap
        raw_rows = raw_rows[:cap]
    rows = [dict(zip(columns, row)) for row in raw_rows]

    return {
        "ok": True,
        "columns": columns,
        "rows": rows,
        "count": len(rows),
        "truncated": truncated,
    }
