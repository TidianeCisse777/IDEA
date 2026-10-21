#!/usr/bin/env python3
"""Inspecter la connexion et, sur demande, qualifier les vues scientifiques.

Lecture seule avec le rôle warehouse_reader. Aucun chargement, modification
de métadonnées ou rapprochement taxonomique. Les résultats restent sur stdout;
les erreurs du pilote ne sont jamais imprimées car elles peuvent contenir un DSN.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


UVP_TAXONOMY_SQL = """
SELECT dataset_version_id,
    COUNT(DISTINCT ecotaxa_object_id) AS objects,
    COUNT(DISTINCT ecotaxa_object_id) FILTER
        (WHERE NULLIF(btrim(taxon_id), '') IS NULL) AS missing_taxon_id,
    COUNT(DISTINCT ecotaxa_object_id) FILTER
        (WHERE NULLIF(btrim(taxon_name), '') IS NULL) AS missing_taxon_name,
    COUNT(DISTINCT ecotaxa_object_id) FILTER
        (WHERE NULLIF(btrim(annotation_status), '') IS NULL) AS missing_annotation_status
FROM explore.uvp_objects GROUP BY dataset_version_id ORDER BY dataset_version_id
"""

FILET_TAXONOMY_SQL = """
SELECT dataset_version_id, COUNT(*) AS source_stage_rows,
    COUNT(*) FILTER (WHERE NULLIF(btrim(taxon_id), '') IS NULL) AS missing_taxon_id,
    COUNT(*) FILTER (WHERE NOT metadata_matched) AS unmatched_metadata_rows,
    COUNT(*) FILTER (WHERE NULLIF(btrim(analysis_contract), '') IS NULL)
        AS missing_analysis_contract_rows
FROM explore.filet_data GROUP BY dataset_version_id ORDER BY dataset_version_id
"""


def connection_options() -> dict:
    """Utiliser uniquement les credentials lecteur fournis dans l'environnement."""
    password = os.environ.get("WAREHOUSE_READER_PASSWORD")
    if not password:
        raise ValueError("WAREHOUSE_READER_PASSWORD requis (aucun fallback propriétaire).")
    return dict(
        host=os.getenv("WAREHOUSE_READER_HOST", "127.0.0.1"),
        port=os.getenv("WAREHOUSE_READER_PORT", "55432"),
        dbname=os.getenv("WAREHOUSE_READER_DB", "neolab_warehouse"),
        user="warehouse_reader", password=password, connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
    )


def inspect(conn, qualify: bool = False) -> dict:
    """Inventorier les colonnes accessibles avant tout scan optionnel des objets."""
    columns = conn.execute("""SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema='explore'
        ORDER BY table_name, ordinal_position""").fetchall()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "columns": columns,
        "qualification": "not_requested",
        "scope": "explore uniquement; UVP limité aux objets liés aux profils",
    }
    if qualify:
        available = {row["table_name"] for row in columns}
        missing = sorted({"uvp_objects", "filet_data"} - available)
        if missing:
            report.update(qualification="unavailable", missing_views=[f"explore.{v}" for v in missing])
            return report
        report["uvp_taxonomy"] = conn.execute(UVP_TAXONOMY_SQL).fetchall()
        report["filet_taxonomy"] = conn.execute(FILET_TAXONOMY_SQL).fetchall()
        report["qualification"] = "measured"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualify", action="store_true",
                        help="Scanner les objets et lignes FILET (potentiellement coûteux).")
    args = parser.parse_args()
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(**connection_options(), row_factory=dict_row) as conn:
            report = inspect(conn, qualify=args.qualify)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 2 if report["qualification"] == "unavailable" else 0
    except Exception:
        print("Diagnostic impossible : vérifier le pilote psycopg, les paramètres lecteur, "
              "le service, les permissions, le schéma et le délai de requête.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
