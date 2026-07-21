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
        "Table principale — une ligne par sample EcoTaxa. "
        "Colonnes clés : sample_id, project_id, lat_avg, lon_avg, iho_zone, "
        "instrument, date_min, date_max, depth_min, depth_max, "
        "object_count, nb_validated, nb_predicted, nb_dubious, nb_unclassified, "
        "used_taxa (JSON), original_id, station_id, profile_id. "
        "Point d'entrée pour toute exploration géographique, temporelle, ou par instrument."
    ),
    "projects_cache": (
        "Référentiel projet — une ligne par projet EcoTaxa synced. "
        "Colonnes : project_id, title, instrument, description, status, contact_name, "
        "objcount, pctvalidated, pctclassified, last_synced. "
        "JOIN avec samples_cache ON project_id pour enrichir n'importe quelle requête "
        "avec le nom du projet, l'instrument, le responsable scientifique et les stats de validation. "
        "title et instrument sont toujours renseignés ; description/status/contact_name "
        "sont populés au sync live (peuvent être NULL sur des caches locaux)."
    ),
    "objects_cache": (
        "Index optionnel des objets EcoTaxa — une ligne par objet. "
        "Colonnes : object_id, sample_id, project_id, original_id, object_date, "
        "depth_min, depth_max, taxon, classification_status, latitude, longitude. "
        "Utilisé pour les agrégations par taxon, statut ou profondeur. "
        "Présent uniquement dans les caches enrichis (fat-cache)."
    ),
    "project_schemas_cache": (
        "Snapshot JSON technique des schémas d'export EcoTaxa par projet. "
        "Colonnes : project_id, schema_json, last_synced. "
        "schema_json contient la liste des champs sample/acquisition/object disponibles "
        "pour un export. Usage : inspect_ecotaxa_project_schema ou compare_ecotaxa_projects. "
        "Pour les métadonnées projet (titre, stats), utiliser projects_cache à la place."
    ),
    "project_signatures_cache": (
        "Table interne de détection de changement — une ligne par projet. "
        "Colonnes : project_id, objcount, pctvalidated, pctclassified, last_synced. "
        "Utilisée par le sync pour détecter si un projet a évolué depuis le dernier sync. "
        "Pour les requêtes sur les stats de validation, préférer projects_cache "
        "qui contient les mêmes champs plus title, instrument et description."
    ),
    "sync_runs": (
        "Historique des synchronisations du cache — une ligne par run. "
        "Colonnes : run_id, started_at, ended_at, status, projects_synced, "
        "samples_synced, error_message. "
        "Utile pour diagnostiquer la fraîcheur du cache et l'historique des syncs."
    ),
}

TABLE_GRAINS: dict[str, str] = {
    "samples_cache": "Une ligne par sample EcoTaxa (`sample_id`).",
    "projects_cache": "Une ligne par projet EcoTaxa (`project_id`).",
    "objects_cache": "Une ligne par objet EcoTaxa (`object_id`).",
    "project_schemas_cache": "Une ligne par projet EcoTaxa (`project_id`) — schéma d'export JSON.",
    "project_signatures_cache": "Une ligne par projet EcoTaxa (`project_id`) — usage interne sync.",
    "sync_runs": "Une ligne par exécution de synchronisation (`run_id`).",
}

LOGICAL_RELATIONS: dict[str, list[dict[str, str]]] = {
    "samples_cache": [
        {
            "from_column": "project_id",
            "to_table": "projects_cache",
            "to_column": "project_id",
            "kind": "logical",
        },
        {
            "from_column": "project_id",
            "to_table": "project_schemas_cache",
            "to_column": "project_id",
            "kind": "logical",
        },
    ],
    "objects_cache": [
        {
            "from_column": "sample_id",
            "to_table": "samples_cache",
            "to_column": "sample_id",
            "kind": "logical",
        },
        {
            "from_column": "project_id",
            "to_table": "projects_cache",
            "to_column": "project_id",
            "kind": "logical",
        },
    ],
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_names(conn: sqlite3.Connection) -> list[str]:
    names = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        )
    ]
    order = {name: index for index, name in enumerate(CACHE_TABLES)}
    return sorted(names, key=lambda name: (order.get(name, len(order)), name))


