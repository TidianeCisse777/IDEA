"""Gérer les comptes de lecture du warehouse (administrateur).

Crée un compte restreint, génère son mot de passe et écrit un fichier
d'identifiants à remettre à la personne; elle l'enregistre avec
`scripts/warehouse_connect.py init --from-file`. Aucun mot de passe n'est affiché
ni passé en argument: le SQL transite par l'entrée standard de psql.

    python scripts/warehouse_user.py create ines --source ecotaxa --contract C1 --zone lab --year-min 2018 --year-max 2022
    python scripts/warehouse_user.py grant ines --source filet --contract C1
    python scripts/warehouse_user.py rotate ines
    python scripts/warehouse_user.py offboard ines
    python scripts/warehouse_user.py list

Connexion administrateur: WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD (comme le
déploiement). Adresse donnée aux utilisateurs: --public-host ou WAREHOUSE_PUBLIC_HOST.
Sans option de droit, le compte est créé SANS accès aux données (refus par défaut).
"""
import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'data' / 'warehouse_backups' / 'users'
NAME = re.compile(r'^[a-z][a-z0-9_]{2,39}$')
RESERVED = ('warehouse_', 'pg_', 'postgres', 'neolab', 'app_owner')
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')


def valid_name(name):
    if not NAME.match(name) or name.startswith(RESERVED) or name in RESERVED:
        raise SystemExit('Nom de rôle invalide ou réservé: lettres minuscules, chiffres et _ (3 à 40), '
                         'sans préfixe warehouse_ ni pg_.')
    return name


