"""Brancher DbHub au warehouse depuis Codex, Claude ou tout client MCP.

Multiplateforme (Python standard). Les identifiants vivent dans un fichier
local en dehors du dépôt; ils ne sont jamais écrits dans une configuration MCP,
un argument de commande ni la sortie de ce script.

    python scripts/warehouse_connect.py init --from-file mon_compte.env
    python scripts/warehouse_connect.py check
    python scripts/warehouse_connect.py config codex      # ou claude-code, claude-desktop

`run` est la commande que le client MCP lance (protocole sur stdout: rien d'autre
n'y est écrit). Code de sortie de `check`: 0 réussi, 1 échec.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'dbhub' / 'warehouse.connect.toml'
SERVER_NAME = 'neolab-warehouse'
DBHUB_PACKAGE = '@bytebase/dbhub@1.5.0'
LOCAL_DBHUB = ROOT / 'data/tooling/dbhub/node_modules/@bytebase/dbhub/dist/index.js'
KEYS = ('WAREHOUSE_DB_HOST', 'WAREHOUSE_DB_PORT', 'WAREHOUSE_DB_NAME',
        'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD', 'WAREHOUSE_DB_SSLMODE')
DEFAULTS = {'WAREHOUSE_DB_PORT': '5432', 'WAREHOUSE_DB_NAME': 'neolab_warehouse',
            'WAREHOUSE_DB_SSLMODE': 'require'}


def credentials_path():
    override = os.environ.get('NEOLAB_WAREHOUSE_CREDENTIALS')
    if override:
        return Path(override)
    base = os.environ.get('APPDATA') if os.name == 'nt' else os.environ.get('XDG_CONFIG_HOME')
    base = Path(base) if base else Path.home() / ('AppData/Roaming' if os.name == 'nt' else '.config')
    return base / 'neolab-warehouse' / 'credentials.env'


def parse_env(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            values[key.strip()] = value.strip()
    return values


def load_settings(environ=None):
    """Variables d'environnement d'abord, puis le fichier local, puis les défauts."""
    environ = os.environ if environ is None else environ
    values = dict(DEFAULTS)
    path = credentials_path()
    if path.exists():
        values.update({k: v for k, v in parse_env(path.read_text(encoding='utf-8')).items() if k in KEYS})
    values.update({k: environ[k] for k in KEYS if environ.get(k)})
    missing = [k for k in ('WAREHOUSE_DB_HOST', 'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD') if not values.get(k)]
    if missing:
        raise SystemExit('Identifiants absents (%s). Lancer: python scripts/warehouse_connect.py init '
                         '--from-file <fichier remis par l\'administrateur>' % ', '.join(missing))
    return values


def build_dsn(values):
    return 'postgres://%s:%s@%s:%s/%s?sslmode=%s' % (
        quote(values['WAREHOUSE_DB_USER'], safe=''), quote(values['WAREHOUSE_DB_PASSWORD'], safe=''),
        values['WAREHOUSE_DB_HOST'], values['WAREHOUSE_DB_PORT'],
        quote(values['WAREHOUSE_DB_NAME'], safe=''), quote(values['WAREHOUSE_DB_SSLMODE'], safe=''))


def dbhub_command():
    override = os.environ.get('WAREHOUSE_DBHUB_COMMAND')
    if override:
        return override.split()
    base = ['--transport', 'stdio', '--config', str(CONFIG)]
    if LOCAL_DBHUB.exists():
        return [shutil.which('node') or 'node', str(LOCAL_DBHUB), *base]
    npx = shutil.which('npx') or shutil.which('npx.cmd')
    if not npx:
        raise SystemExit('Node.js est requis (https://nodejs.org) pour lancer DbHub.')
    return [npx, '-y', DBHUB_PACKAGE, *base]


def server_environment(values):
    env = dict(os.environ)
    env['WAREHOUSE_DSN'] = build_dsn(values)
    return env


def write_private(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        handle.write(content)
    if os.name != 'nt':
        path.chmod(0o600)


def init(args):
    if args.from_file:
        values = parse_env(Path(args.from_file).read_text(encoding='utf-8'))
    else:
        values = {'WAREHOUSE_DB_HOST': args.host, 'WAREHOUSE_DB_PORT': str(args.port),
                  'WAREHOUSE_DB_NAME': args.database, 'WAREHOUSE_DB_USER': args.user,
                  'WAREHOUSE_DB_SSLMODE': args.sslmode,
                  'WAREHOUSE_DB_PASSWORD': os.environ.get('WAREHOUSE_DB_PASSWORD') or getpass.getpass('Mot de passe: ')}
    values = {**DEFAULTS, **{k: v for k, v in values.items() if k in KEYS and v}}
    missing = [k for k in ('WAREHOUSE_DB_HOST', 'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD') if not values.get(k)]
    if missing:
        raise SystemExit('Valeurs manquantes: ' + ', '.join(missing))
    path = credentials_path()
    write_private(path, ''.join('%s=%s\n' % (k, values[k]) for k in KEYS if values.get(k)))
    print('Identifiants enregistrés: %s (compte %s). Ils ne sont pas dans le dépôt.' % (path, values['WAREHOUSE_DB_USER']))
    print('Suite: python scripts/warehouse_connect.py check')
    return 0


def run(_args):
    command = dbhub_command()
    env = server_environment(load_settings())
    if os.name == 'nt':
        return subprocess.call(command, env=env)
    os.execvpe(command[0], command, env)


def registration(client):
    script = str(Path(__file__).resolve())
    python = sys.executable
    if client == 'codex':
        return ('# Option 1: ligne de commande\n'
                'codex mcp add %s -- "%s" "%s" run\n\n'
                '# Option 2: ~/.codex/config.toml\n'
                '[mcp_servers.%s]\ncommand = "%s"\nargs = ["%s", "run"]\n'
                % (SERVER_NAME, python, script, SERVER_NAME, python, script))
    if client == 'claude-code':
        return ('# Pour vous seul, tous projets:\n'
                'claude mcp add --scope user %s -- "%s" "%s" run\n\n'
                '# Ou partagé dans un projet (.mcp.json, sans secret):\n%s\n'
                % (SERVER_NAME, python, script, registration('json')))
    if client == 'claude-desktop':
        return ('Ajouter dans claude_desktop_config.json (Réglages > Développeur > Modifier la config):\n%s\n'
                % registration('json'))
    return json.dumps({'mcpServers': {SERVER_NAME: {'command': python, 'args': [script, 'run']}}}, indent=2)


def config(args):
    print(registration(args.client))
    print('Les identifiants restent dans %s; redémarrer le client pour charger le serveur.' % credentials_path())
    return 0


class McpSession:
    """Client MCP minimal sur le processus DbHub (une réponse par id)."""

    def __init__(self, command, env):
        self.process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.next_id = 0

    def request(self, method, params):
        self.next_id += 1
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.next_id, 'method': method,
                                             'params': params}) + '\n')
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError('DbHub s\'est arrêté (connexion refusée, identifiants ou réseau)')
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get('id') == self.next_id:
                if 'error' in message:
                    raise RuntimeError('erreur MCP sur %s' % method)
                return message['result']

    def notify(self, method):
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': method}) + '\n')
        self.process.stdin.flush()

    def sql(self, statement):
        result = self.request('tools/call', {'name': 'execute_sql', 'arguments': {'sql': statement}})
        text = ''.join(part.get('text', '') for part in result.get('content', []))
        payload = json.loads(text)
        if result.get('isError') or not payload.get('success', True):
            raise RuntimeError('requête refusée: %s' % str(payload.get('error', ''))[:160])
        return payload['data']['statements'][0]['rows']

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        self.process.terminate()


def check(_args):
    values = load_settings()
    print('Compte %s sur %s:%s/%s' % (values['WAREHOUSE_DB_USER'], values['WAREHOUSE_DB_HOST'],
                                       values['WAREHOUSE_DB_PORT'], values['WAREHOUSE_DB_NAME']))
    session = McpSession(dbhub_command(), server_environment(values))
    steps = []
    try:
        session.request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                       'clientInfo': {'name': 'neolab-check', 'version': '1'}})
        session.notify('notifications/initialized')
        tools = {tool['name'] for tool in session.request('tools/list', {})['tools']}
        missing = {'execute_sql', 'warehouse_context'} - tools
        steps.append(('outils MCP', not missing, 'manquants: %s' % ', '.join(sorted(missing)) if missing else ', '.join(sorted(tools))))
        who = session.sql("SELECT current_user AS role, current_setting('transaction_read_only') AS read_only")[0]
        steps.append(('compte et lecture seule', who['read_only'] == 'on', '%s, lecture seule=%s' % (who['role'], who['read_only'])))
        scope = session.sql('SELECT grantee, source_instance, contract, zone_key, year_min, year_max FROM explore.my_access')
        steps.append(('périmètre (explore.my_access)', True, '; '.join(
            ' / '.join(str(row[k]) for k in ('grantee', 'source_instance', 'contract', 'zone_key', 'year_min', 'year_max') if row.get(k) is not None)
            for row in scope) or 'aucun droit accordé: aucune donnée lisible'))
        catalog = session.sql('SELECT count(*) AS n FROM explore.dataset_catalog')[0]['n']
        steps.append(('catalogue (explore.dataset_catalog)', True, '%s version(s) décrite(s)' % catalog))
        context = session.request('tools/call', {'name': 'warehouse_context', 'arguments': {'topic': 'overview'}})
        steps.append(('contexte métier (warehouse_context)', not context.get('isError'), 'fiche overview lue'))
    except Exception as error:  # noqa: BLE001 - toute erreur est un échec de recette, sans détail secret
        steps.append(('connexion', False, str(error)))
    finally:
        session.close()
    for label, ok, detail in steps:
        print('  %s %s: %s' % ('OK  ' if ok else 'ÉCHEC', label, detail))
    passed = bool(steps) and all(ok for _, ok, _ in steps)
    print('PASS: DbHub est utilisable depuis ce poste.' if passed else
          'FAIL: voir l\'étape en échec; vérifier le fichier d\'identifiants et l\'accès réseau au serveur.')
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init', help='enregistrer les identifiants reçus (fichier local privé)')
    p.add_argument('--from-file', help='fichier remis par l\'administrateur')
    p.add_argument('--host')
    p.add_argument('--port', type=int, default=5432)
    p.add_argument('--database', default='neolab_warehouse')
    p.add_argument('--user')
    p.add_argument('--sslmode', default='require')
    p.set_defaults(handler=init)
    sub.add_parser('check', help='recette complète: connexion, rôle, périmètre, catalogue').set_defaults(handler=check)
    sub.add_parser('run', help='lancer le serveur MCP (commande enregistrée dans le client)').set_defaults(handler=run)
    p = sub.add_parser('config', help='afficher la commande ou le fragment de configuration du client')
    p.add_argument('client', choices=('codex', 'claude-code', 'claude-desktop', 'json'))
    p.set_defaults(handler=config)
    args = parser.parse_args(argv)
    if args.command == 'init' and not args.from_file and not (args.host and args.user):
        parser.error('init: --from-file, ou --host et --user')
    return args.handler(args)


if __name__ == '__main__':
    sys.exit(main())