def _columns(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    table = _quote_identifier(table_name)
    return [
        {
            "cid": int(row[0]),
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        }
        for row in conn.execute(f"PRAGMA table_info({table})")
    ]


def _indexes(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    table = _quote_identifier(table_name)
    result = []
    for row in conn.execute(f"PRAGMA index_list({table})"):
        name = str(row[1])
        index = _quote_identifier(name)
        result.append(
            {
                "seq": int(row[0]),
                "name": name,
                "unique": bool(row[2]),
                "origin": row[3],
                "columns": [item[2] for item in conn.execute(f"PRAGMA index_info({index})")],
            }
        )
    return result


def _relations(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    table = _quote_identifier(table_name)
    declared = [
        {
            "from_column": row[3],
            "to_table": row[2],
            "to_column": row[4],
            "kind": "foreign_key",
        }
        for row in conn.execute(f"PRAGMA foreign_key_list({table})")
    ]
    existing_tables = set(_table_names(conn))
    logical = [
        relation
        for relation in LOGICAL_RELATIONS.get(table_name, [])
        if relation["to_table"] in existing_tables
    ]
    return [*declared, *logical]


def list_tables(conn: sqlite3.Connection) -> list[dict]:
    """Return a complete map of every non-internal table actually present."""
    result = []
    for name in _table_names(conn):
        try:
            table = _quote_identifier(name)
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            count = None
        result.append(
            {
                "table": name,
                "rows": count,
                "description": CACHE_TABLES.get(
                    name,
                    "Table d'extension locale présente dans ce cache.",
                ),
                "grain": TABLE_GRAINS.get(name, "Grain non documenté."),
                "columns": _columns(conn, name),
                "indexes": _indexes(conn, name),
                "relations": _relations(conn, name),
            }
        )
    return result


def describe_table(conn: sqlite3.Connection, table_name: str) -> dict:
    """Return column definitions and indexes for one table.

    Returns ``{"ok": False, "error": ...}`` for unknown table names.
    """
    available = _table_names(conn)
    if table_name not in available:
        return {
            "ok": False,
            "error": (
                f"Table inconnue : {table_name!r}. "
                f"Tables disponibles : {available}"
            ),
        }
    return {
        "ok": True,
        "table": table_name,
        "description": CACHE_TABLES.get(
            table_name,
            "Table d'extension locale présente dans ce cache.",
        ),
        "grain": TABLE_GRAINS.get(table_name, "Grain non documenté."),
        "columns": _columns(conn, table_name),
        "indexes": _indexes(conn, table_name),
        "relations": _relations(conn, table_name),
    }


def run_select(
    conn: sqlite3.Connection,
    sql: str,
    cap: int | None = _HARD_CAP,
) -> dict:
    """Execute a read-only SELECT and return structured result.

    Enforces SELECT/CTE-only and no statement chaining. ``cap`` limits rows only
    when supplied. ``None`` fetches the complete result set; this is used by
    the agent path so display limits cannot silently discard data. The MCP
    path keeps its defensive default of 500 rows.
    Returns ``{"ok": False, "error": ...}`` on validation failure or SQL error.
    """
    stripped = (sql or "").strip()
    tokens = stripped.split()
    first = tokens[0].upper() if tokens else ""
    if first not in {"SELECT", "WITH"}:
        return {
            "ok": False,
            "error": f"Only SELECT or WITH statements are allowed (got {first!r}).",
        }
    if ";" in stripped:
        return {
            "ok": False,
            "error": "Statement chaining (;) is not allowed — use a single SELECT.",
        }

    try:
        conn.execute("PRAGMA query_only=ON")
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