def admin_env():
    password = os.environ.get('WAREHOUSE_POSTGRES_PASSWORD')
    if not password:
        raise SystemExit('WAREHOUSE_POSTGRES_PASSWORD est requis (rôle propriétaire).')
    env = dict(os.environ)
    env.update(PGHOST=env.get('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
               PGPORT=env.get('WAREHOUSE_POSTGRES_PORT', '55432'),
               PGDATABASE=env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
               PGUSER=env.get('WAREHOUSE_POSTGRES_USER', 'neolab'), PGPASSWORD=password)
    return env


def psql(env, script, variables=None, tuples=False):
    """Exécuter du SQL lu sur stdin: un secret n'apparaît jamais dans la liste des processus."""
    command = ['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1']
    for key, value in (variables or {}).items():
        command += ['-v', '%s=%s' % (key, value)]
    if tuples:
        command += ['-A', '-t']
    result = subprocess.run(command + ['-f', '-'], input=script, env=env, text=True, capture_output=True)
    if result.returncode:
        errors = [line for line in result.stderr.splitlines() if 'ERROR' in line] or result.stderr.splitlines()
        raise SystemExit('Échec PostgreSQL: ' + (errors[0] if errors else 'erreur inconnue')[:300])
    return result.stdout.strip()


def role_exists(env, name):
    return psql(env, "SELECT 1 FROM pg_roles WHERE rolname = :'name';", {'name': name}, tuples=True) == '1'


def write_bundle(env, name, password, out_dir, public_host, sslmode):
    host = public_host or os.environ.get('WAREHOUSE_PUBLIC_HOST') or env['PGHOST']
    mode = sslmode or ('disable' if host in LOCAL_HOSTS else 'require')
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ('%s.env' % name)
    content = ('# Identifiants NeoLab warehouse pour %s. Remettre par un canal sûr, puis supprimer ce fichier.\n'
               'WAREHOUSE_DB_HOST=%s\nWAREHOUSE_DB_PORT=%s\nWAREHOUSE_DB_NAME=%s\nWAREHOUSE_DB_USER=%s\n'
               'WAREHOUSE_DB_PASSWORD=%s\nWAREHOUSE_DB_SSLMODE=%s\n'
               % (name, host, os.environ.get('WAREHOUSE_PUBLIC_PORT', env['PGPORT']), env['PGDATABASE'], name, password, mode))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        handle.write(content)
    return path


# The UVP views join an EcoPart profile to its EcoTaxa sample: a grant on only
# one of them leaves those views empty.
PAIRED_SOURCES = {'ecotaxa': 'ecopart', 'ecopart': 'ecotaxa'}


def sources(args):
    """`--source a,b` gives one grant per source; absent means every source."""
    if not args.source:
        return ['']
    values = [value.strip() for value in args.source.split(',') if value.strip()]
    if any(not re.match(r'^[a-z][a-z0-9_]*$', value) for value in values):
        raise SystemExit('--source: noms de sources séparés par des virgules (ex. ecotaxa,ecopart).')
    return values


def grant_sql(source_index):
    return ("INSERT INTO warehouse.access_grant (grantee, source_instance, contract, zone_key, year_min, year_max, "
            "include_unknown_scope, note) "
            "VALUES (:'name', NULLIF(:'source_%d', ''), NULLIF(:'contract', ''), NULLIF(:'zone', ''), "
            "NULLIF(:'year_min', '')::integer, NULLIF(:'year_max', '')::integer, :'include_unknown'::boolean, "
            "NULLIF(:'note', ''));" % source_index)


def grants_sql(args):
    return ''.join(grant_sql(index) + '\n' for index, _ in enumerate(sources(args)))


def grant_variables(args):
    variables = {'name': args.name, 'contract': args.contract or '', 'zone': args.zone or '',
                 'year_min': args.year_min if args.year_min is not None else '',
                 'year_max': args.year_max if args.year_max is not None else '', 'note': args.note or '',
                 'include_unknown': 'true' if getattr(args, 'include_unknown', False) else 'false'}
    variables.update({'source_%d' % index: value for index, value in enumerate(sources(args))})
    return variables


def paired_source_warning(args):
    granted = set(sources(args))
    missing = sorted(PAIRED_SOURCES[value] for value in granted if value in PAIRED_SOURCES and PAIRED_SOURCES[value] not in granted)
    if missing and '' not in granted:
        return ('Attention: les vues UVP joignent EcoTaxa et EcoPart. Sans droit sur %s, elles resteront vides '
                'pour ce compte (ajouter --source ecotaxa,ecopart ou un `grant`).' % ', '.join(missing))
    return None


def wants_grant(args):
    return any(value is not None for value in (args.source, args.contract, args.zone, args.year_min, args.year_max))


def create(args):
    valid_name(args.name)
    env = admin_env()
    if role_exists(env, args.name):
        raise SystemExit('Le rôle existe déjà: utiliser `rotate` pour un nouveau mot de passe, `grant` pour des droits.')
    password = secrets.token_urlsafe(24)
    expires = ("VALID UNTIL '%s'" % (datetime.now(timezone.utc) + timedelta(days=args.expires_days)).strftime('%Y-%m-%d %H:%M:%S+00')
               if args.expires_days else '')
    enroll = ("GRANT warehouse_all_access TO :\"name\"; GRANT warehouse_explore_reader TO :\"name\"; "
              "ALTER ROLE :\"name\" SET default_transaction_read_only = on; "
              "ALTER ROLE :\"name\" SET statement_timeout = '30s'; "
              "ALTER ROLE :\"name\" SET enable_mergejoin = off;"
              if args.all_access else "SELECT warehouse.enroll_access_role(:'name');")
    script = ("BEGIN;\nCREATE ROLE :\"name\" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
              "PASSWORD '%s' %s;\n%s\n" % (password, expires, enroll))
    if wants_grant(args) and not args.all_access:
        script += grants_sql(args)
    psql(env, script + 'COMMIT;\n', grant_variables(args))
    path = write_bundle(env, args.name, password, Path(args.out_dir), args.public_host, args.sslmode)
    print('Compte %s créé (%s).' % (args.name, 'accès à toutes les données' if args.all_access else
                                    'périmètre restreint' if wants_grant(args) else 'AUCUN droit: refus par défaut'))
    print('Fichier d\'identifiants: %s (lecture réservée au propriétaire).' % path)
    warning = paired_source_warning(args) if wants_grant(args) and not args.all_access else None
    if warning:
        print(warning)
    print('Remettre ce fichier par un canal sûr; la personne exécute:')
    print('  python scripts/warehouse_connect.py init --from-file <fichier> && python scripts/warehouse_connect.py check')
    return 0


def grant(args):
    valid_name(args.name)
    env = admin_env()
    if not role_exists(env, args.name):
        raise SystemExit('Rôle inconnu: créer le compte avec `create`.')
    if not wants_grant(args):
        raise SystemExit('Préciser au moins une limite (--source, --contract, --zone, --year-min, --year-max).')
    psql(env, grants_sql(args), grant_variables(args))
    print('%d droit(s) ajouté(s) pour %s.' % (len(sources(args)), args.name))
    warning = paired_source_warning(args)
    if warning:
        print(warning)
    return 0


def rotate(args):
    valid_name(args.name)
    env = admin_env()
    if not role_exists(env, args.name):
        raise SystemExit('Rôle inconnu.')
    password = secrets.token_urlsafe(24)
    psql(env, "ALTER ROLE :\"name\" LOGIN PASSWORD '%s';\n" % password, {'name': args.name})
    path = write_bundle(env, args.name, password, Path(args.out_dir), args.public_host, args.sslmode)
    print('Nouveau mot de passe pour %s: %s (l\'ancien est invalide).' % (args.name, path))
    return 0


def offboard(args):
    valid_name(args.name)
    env = admin_env()
    if not role_exists(env, args.name):
        raise SystemExit('Rôle inconnu.')
    psql(env, "BEGIN;\nUPDATE warehouse.access_grant SET revoked_at = now() WHERE grantee = :'name' AND revoked_at IS NULL;\n"
              "ALTER ROLE :\"name\" NOLOGIN;\nCOMMIT;\n", {'name': args.name})
    print('%s: droits révoqués (historique conservé) et connexion fermée.' % args.name)
    return 0


def list_accounts(_args):
    env = admin_env()
    print(psql(env, """
SELECT r.rolname, CASE WHEN r.rolcanlogin THEN 'actif' ELSE 'fermé' END AS connexion,
       CASE WHEN pg_has_role(r.oid, 'warehouse_all_access', 'member') THEN 'toutes les données' ELSE 'restreint' END AS portée,
       coalesce((SELECT string_agg(format('%s/%s/%s/%s-%s', coalesce(g.source_instance, '*'), coalesce(g.contract, '*'),
                 coalesce(g.zone_key, '*'), coalesce(g.year_min::text, '*'), coalesce(g.year_max::text, '*'))
                 || CASE WHEN g.include_unknown_scope THEN ' +inconnues' ELSE '' END, '; ')
                 FROM warehouse.access_grant g WHERE g.grantee = r.rolname AND g.revoked_at IS NULL), '') AS droits_actifs,
       coalesce(r.rolvaliduntil::date::text, '') AS expire
FROM pg_roles r
WHERE r.rolname NOT IN ('warehouse_explore_reader', 'warehouse_all_access', 'warehouse_data_owner')
  AND (pg_has_role(r.oid, 'warehouse_explore_reader', 'member') OR r.rolname IN ('warehouse_reader', 'warehouse_navigator'))
ORDER BY 1;""", tuples=True) or 'Aucun compte.')
    return 0


def add_grant_options(parser):
    parser.add_argument('--source', help='ecotaxa, ecopart, filet, ctd…, ou plusieurs séparées par des virgules '
                                         '(absent = toutes). Vues UVP: ecotaxa,ecopart')
    parser.add_argument('--contract', help='contrat de la version du jeu de données (absent = tous)')
    parser.add_argument('--zone', help='clé de zone marine (absent = toutes, zones inconnues incluses)')
    parser.add_argument('--include-unknown', action='store_true',
                        help='avec --zone ou des années: inclure aussi les lignes à zone non attribuée ou sans date')
    parser.add_argument('--year-min', type=int)
    parser.add_argument('--year-max', type=int)
    parser.add_argument('--note', help='référence de l\'entente ou de la demande')


def add_bundle_options(parser):
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT), help='dossier des fichiers d\'identifiants (hors Git)')
    parser.add_argument('--public-host', help='adresse que la personne utilisera pour joindre la base')
    parser.add_argument('--sslmode', choices=('disable', 'prefer', 'require'), help='défaut: require hors local')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create', help='créer un compte et son fichier d\'identifiants')
    p.add_argument('name')
    p.add_argument('--all-access', action='store_true', help='personnel autorisé à tout lire (sans filtre)')
    p.add_argument('--expires-days', type=int, help='mot de passe valide N jours')
    add_grant_options(p)
    add_bundle_options(p)
    p.set_defaults(handler=create)
    p = sub.add_parser('grant', help='ajouter un droit à un compte existant')
    p.add_argument('name')
    add_grant_options(p)
    p.set_defaults(handler=grant)
    p = sub.add_parser('rotate', help='nouveau mot de passe et nouveau fichier')
    p.add_argument('name')
    add_bundle_options(p)
    p.set_defaults(handler=rotate)
    p = sub.add_parser('offboard', help='révoquer les droits et fermer la connexion')
    p.add_argument('name')
    p.set_defaults(handler=offboard)
    sub.add_parser('list', help='comptes, portée et droits actifs').set_defaults(handler=list_accounts)
    args = parser.parse_args(argv)
    if getattr(args, 'all_access', False) and wants_grant(args):
        parser.error('--all-access ne se combine pas avec des limites de droit')
    return args.handler(args)


if __name__ == '__main__':
    sys.exit(main())
