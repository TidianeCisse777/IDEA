"""Déployer, mettre à niveau ou vérifier le warehouse sur n'importe quel PostgreSQL 16+.

Rejouable: un warehouse existant n'est jamais réécrit; seules les migrations
additives, le contrôle d'accès, les rôles, l'enregistrement de version et le
contexte MCP sont réappliqués. Aucune donnée scientifique n'est chargée. Les
secrets passent par l'environnement, jamais par argv.

    WAREHOUSE_POSTGRES_PASSWORD=... WAREHOUSE_READER_PASSWORD=... \\
    WAREHOUSE_NAVIGATOR_PASSWORD=... python scripts/deploy_warehouse_postgres.py --check

    python scripts/deploy_warehouse_postgres.py --verify   # contrôle seul, ne modifie rien

Connexion: WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD (le rôle propriétaire).
Code de sortie: 0 prêt, 1 erreur, 2 prêt mais métadonnées FAIR incomplètes,
3 non prêt (contrôle de préparation en échec, prioritaire sur 2).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
# Order matters: roles come after every object they grant on; the release
# record comes last so it describes a complete deployment.
FRESH_FILES = ('warehouse_schema_proposal.sql', 'warehouse_metadata_migration.sql',
               'warehouse_ecopart_migration.sql')
ALWAYS_FILES = ('warehouse_ctd_zone_migration.sql', 'warehouse_uvp_particle_sizes_view.sql',
               'warehouse_ecotaxa_object_size_migration.sql',
               'warehouse_fair_migration.sql', 'warehouse_access_control.sql')
ROLES_FILE = 'warehouse_roles.sql'
RELEASE_FILE = 'warehouse_release.sql'
SERVICE_ROLES = ('warehouse_reader', 'warehouse_navigator')
GROUP_ROLES = ('warehouse_data_owner', 'warehouse_all_access', 'warehouse_explore_reader')


def release_version():
    """The release number lives in docs/warehouse_release.sql only."""
    match = re.search(r"\\set release '([^']+)'", (DOCS / RELEASE_FILE).read_text(encoding='utf-8'))
    return match.group(1)


def release_manifest():
    files = (*FRESH_FILES, *ALWAYS_FILES, ROLES_FILE, RELEASE_FILE)
    return [{'file': name, 'sha256': hashlib.sha256((DOCS / name).read_bytes()).hexdigest()} for name in files]


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
                            env=env, text=True, capture_output=capture)
    if result.returncode:
        if capture and result.stderr:
            # A captured query must still explain its failure.
            sys.stderr.write(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, 'psql')
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
    print('Warehouse %s — base: %s' % (release_version(), 'vide, schéma complet' if fresh
                                         else 'existante, migrations additives seulement'))
    if not have_roles:
        print('Rôles ignorés: WAREHOUSE_READER_PASSWORD et WAREHOUSE_NAVIGATOR_PASSWORD requis.')
    for name, single_transaction in steps:
        print(('[dry-run] ' if dry_run else '') + 'appliquer', name)
        if not dry_run:
            psql(env, *(['-1'] if single_transaction else []), '-f', str(DOCS / name))
    print(('[dry-run] ' if dry_run else '') + 'enregistrer la version', release_version())
    if not dry_run:
        psql(env, '-1', '-v', 'release=' + release_version(), '-v', 'method=deploy-script',
             '-v', 'migrations=' + json.dumps(release_manifest()), '-f', str(DOCS / RELEASE_FILE))
    if not dry_run:
        ensure_postgis(env)


def ensure_postgis(env):
    """PostGIS serves the navigator's spatial filter only; the schema does not need it."""
    if query(env, "SELECT count(*) FROM pg_extension WHERE extname = 'postgis'") != '0':
        return
    if query(env, "SELECT count(*) FROM pg_available_extensions WHERE name = 'postgis'") == '0':
        print('PostGIS non installé sur ce serveur: le filtre spatial du navigateur sera indisponible; '
              'le schéma, les accès et DbHub ne sont pas concernés.')
        return
    # PostGIS is not a trusted extension: a non-superuser owner cannot create it.
    result = subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE EXTENSION IF NOT EXISTS postgis'],
                            env=env, text=True, capture_output=True)
    if result.returncode:
        print('PostGIS disponible mais non activé (superuser requis). Demander à l\'administrateur du serveur: '
              'CREATE EXTENSION postgis; dans la base %s. Le reste du déploiement est appliqué.' % env['PGDATABASE'])


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


def role_settings(env, role):
    return query(env, "SELECT coalesce(array_to_string(s.setconfig, ' '), '') FROM pg_roles r "
                      "LEFT JOIN pg_db_role_setting s ON s.setrole = r.oid AND s.setdatabase = 0 "
                      "WHERE r.rolname = '%s'" % role)


