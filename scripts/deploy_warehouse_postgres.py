"""Déployer ou mettre à niveau le warehouse sur n'importe quel PostgreSQL 16+.

Rejouable: un warehouse existant n'est jamais réécrit; seules les migrations
additives (FAIR) et les rôles sont réappliqués. Aucune donnée scientifique
n'est chargée. Les secrets passent par l'environnement, jamais par argv.

    WAREHOUSE_POSTGRES_PASSWORD=... WAREHOUSE_READER_PASSWORD=... \\
    WAREHOUSE_NAVIGATOR_PASSWORD=... python scripts/deploy_warehouse_postgres.py

Connexion: WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD (le rôle propriétaire).
Code de sortie: 0 déployé, 1 erreur, 2 --check avec critères FAIR manquants,
3 --check avec un contournement du contrôle d'accès (prioritaire sur 2).
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
# Order matters: roles come last so they cover every object created above.
FRESH_FILES = ('warehouse_schema_proposal.sql', 'warehouse_metadata_migration.sql',
               'warehouse_ecopart_migration.sql')
ALWAYS_FILES = ('warehouse_ctd_zone_migration.sql', 'warehouse_fair_migration.sql', 'warehouse_access_control.sql')
ROLES_FILE = 'warehouse_roles.sql'


def connection_env():
    env = dict(os.environ)
    env.update(PGHOST=env.get('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
               PGPORT=env.get('WAREHOUSE_POSTGRES_PORT', '55432'),
               PGDATABASE=env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
               PGUSER=env.get('WAREHOUSE_POSTGRES_USER', 'neolab'))
    password = env.get('WAREHOUSE_POSTGRES_PASSWORD')
    if not password:
        raise SystemExit('WAREHOUSE_POSTGRES_PASSWORD est requis (rôle propriétaire).')
    env['PGPASSWORD'] = password
    # The deploying session always writes, whatever defaults the owner role carries.
    env['PGOPTIONS'] = '-c default_transaction_read_only=off -c statement_timeout=0'
    return env


def psql(env, *args, capture=False):
    result = subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', *args],
                            env=env, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def query(env, statement):
    return psql(env, '-At', '-c', statement, capture=True)


def deploy(env, dry_run):
    fresh = query(env, "SELECT to_regnamespace('warehouse') IS NULL") == 't'
    steps = []
    if fresh:
        steps += [(name, True) for name in FRESH_FILES]
    steps += [(name, True) for name in ALWAYS_FILES]
    have_roles = bool(env.get('WAREHOUSE_READER_PASSWORD') and env.get('WAREHOUSE_NAVIGATOR_PASSWORD'))
    if have_roles:
        steps.append((ROLES_FILE, False))
    print('Base:', 'vide, schéma complet' if fresh else 'existante, migrations additives seulement')
    if not have_roles:
        print('Rôles ignorés: WAREHOUSE_READER_PASSWORD et WAREHOUSE_NAVIGATOR_PASSWORD requis.')
    for name, single_transaction in steps:
        print(('[dry-run] ' if dry_run else '') + 'appliquer', name)
        if not dry_run:
            psql(env, *(['-1'] if single_transaction else []), '-f', str(DOCS / name))
    if fresh and not dry_run:
        if query(env, "SELECT count(*) FROM pg_available_extensions WHERE name = 'postgis'") == '0':
            print('PostGIS indisponible: le navigateur spatial sera limité; le schéma reste utilisable.')
        else:
            psql(env, '-c', 'CREATE EXTENSION IF NOT EXISTS postgis')


def publish_context(env):
    """Publier les fiches MCP (warehouse_context, dictionnaire) sans toucher au dépôt."""
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'publish_warehouse_context.py'), '--no-doc'],
                            env=env, text=True, capture_output=True)
    if result.returncode:
        print('Contexte MCP non publié (installer psycopg[binary], puis relancer): '
              + (result.stderr.strip().splitlines() or ['erreur inconnue'])[-1][:200])
        return False
    print(result.stdout.strip())
    return True


def check(env):
    rows = query(env, "SELECT dataset_version_id, source_instance||'/'||dataset_key||'/'||version_key, "
                      "coalesce(array_to_string(missing_criteria, ','), '') "
                      "FROM explore.fair_readiness ORDER BY 1")
    total = incomplete = 0
    for line in filter(None, rows.splitlines()):
        total += 1
        _, name, missing = line.split('|')
        if missing:
            incomplete += 1
            print(f'  {name}: manque {missing}')
    print(f'FAIR: {total - incomplete}/{total} versions complètes.')
    gaps = [line for line in query(env, 'SELECT problem||\': \'||object_name FROM explore.access_audit').splitlines() if line]
    for gap in gaps:
        print('  ACCÈS:', gap)
    print('Contrôle d\'accès:', 'écarts détectés' if gaps else 'aucun écart')
    return 3 if gaps else (2 if incomplete else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='afficher les étapes sans les appliquer')
    parser.add_argument('--check', action='store_true', help='rapporter les critères FAIR manquants après déploiement')
    args = parser.parse_args(argv)
    env = connection_env()
    deploy(env, args.dry_run)
    if not args.dry_run:
        publish_context(env)
    return check(env) if args.check and not args.dry_run else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(f'Échec PostgreSQL (code {error.returncode}); voir le message ci-dessus.')
