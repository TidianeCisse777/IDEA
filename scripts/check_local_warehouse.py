"""Recette SQL réelle des privilèges locaux; aucun secret imprimé."""
import json
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
passwords = json.loads((ROOT / 'data/local_warehouse/credentials.json').read_text())
for role, key, raw_allowed in (
    ('warehouse_reader', 'reader', False),
    ('warehouse_navigator', 'navigator', True),
):
    with psycopg.connect(host='127.0.0.1', port=55432, dbname='neolab_warehouse',
                         user=role, password=passwords[key], autocommit=True) as conn:
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        assert conn.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                            "FROM pg_roles WHERE rolname=current_user").fetchone() == (False,) * 5
        assert conn.execute("SELECT has_database_privilege(current_user,current_database(),'CREATE'),"
                            "has_database_privilege(current_user,current_database(),'TEMP')").fetchone() == (False, False)
        assert not conn.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]
        assert conn.execute("SELECT has_schema_privilege(current_user,'warehouse','USAGE')").fetchone()[0] == raw_allowed
        assert not conn.execute("SELECT has_table_privilege(current_user,c.oid,'INSERT') "
                                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "WHERE n.nspname='warehouse' AND c.relname='dataset_version'").fetchone()[0]
        conn.execute('SELECT * FROM explore.uvp_projects LIMIT 1')
        assert conn.execute('SELECT count(*) FROM explore.warehouse_context').fetchone()[0] == 21
        assert conn.execute('SELECT count(*) FROM explore.warehouse_dictionary '
                            'WHERE column_description IS NULL OR view_description IS NULL').fetchone()[0] == 0
        conn.execute('SELECT * FROM explore.dataset_versions LIMIT 1')
        try:
            conn.execute('SELECT * FROM warehouse.dataset_version LIMIT 1')
            assert raw_allowed, 'Le lecteur MCP ne doit pas lire les tables brutes'
        except psycopg.errors.InsufficientPrivilege:
            assert not raw_allowed
        meters = conn.execute("SELECT ST_Distance('SRID=4326;POINT(0 0)'::geography,"
                              "'SRID=4326;POINT(1 0)'::geography)").fetchone()[0]
        assert 111_319 < meters < 111_320
        print('PASS :', role, 'droits minimaux et distance PostGIS vérifiés.')