def readiness(env):
    """Everything a person or an agent relies on, as (label, ok, detail, blocking)."""
    checks = []
    def exists(sql):
        return query(env, sql) == 't'

    release = query(env, "SELECT coalesce((SELECT release || ' (' || method || ', ' || to_char(applied_at, "
                         "'YYYY-MM-DD HH24:MI') || ')' FROM explore.warehouse_release), '')"
                         " WHERE to_regclass('explore.warehouse_release') IS NOT NULL")
    checks.append(('version enregistrée', bool(release), release or 'aucune: rejouer le déploiement', True))
    missing = [r for r in (*GROUP_ROLES, *SERVICE_ROLES)
               if not exists("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '%s')" % r)]
    checks.append(('rôles', not missing, 'manquants: ' + ', '.join(missing) if missing else 'groupes et rôles de service présents', True))
    for role in SERVICE_ROLES:
        settings = role_settings(env, role)
        needed = ['default_transaction_read_only=on', 'statement_timeout=30s']
        if role == 'warehouse_reader':
            needed.append('enable_mergejoin=off')
        absent = [item for item in needed if item not in settings]
        checks.append(('réglages %s' % role, not absent, 'manquants: ' + ', '.join(absent) if absent else 'lecture seule, 30 s', True))
    owner = role_settings(env, env['PGUSER'])
    checks.append(('propriétaire en lecture-écriture', 'default_transaction_read_only=on' not in owner,
                   env['PGUSER'], True))
    public_connect = exists("SELECT has_database_privilege('public', current_database(), 'CONNECT')")
    checks.append(('base fermée à PUBLIC', not public_connect, 'CONNECT accordé par nom uniquement'
                   if not public_connect else 'PUBLIC peut se connecter', True))
    gaps = [line for line in query(env, "SELECT problem || ': ' || object_name FROM explore.access_audit").splitlines() if line]
    checks.append(('filtre par ligne sans contournement', not gaps, '; '.join(gaps) or 'explore.access_audit vide', True))
    unsecured = query(env, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                           "WHERE n.nspname = 'warehouse' AND c.relrowsecurity AND NOT c.relforcerowsecurity")
    checks.append(('sécurité par ligne forcée', unsecured == '0', '%s table(s) sans FORCE' % unsecured
                   if unsecured != '0' else 'toutes les tables protégées', True))
    context = exists("SELECT to_regclass('explore.warehouse_context') IS NOT NULL AND "
                     "EXISTS (SELECT 1 FROM explore.warehouse_context WHERE topic = 'overview')")
    checks.append(('contexte MCP publié', context, 'warehouse_context(overview)' if context
                   else 'absent: publier le contexte (service warehouse-context ou ce script)', True))
    views = [v for v in ('my_access', 'my_datasets', 'dataset_catalog', 'fair_readiness', 'warehouse_dictionary')
             if not exists("SELECT to_regclass('explore.%s') IS NOT NULL" % v)]
    checks.append(('vues de découverte', not views, 'manquantes: ' + ', '.join(views) if views
                   else 'my_access, my_datasets, dataset_catalog, fair_readiness, dictionnaire', True))
    # Access follows the dataset version's contract. A FILET version whose analyses
    # carry another contract would be opened or closed as a whole: flag it.
    mixed = query(env, "SELECT string_agg(DISTINCT v.dataset_key || '/' || v.version_key, ', ') "
                       "FROM warehouse.filet_analysis a "
                       "JOIN warehouse.dataset_metadata m ON m.dataset_version_id = a.dataset_version_id "
                       "JOIN warehouse.dataset_version v ON v.id = a.dataset_version_id "
                       "WHERE a.analysis_contract IS NOT NULL AND a.analysis_contract IS DISTINCT FROM m.access_contract")
    checks.append(('contrats FILET cohérents avec la version', not mixed, 'aucun écart' if not mixed else
                   'analyses sous un autre contrat que leur version: ' + mixed[:200]
                   + ' (charger une version par contrat ou renseigner access_contract)', False))
    postgis = exists("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
    checks.append(('PostGIS (filtre spatial du navigateur)', postgis, 'actif' if postgis
                   else 'absent: CREATE EXTENSION postgis; par un superuser (le reste fonctionne sans)', False))
    trigger = exists("SELECT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'warehouse_adopt_explore_views')")
    checks.append(('adoption automatique des nouvelles vues', trigger, 'déclencheur actif' if trigger
                   else 'absent (déploiement sans superuser): rejouer après toute nouvelle vue explore', False))
    return checks


def fair_summary(env):
    rows = query(env, "SELECT source_instance||'/'||dataset_key||'/'||version_key, "
                      "coalesce(array_to_string(missing_criteria, ','), '') FROM explore.fair_readiness ORDER BY 1")
    lines = [line.split('|') for line in rows.splitlines() if line]
    incomplete = [(name, missing) for name, missing in lines if missing]
    for name, missing in incomplete[:20]:
        print(f'  {name}: manque {missing}')
    if len(incomplete) > 20:
        print(f'  … {len(incomplete) - 20} autre(s)')
    print(f'FAIR: {len(lines) - len(incomplete)}/{len(lines)} versions aux métadonnées complètes.')
    return bool(incomplete)


def check(env):
    checks = readiness(env)
    print('Préparation au déploiement:')
    for label, ok, detail, blocking in checks:
        print('  %s %s: %s' % ('OK  ' if ok else ('ÉCHEC' if blocking else 'NOTE'), label, detail))
    # Kept on its own line: scripts and the docs grep for it.
    gaps = next(detail for label, ok, detail, _ in checks if label == 'filtre par ligne sans contournement')
    print('Contrôle d\'accès:', 'aucun écart' if gaps == 'explore.access_audit vide' else 'écarts détectés')
    fair_incomplete = fair_summary(env)
    ready = all(ok for _, ok, _, blocking in checks if blocking)
    print('PRÊT: le warehouse peut être ouvert aux comptes.' if ready else 'NON PRÊT: corriger les lignes ÉCHEC.')
    return 3 if not ready else (2 if fair_incomplete else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='afficher les étapes sans les appliquer')
    parser.add_argument('--check', action='store_true', help='déployer puis produire le rapport de préparation')
    parser.add_argument('--verify', action='store_true', help='rapport de préparation seul, sans rien modifier')
    args = parser.parse_args(argv)
    env = connection_env()
    if args.verify:
        return check(env)
    deploy(env, args.dry_run)
    if not args.dry_run:
        publish_context(env)
    return check(env) if args.check and not args.dry_run else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(f'Échec PostgreSQL (code {error.returncode}); voir le message ci-dessus.')
