"""Sauvegarder ou restaurer le warehouse dans un seul fichier portable.

Le fichier produit est indépendant de la machine : il peut être copié sur un
disque externe, un cloud (Drive, OneDrive...) ou utilisé pour reconstituer la
base sur un autre ordinateur ou serveur. C'est le filet de sécurité en
attendant un hébergement permanent (voir docs/WAREHOUSE_RELEASE_V1.md).

    python scripts/backup_warehouse.py
    python scripts/backup_warehouse.py --copy-to "~/OneDrive/NeoLab/warehouse-backups"
    python scripts/backup_warehouse.py --keep 10
    python scripts/backup_warehouse.py --restore data/warehouse_backups/neolab_warehouse_20261030_183000.dump

Connexion: WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD (le rôle propriétaire),
lues dans l'environnement ou dans .env.warehouse. Le mot de passe ne passe
jamais en argument de commande.
Code de sortie: 0 ok, 1 erreur (connexion, pg_dump/pg_restore, fichier absent).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / 'data' / 'warehouse_backups'  # ignoré par Git (.gitignore)


def connection_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env.warehouse')
    except ImportError:
        pass
    env = dict(os.environ)
    env.update(PGHOST=env.get('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
               PGPORT=env.get('WAREHOUSE_POSTGRES_PORT', '55432'),
               PGDATABASE=env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
               PGUSER=env.get('WAREHOUSE_POSTGRES_USER', 'neolab'))
    password = env.get('WAREHOUSE_POSTGRES_PASSWORD')
    if not password:
        raise SystemExit('WAREHOUSE_POSTGRES_PASSWORD est requis (rôle propriétaire); '
                         'le définir dans .env.warehouse ou l\'environnement.')
    env['PGPASSWORD'] = password
    return env


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(num_bytes):
    value = float(num_bytes)
    for unit in ('o', 'Ko', 'Mo', 'Go'):
        if value < 1024 or unit == 'Go':
            return f'{value:.1f} {unit}'
        value /= 1024


def backup(env, args):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    target = BACKUP_DIR / f"{env['PGDATABASE']}_{stamp}.dump"
    print(f"Sauvegarde de {env['PGDATABASE']}@{env['PGHOST']}:{env['PGPORT']}...")
    result = subprocess.run(
        ['pg_dump', '-Fc', '--no-owner', '--no-acl', '-h', env['PGHOST'], '-p', env['PGPORT'],
         '-U', env['PGUSER'], '-d', env['PGDATABASE'], '-f', str(target)],
        env=env, text=True, capture_output=True)
    if result.returncode:
        target.unlink(missing_ok=True)
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit('Échec de pg_dump; voir le message ci-dessus (identifiants, connexion, espace disque).')
    digest = sha256_of(target)
    (target.with_suffix(target.suffix + '.sha256')).write_text(f'{digest}  {target.name}\n', encoding='utf-8')
    print(f'Sauvegarde créée : {target} ({human_size(target.stat().st_size)})')
    print(f'SHA-256 : {digest}')

    destinations = [target]
    if args.copy_to:
        remote_dir = Path(args.copy_to).expanduser()
        remote_dir.mkdir(parents=True, exist_ok=True)
        for source in (target, target.with_suffix(target.suffix + '.sha256')):
            shutil.copy2(source, remote_dir / source.name)
        destinations.append(remote_dir / target.name)
        print(f'Copiée vers : {remote_dir / target.name}')

    if args.keep:
        prune(BACKUP_DIR, args.keep)

    print('\nPour restaurer ce fichier ailleurs :')
    print(f'  python scripts/backup_warehouse.py --restore {target.name if args.copy_to is None else destinations[-1]}')
    return 0


def prune(directory, keep):
    dumps = sorted(directory.glob('*.dump'), key=lambda path: path.stat().st_mtime, reverse=True)
    for stale in dumps[keep:]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(stale.suffix + '.sha256').unlink(missing_ok=True)
        print(f'Ancienne sauvegarde locale supprimée : {stale.name}')


def restore(env, args):
    source = Path(args.restore).expanduser()
    if not source.is_file():
        raise SystemExit(f'Fichier introuvable : {source}')
    checksum_file = source.with_suffix(source.suffix + '.sha256')
    if checksum_file.is_file():
        expected = checksum_file.read_text(encoding='utf-8').split()[0]
        actual = sha256_of(source)
        if actual != expected:
            raise SystemExit(f'SHA-256 différent de celui attendu : fichier possiblement corrompu ou modifié.\n'
                             f'  attendu  {expected}\n  obtenu   {actual}')
        print('Empreinte SHA-256 vérifiée.')
    if not args.yes:
        answer = input(f"Ceci va remplacer le contenu de la base '{env['PGDATABASE']}' sur "
                       f"{env['PGHOST']}:{env['PGPORT']} par {source.name}. Continuer ? [o/N] ")
        if answer.strip().lower() not in ('o', 'oui', 'y', 'yes'):
            print('Annulé.')
            return 1
    print(f"Restauration de {source} vers {env['PGDATABASE']}@{env['PGHOST']}:{env['PGPORT']}...")
    result = subprocess.run(
        ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-acl', '-h', env['PGHOST'], '-p', env['PGPORT'],
         '-U', env['PGUSER'], '-d', env['PGDATABASE'], str(source)],
        env=env, text=True, capture_output=True)
    # pg_restore renvoie parfois un code non nul pour de simples avertissements
    # (objets déjà absents lors du --clean) ; seules les erreurs réelles bloquent.
    real_errors = [line for line in result.stderr.splitlines() if 'ERROR' in line]
    if result.returncode and real_errors:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit('Échec de pg_restore; voir le message ci-dessus.')
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    print('Restauration terminée. Vérifier ensuite : python scripts/deploy_warehouse_postgres.py --verify')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--copy-to', help='dossier supplémentaire où copier la sauvegarde (ex. un dossier cloud synchronisé)')
    parser.add_argument('--keep', type=int, default=0, help='ne garder que les N sauvegardes locales les plus récentes (0 = toutes les garder)')
    parser.add_argument('--restore', help='restaurer depuis ce fichier .dump au lieu de sauvegarder')
    parser.add_argument('--yes', action='store_true', help='restaurer sans demander de confirmation')
    args = parser.parse_args(argv)
    env = connection_env()
    return restore(env, args) if args.restore else backup(env, args)


if __name__ == '__main__':
    sys.exit(main())
