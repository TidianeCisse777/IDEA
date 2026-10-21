"""Cycle de vie du warehouse Windows portable, sans service système.

Créer le cluster seulement s'il est absent. Ne jamais injecter de données
scientifiques. Les secrets générés restent dans data/local_warehouse/.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
if os.name == 'nt':
    # PostgreSQL's Windows initdb can pass ANSI paths into a UTF-8 bootstrap.
    # The short path keeps accented Windows account names out of that SQL.
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.kernel32.GetShortPathNameW(str(ROOT), buffer, len(buffer)):
        ROOT = Path(buffer.value)
STATE = ROOT / 'data/local_warehouse'
PG = ROOT / 'data/tooling/pgsql/bin'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run_pg(command, *args):
    subprocess.run([str(PG / (command + '.exe')), *map(str, args)],
                   check=True, cwd=ROOT)


def credentials():
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / 'credentials.json'
    if not path.exists():
        path.write_text(json.dumps({key: secrets.token_urlsafe(32)
                                   for key in ('owner', 'reader', 'navigator')}), encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8'))


def initialize_database(conn, passwords):
    from psycopg import sql
    # An existing warehouse is never replayed or overwritten.
    exists = conn.execute("SELECT to_regnamespace('warehouse')").fetchone()[0]
    if not exists:
        with conn.transaction():
            conn.execute('CREATE EXTENSION IF NOT EXISTS postgis')
            for name in ('warehouse_schema_proposal.sql', 'warehouse_metadata_migration.sql',
                         'warehouse_ecopart_migration.sql'):
                conn.execute((ROOT / 'docs' / name).read_text(encoding='utf-8'))
            # The current base DDL already contains FILET zone columns. The
            # historical migration assumes the pre-zone view column order.
            conn.execute('CREATE INDEX IF NOT EXISTS filet_sample_marine_zone_name_idx '
                         'ON warehouse.filet_sample (marine_zone_name)')
    conn.execute('REVOKE ALL ON DATABASE neolab_warehouse FROM PUBLIC')
    conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    for role, key, schemas in (
        ('warehouse_reader', 'reader', ('explore',)),
        ('warehouse_navigator', 'navigator', ('warehouse', 'explore')),
    ):
        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(
                sql.Identifier(role), sql.Literal(passwords[key])))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE neolab_warehouse TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(sql.Identifier(role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='30s'").format(sql.Identifier(role)))
        for schema in schemas:
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))


def start():
    import psycopg
    passwords = credentials()
    cluster = STATE / 'pgdata'
    if not (cluster / 'PG_VERSION').exists():
        password_file = STATE / 'init-password.tmp'
        try:
            password_file.write_text(passwords['owner'], encoding='utf-8')
            run_pg('initdb', '-D', cluster, '-U', 'neolab', '--auth=scram-sha-256',
                   '--encoding=UTF8', '--locale=C', '--pwfile', password_file)
        finally:
            password_file.unlink(missing_ok=True)
    # A sandbox may refuse pg_ctl's process inspection even for a live server.
    # Check the local endpoint first; the authenticated connection below then
    # verifies we can use this instance instead of attempting a duplicate start.
    try:
        with socket.create_connection(('127.0.0.1', 55432), timeout=2):
            running = True
    except OSError:
        running = False
    if not running:
        run_pg('pg_ctl', '-D', cluster, '-l', STATE / 'postgres.log',
               '-o', '-h 127.0.0.1 -p 55432', '-w', 'start')
    options = dict(host='127.0.0.1', port=55432, user='neolab', password=passwords['owner'])
    with psycopg.connect(**options, dbname='postgres', autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='neolab_warehouse'").fetchone():
            conn.execute('CREATE DATABASE neolab_warehouse')
    with psycopg.connect(**options, dbname='neolab_warehouse', autocommit=True) as conn:
        initialize_database(conn, passwords)
        from publish_warehouse_context import publish
        publish(conn)
        print('Warehouse prêt :', conn.execute('SELECT version()').fetchone()[0])
    import urllib.request
    try:
        with urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2):
            print('Interface déjà démarrée : http://127.0.0.1:8090')
            return
    except OSError:
        pass
    env = {**os.environ, 'WAREHOUSE_POSTGRES_HOST': '127.0.0.1',
           'WAREHOUSE_POSTGRES_PORT': '55432', 'WAREHOUSE_POSTGRES_USER': 'warehouse_navigator',
           'WAREHOUSE_POSTGRES_PASSWORD': passwords['navigator'],
           'WAREHOUSE_ZONES_PATH': str(ROOT / 'shared_data/geo/zones_registry.geojson')}
    with (STATE / 'navigator.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app',
                                    '--app-dir', str(ROOT / 'warehouse_navigator'),
                                    '--host', '127.0.0.1', '--port', '8090'],
                                   env=env, stdout=log, stderr=log, creationflags=FLAGS)
    (STATE / 'navigator.pid').write_text(str(process.pid), encoding='ascii')
    print('Interface lancée : http://127.0.0.1:8090 (base vide si aucune restauration).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status'), default='start', nargs='?')
    action = parser.parse_args().action
    if action == 'start':
        start()
    elif action == 'status':
        import psycopg
        with psycopg.connect(host='127.0.0.1', port=55432, dbname='neolab_warehouse',
                             user='warehouse_reader', password=credentials()['reader'], connect_timeout=3) as conn:
            print('Warehouse actif :', conn.execute('SELECT current_database(),current_user').fetchone())
    else:
        pid_file = STATE / 'navigator.pid'
        if pid_file.exists():
            import signal
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
            pid_file.unlink()
        run_pg('pg_ctl', '-D', STATE / 'pgdata', '-m', 'fast', '-w', 'stop')
