"""Charger les données réelles dans un warehouse v1 déployé, dans le bon ordre.

Vérifie d'abord tout ce dont les chargeurs ont besoin, puis enchaîne les scripts
existants (aucune logique de chargement n'est dupliquée ici), s'arrête au premier
échec, rejoue le déploiement et lance l'assurance qualité.

    python scripts/load_warehouse.py --preflight                 # vérifications seules
    python scripts/load_warehouse.py --project-id 149 --dry-run  # plan, sans rien lancer
    python scripts/load_warehouse.py --all-projects --filet-dir ~/exports/filet

Connexion: WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD (le rôle propriétaire).
Sources: ECOTAXA_USERNAME / ECOTAXA_PASSWORD (EcoTaxa et EcoPart), ou ECOPART_TOKEN.
Les secrets ne sont jamais affichés ni passés en argument.
Code de sortie: 0 chargé et vérifié, 1 vérification préalable en échec, 2 étape en échec.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
SOURCES = {
    'EcoTaxa': 'https://ecotaxa.obs-vlfr.fr/api/status',
    'EcoPart': 'https://ecopart.obs-vlfr.fr/',
    'ERDDAP Amundsen': 'https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713.das',
}
MODULES = ('bs4', 'pandas', 'psycopg', 'dotenv', 'requests', 'shapely')
FILET_SUFFIXES = {'samples': '(taxonomy samples-data).csv', 'abundance': '(copepod abund&biomass-data).csv',
                  'dictionary': '(copepod abund&biomass-metadata).csv'}


def environment():
    env = dict(os.environ)
    try:
        from dotenv import dotenv_values
        for name in ('.env', '.env.warehouse'):
            for key, value in dotenv_values(ROOT / name).items():
                env.setdefault(key, value)
    except ImportError:
        pass
    conninfo = 'host=%s port=%s dbname=%s user=%s' % (
        env.get('WAREHOUSE_POSTGRES_HOST', 'localhost'), env.get('WAREHOUSE_POSTGRES_PORT', '55432'),
        env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'), env.get('WAREHOUSE_POSTGRES_USER', 'neolab'))
    # Every loader reads one of these; the password travels through libpq's PGPASSWORD.
    env['WAREHOUSE_DATABASE_URL'] = conninfo
    if env.get('WAREHOUSE_POSTGRES_PASSWORD'):
        env['PGPASSWORD'] = env['WAREHOUSE_POSTGRES_PASSWORD']
    # Loader sessions always write, whatever defaults the owner role carries.
    env['PGOPTIONS'] = '-c default_transaction_read_only=off -c statement_timeout=0'
    return env, conninfo


def filet_files(directory):
    if not directory:
        return None
    found = {}
    for key, suffix in FILET_SUFFIXES.items():
        matches = sorted(Path(directory).expanduser().glob('*' + suffix))
        found[key] = matches[-1] if matches else None
    return found


def preflight(env, conninfo, args):
    checks = []
    checks.append(('identifiants EcoTaxa', bool(env.get('ECOTAXA_USERNAME') and env.get('ECOTAXA_PASSWORD')),
                   'présents (non affichés)' if env.get('ECOTAXA_USERNAME') else
                   'ECOTAXA_USERNAME / ECOTAXA_PASSWORD absents (secrets de l\'environnement ou .env)'))
    checks.append(('mot de passe propriétaire', bool(env.get('WAREHOUSE_POSTGRES_PASSWORD')),
                   'présent (non affiché)' if env.get('WAREHOUSE_POSTGRES_PASSWORD') else 'WAREHOUSE_POSTGRES_PASSWORD absent'))
    missing = [m for m in MODULES if importlib.util.find_spec(m) is None]
    checks.append(('dépendances Python', not missing, 'manquantes: %s (pip install -r scripts/requirements-warehouse.txt)'
                   % ', '.join(missing) if missing else ', '.join(MODULES)))
    checks.append(('client psql', bool(shutil.which('psql')), shutil.which('psql') or 'psql introuvable'))
    if shutil.which('psql') and env.get('WAREHOUSE_POSTGRES_PASSWORD'):
        result = subprocess.run(['psql', '-X', '-At', conninfo, '-c',
                                 "SELECT coalesce((SELECT release FROM explore.warehouse_release), 'absente')"],
                                env=env, capture_output=True, text=True)
        release = result.stdout.strip()
        checks.append(('warehouse v1 déployé', result.returncode == 0 and release not in ('', 'absente'),
                       'version %s' % release if result.returncode == 0 else
                       'connexion impossible: %s' % (result.stderr.strip().splitlines() or ['?'])[-1][:160]))
    for name, url in SOURCES.items():
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                reachable, detail = True, 'joignable (HTTP %s)' % response.status
        except urllib.error.HTTPError as error:  # the server answered
            reachable, detail = error.code < 500, 'joignable (HTTP %s)' % error.code
        except OSError as error:
            reachable, detail = False, 'injoignable: %s' % str(error)[:120]
        checks.append(('réseau ' + name, reachable, detail))
    files = filet_files(args.filet_dir)
    if files is not None:
        absent = [key for key, path in files.items() if path is None]
        checks.append(('exports FILET', not absent, 'manquants: %s dans %s' % (', '.join(absent), args.filet_dir)
                       if absent else ', '.join(path.name for path in files.values())))
    print('Vérification préalable:')
    for label, ok, detail in checks:
        print('  %s %s: %s' % ('OK  ' if ok else 'ÉCHEC', label, detail))
    return all(ok for _, ok, _ in checks)


def steps(args, conninfo):
    scope = ['--all-projects'] if args.all_projects else ['--project-id', str(args.project_id)]
    plan = [
        ('échantillons EcoTaxa', ['populate_ecotaxa_samples.py', *scope, '--database-url', conninfo]),
        ('objets EcoTaxa', ['populate_ecotaxa_objects.py', *scope, '--database-url', conninfo]),
        ('profils EcoPart liés', ['populate_ecopart.py']),
        ('profils CTD Amundsen', ['populate_amundsen_ctd.py', '--database-url', conninfo]),
        ('zones des profils CTD', ['assign_filet_zones.py', '--table', 'ctd_profile', '--database-url', conninfo]),
    ]
    files = filet_files(args.filet_dir)
    if files and all(files.values()):
        plan += [
            ('FILET', ['populate_filet.py', '--samples', str(files['samples']), '--abundance', str(files['abundance']),
                       '--dictionary', str(files['dictionary']), '--database-url', conninfo]),
            ('appariements FILET–UVP', ['populate_filet_uvp_matches.py', '--database-url', conninfo]),
        ]
    # Replay: catalog entries for the new versions, ownership, MCP context, release record, readiness.
    plan.append(('rejeu du déploiement et rapport', ['deploy_warehouse_postgres.py', '--check']))
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--project-id', type=int, help='un projet EcoTaxa (conseillé pour un premier essai)')
    scope.add_argument('--all-projects', action='store_true', help='tous les projets accessibles au compte')
    parser.add_argument('--filet-dir', help='dossier contenant les trois exports FILET (facultatif)')
    parser.add_argument('--preflight', action='store_true', help='vérifications seules')
    parser.add_argument('--dry-run', action='store_true', help='vérifications et plan, sans rien lancer')
    args = parser.parse_args(argv)
    env, conninfo = environment()
    ready = preflight(env, conninfo, args)
    if args.preflight:
        return 0 if ready else 1
    if not (args.project_id or args.all_projects):
        parser.error('indiquer --project-id ou --all-projects')
    plan = steps(args, conninfo)
    print('Plan:')
    for number, (label, command) in enumerate(plan, 1):
        print('  %d. %s: python scripts/%s' % (number, label, ' '.join(command)))
    if args.dry_run:
        return 0 if ready else 1
    if not ready:
        print('Arrêt: corriger les lignes ÉCHEC avant de charger.')
        return 1
    for number, (label, command) in enumerate(plan, 1):
        started = time.monotonic()
        print('\n[%d/%d] %s…' % (number, len(plan), label), flush=True)
        result = subprocess.run([sys.executable, str(SCRIPTS / command[0]), *command[1:]], env=env, cwd=ROOT)
        # The deploy report exits 2 when only FAIR metadata is incomplete: expected in v1.
        if result.returncode and not (command[0] == 'deploy_warehouse_postgres.py' and result.returncode == 2):
            print('ÉCHEC à l\'étape « %s » (code %d). Les étapes précédentes sont conservées; corriger puis relancer: '
                  'les chargeurs reprennent ou ignorent ce qui est déjà chargé.' % (label, result.returncode))
            return 2
        print('[%d/%d] %s: terminé en %.0f s' % (number, len(plan), label, time.monotonic() - started), flush=True)
    print('\nAssurance qualité (lecture seule, rôle lecteur):')
    qa_env = dict(env, WAREHOUSE_READER_HOST=env.get('WAREHOUSE_POSTGRES_HOST', 'localhost'),
                  WAREHOUSE_READER_PORT=env.get('WAREHOUSE_POSTGRES_PORT', '55432'),
                  WAREHOUSE_READER_DB=env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'))
    qa = subprocess.run([sys.executable, str(SCRIPTS / 'audit_warehouse.py')], env=qa_env, cwd=ROOT)
    print('Chargement terminé. Poser ensuite les contrats (scripts/warehouse_user.py contract) avant d\'ouvrir des comptes restreints.')
    return 0 if qa.returncode == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
