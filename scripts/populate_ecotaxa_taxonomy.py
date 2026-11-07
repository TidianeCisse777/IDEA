#!/usr/bin/env python3
"""Charge la taxonomie EcoTaxa des catégories présentes dans le warehouse.

Pour chaque catégorie d'objet chargée (warehouse.ecotaxa_object.category_id),
lit dans EcoTaxa son nom, son type (P phylogénétique, M morphologique : part,
dead, eggs...), son rang, son AphiaID WoRMS et sa lignée jusqu'à la racine
(GET /taxon_set/query?ids=..., public, sans identifiants), et l'écrit dans
warehouse.ecotaxa_taxon. Recalcule ensuite les comptes par sample et taxon
(warehouse.refresh_ecotaxa_sample_taxon) pour les samples dont les totaux ne
correspondent plus à leurs compteurs.

Sans option, seules les catégories absentes de la table sont lues; --all relit
tout (un taxon renommé ou déplacé dans l'arbre EcoTaxa).

    python scripts/populate_ecotaxa_taxonomy.py
    python scripts/populate_ecotaxa_taxonomy.py --all

Connexion : WAREHOUSE_DATABASE_URL, ou WAREHOUSE_POSTGRES_* (comme les autres
chargeurs), lues dans l'environnement ou .env.warehouse.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

import requests

BASE = 'https://ecotaxa.obs-vlfr.fr/api'
BATCH = 200
ROOT = Path(__file__).resolve().parents[1]


def default_database() -> str:
    if os.getenv('WAREHOUSE_DATABASE_URL'):
        return os.environ['WAREHOUSE_DATABASE_URL']
    if os.getenv('WAREHOUSE_POSTGRES_PASSWORD'):
        os.environ.setdefault('PGPASSWORD', os.environ['WAREHOUSE_POSTGRES_PASSWORD'])
    return 'host=%s port=%s dbname=%s user=%s' % (
        os.getenv('WAREHOUSE_POSTGRES_HOST', 'localhost'), os.getenv('WAREHOUSE_POSTGRES_PORT', '55432'),
        os.getenv('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'), os.getenv('WAREHOUSE_POSTGRES_USER', 'neolab'))


def psql(db: str, sql, stdin: str | None = None) -> str:
    # A list runs as successive -c in one session: psql refuses COPY FROM STDIN inside one multi-statement -c.
    commands = [part for item in ([sql] if isinstance(sql, str) else sql) for part in ('-c', item)]
    result = subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-At', db, *commands],
                            input=stdin, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def taxon_row(taxon: dict, source_uri: str) -> dict:
    """One EcoTaxa TaxonModel as a warehouse.ecotaxa_taxon row; refuses an incomplete answer."""
    lineage, id_lineage = taxon.get('lineage'), taxon.get('id_lineage')
    if not taxon.get('id') or not taxon.get('name') or not lineage or not id_lineage \
            or len(lineage) != len(id_lineage) or id_lineage[0] != taxon['id']:
        raise ValueError('réponse EcoTaxa incomplète pour le taxon %r' % taxon.get('id'))
    return {'taxon_id': taxon['id'], 'taxon_name': taxon['name'], 'display_name': taxon.get('display_name'),
            'taxon_type': taxon.get('type'), 'taxon_status': taxon.get('status'), 'taxon_rank': taxon.get('rank'),
            'aphia_id': taxon.get('aphia_id'), 'lineage': lineage, 'id_lineage': id_lineage, 'source_uri': source_uri}


def fetch(ids: list[int], session=None) -> list[dict]:
    session = session or requests.Session()
    rows = []
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        uri = '%s/taxon_set/query?ids=%s' % (BASE, ','.join(map(str, batch)))
        response = session.get(uri, timeout=60)
        response.raise_for_status()
        found = {t['id']: t for t in response.json()}
        missing = sorted(set(batch) - set(found))
        if missing:
            raise ValueError('EcoTaxa ne connaît pas les taxons %s' % missing[:10])
        rows += [taxon_row(found[i], '%s/taxon_set/query?ids=%d' % (BASE, i)) for i in batch]
    return rows



def store(db: str, rows: list[dict]) -> None:
    # The JSON goes through a temporary table loaded by COPY: no value is ever spliced into SQL.
    payload = json.dumps(rows, ensure_ascii=False)
    psql(db, ['BEGIN', 'CREATE TEMP TABLE taxon_json (doc text) ON COMMIT DROP',
              "COPY taxon_json FROM STDIN WITH (FORMAT csv, QUOTE E'\\x01', DELIMITER E'\\x02')",
              'INSERT INTO warehouse.ecotaxa_taxon (taxon_id, taxon_name, display_name, taxon_type, taxon_status, '
              'taxon_rank, aphia_id, lineage, id_lineage, source_uri, fetched_at) '
              'SELECT r.taxon_id, r.taxon_name, r.display_name, r.taxon_type, r.taxon_status, r.taxon_rank, '
              'r.aphia_id, r.lineage, r.id_lineage, r.source_uri, now() '
              'FROM taxon_json j, json_to_recordset(j.doc::json) AS r(taxon_id integer, taxon_name text, '
              'display_name text, taxon_type text, taxon_status text, taxon_rank text, aphia_id integer, '
              'lineage text[], id_lineage integer[], source_uri text) '
              'ON CONFLICT (taxon_id) DO UPDATE SET taxon_name = EXCLUDED.taxon_name, '
              'display_name = EXCLUDED.display_name, taxon_type = EXCLUDED.taxon_type, '
              'taxon_status = EXCLUDED.taxon_status, taxon_rank = EXCLUDED.taxon_rank, '
              'aphia_id = EXCLUDED.aphia_id, lineage = EXCLUDED.lineage, id_lineage = EXCLUDED.id_lineage, '
              'source_uri = EXCLUDED.source_uri, fetched_at = EXCLUDED.fetched_at', 'COMMIT'],
         stdin=payload + '\n')


def load_taxonomy(db: str, everything: bool = False, session=None) -> tuple[int, int]:
    """Fetch the missing (or all) categories, then refresh the per-sample counts."""
    refreshed = int(psql(db, 'SELECT warehouse.refresh_ecotaxa_sample_taxon()').strip())
    where = '' if everything else ' AND NOT EXISTS (SELECT 1 FROM warehouse.ecotaxa_taxon t WHERE t.taxon_id = s.taxon_id)'
    ids = [int(x) for x in psql(db, 'SELECT DISTINCT taxon_id FROM warehouse.ecotaxa_sample_taxon s '
                                    'WHERE taxon_id IS NOT NULL' + where + ' ORDER BY 1').split()]
    if ids:
        store(db, fetch(ids, session))
    return len(ids), refreshed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--all', action='store_true', help='relire toutes les catégories, pas seulement les nouvelles')
    parser.add_argument('--database-url')
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env.warehouse')
    taxa, samples = load_taxonomy(args.database_url or default_database(), args.all)
    print('[taxonomie] %d catégorie(s) lue(s) dans EcoTaxa; %d sample(s) recompté(s) par taxon.' % (taxa, samples))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
