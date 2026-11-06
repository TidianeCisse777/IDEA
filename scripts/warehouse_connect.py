"""Brancher DbHub au warehouse depuis Codex, Claude ou tout client MCP.

Multiplateforme (Python standard). Les identifiants vivent dans un fichier
local en dehors du dépôt; ils ne sont jamais écrits dans une configuration MCP,
un argument de commande ni la sortie de ce script.

    python scripts/warehouse_connect.py init --from-file mon_compte.env
    python scripts/warehouse_connect.py check
    python scripts/warehouse_connect.py config codex      # ou claude-code, claude-desktop, gemini, opencode, cursor, vscode, json

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
        'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD', 'WAREHOUSE_DB_SSLMODE',
        'WAREHOUSE_DB_SSLROOTCERT', 'WAREHOUSE_DB_EXPIRES', 'WAREHOUSE_DB_PASSWORD_STORE')
KEYRING_SERVICE = 'neolab-warehouse'
EXPIRY_NOTICE_DAYS = 14
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


def keyring_account(values):
    return '%s@%s:%s/%s' % (values['WAREHOUSE_DB_USER'], values['WAREHOUSE_DB_HOST'],
                            values.get('WAREHOUSE_DB_PORT', DEFAULTS['WAREHOUSE_DB_PORT']),
                            values.get('WAREHOUSE_DB_NAME', DEFAULTS['WAREHOUSE_DB_NAME']))


def keyring_module():
    try:
        import keyring
    except ImportError:
        raise SystemExit('Le trousseau du système demande le module Python keyring: pip install keyring')
    return keyring


def load_settings(environ=None):
    """Variables d'environnement d'abord, puis le fichier local, puis les défauts."""
    environ = os.environ if environ is None else environ
    values = dict(DEFAULTS)
    path = credentials_path()
    if path.exists():
        values.update({k: v for k, v in parse_env(path.read_text(encoding='utf-8')).items() if k in KEYS})
    values.update({k: environ[k] for k in KEYS if environ.get(k)})
    if values.get('WAREHOUSE_DB_PASSWORD_STORE') == 'keyring' and not values.get('WAREHOUSE_DB_PASSWORD') \
            and values.get('WAREHOUSE_DB_USER') and values.get('WAREHOUSE_DB_HOST'):
        secret = keyring_module().get_password(KEYRING_SERVICE, keyring_account(values))
        if not secret:
            raise SystemExit('Mot de passe absent du trousseau du système: refaire init --keyring.')
        values['WAREHOUSE_DB_PASSWORD'] = secret
    missing = [k for k in ('WAREHOUSE_DB_HOST', 'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD') if not values.get(k)]
    if missing:
        raise SystemExit('Identifiants absents (%s). Lancer: python scripts/warehouse_connect.py init '
                         '--from-file <fichier remis par l\'administrateur>' % ', '.join(missing))
    return values


def build_dsn(values):
    dsn = 'postgres://%s:%s@%s:%s/%s?sslmode=%s' % (
        quote(values['WAREHOUSE_DB_USER'], safe=''), quote(values['WAREHOUSE_DB_PASSWORD'], safe=''),
        values['WAREHOUSE_DB_HOST'], values['WAREHOUSE_DB_PORT'],
        quote(values['WAREHOUSE_DB_NAME'], safe=''), quote(values['WAREHOUSE_DB_SSLMODE'], safe=''))
    if values.get('WAREHOUSE_DB_SSLROOTCERT'):
        # Certificate authority of the server: required to verify its identity (verify-full).
        dsn += '&sslrootcert=' + quote(values['WAREHOUSE_DB_SSLROOTCERT'], safe='')
    return dsn


# DbHub's connection errors, mapped to the action the person can take. Matched
# on its stderr, which is never printed as is (it can echo the DSN).
DIAGNOSES = (
    ('password authentication failed', 'identifiants refusés: mot de passe faux, renouvelé (rotate) ou expiré. '
                                       'Demander un nouveau fichier à l\'administrateur.'),
    ('no encryption', 'le serveur exige une connexion chiffrée: WAREHOUSE_DB_SSLMODE=require.'),
    ('rejects connection', 'le serveur refuse ce poste ou ce compte (pg_hba): contacter l\'administrateur.'),
    ('does not support ssl', 'le serveur ne propose pas TLS: WAREHOUSE_DB_SSLMODE=disable, uniquement en local ou via tunnel SSH.'),
    ('certificate', 'certificat du serveur non vérifiable: indiquer son certificat d\'autorité '
                    '(WAREHOUSE_DB_SSLROOTCERT) ou utiliser WAREHOUSE_DB_SSLMODE=require.'),
    ('econnrefused', 'serveur injoignable sur cet hôte et ce port: service arrêté, port fermé ou tunnel SSH absent.'),
    ('enotfound', 'nom d\'hôte inconnu: vérifier WAREHOUSE_DB_HOST.'),
    ('etimedout', 'délai réseau dépassé: pare-feu, VPN ou tunnel requis.'),
    ('timeout', 'délai réseau dépassé: pare-feu, VPN ou tunnel requis.'),
    ('does not exist', 'base ou compte inexistant: vérifier WAREHOUSE_DB_NAME et le compte.'),
)


def diagnose(stderr_text):
    lowered = stderr_text.lower()
    for marker, message in DIAGNOSES:
        if marker in lowered:
            return message
    return 'DbHub s\'est arrêté sans cause reconnue (connexion refusée, identifiants ou réseau).'


def expiry_status(values, today=None):
    """Message about the password's validity, from the date in the credentials file."""
    raw = values.get('WAREHOUSE_DB_EXPIRES')
    if not raw:
        return None
    from datetime import date
    try:
        expires = date.fromisoformat(raw)
    except ValueError:
        return None
    days = (expires - (today or date.today())).days
    if days < 0:
        return 'Mot de passe expiré le %s: demander `rotate` à l\'administrateur.' % raw
    if days <= EXPIRY_NOTICE_DAYS:
        return 'Mot de passe valide jusqu\'au %s (%d jour(s)): prévoir son renouvellement.' % (raw, days)
    return 'Mot de passe valide jusqu\'au %s.' % raw


def dbhub_command():
    override = os.environ.get('WAREHOUSE_DBHUB_COMMAND')
    if override:
        return override.split()
    base = ['--transport', 'stdio', '--config', str(CONFIG)]
    if LOCAL_DBHUB.exists():
        return [shutil.which('node') or 'node', str(LOCAL_DBHUB), *base]
    npx = shutil.which('npx') or shutil.which('npx.cmd')
    if not npx:
        raise SystemExit('Node.js 18+ est requis (https://nodejs.org) pour lancer DbHub.')
    return [npx, '-y', DBHUB_PACKAGE, *base]


def dbhub_origin():
    if os.environ.get('WAREHOUSE_DBHUB_COMMAND'):
        return 'commande personnalisée'
    return 'installation locale' if LOCAL_DBHUB.exists() else 'npx (téléchargé au premier lancement)'


def install_dbhub(_args):
    """Install the pinned DbHub next to the repo so later starts need no network."""
    npm = shutil.which('npm') or shutil.which('npm.cmd')
    if not npm:
        raise SystemExit('Node.js 18+ (avec npm) est requis: https://nodejs.org')
    prefix = LOCAL_DBHUB.parents[4]  # data/tooling/dbhub
    prefix.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([npm, 'install', '--no-audit', '--no-fund', '--prefix', str(prefix), DBHUB_PACKAGE])
    if result.returncode or not LOCAL_DBHUB.exists():
        raise SystemExit('Installation de DbHub échouée (réseau npm requis une fois).')
    print('DbHub %s installé dans %s: les lancements suivants n\'ont plus besoin du réseau.' % (DBHUB_PACKAGE, prefix))
    return 0


def server_environment(values, application='neolab-mcp'):
    env = dict(os.environ)
    env['WAREHOUSE_DSN'] = build_dsn(values)
    # Names the agent in the server's query audit (docs/WAREHOUSE_AUDIT.md). DbHub drops
    # application_name from the DSN; node-postgres reads PGAPPNAME instead.
    env['PGAPPNAME'] = application
    return env


def agent_application_name(initialize_line):
    """'neolab-mcp:<agent>' from the client's first MCP message, so the server audit shows
    which agent ran each query. Older protocol versions send clientInfo in `initialize`;
    2026-07-28 (Claude Code 2.1) opens with `server/discover` and puts it in params._meta."""
    try:
        params = json.loads(initialize_line).get('params') or {}
        info = params.get('clientInfo') or (params.get('_meta') or {}).get('io.modelcontextprotocol/clientInfo') or {}
        name = info.get('name')
    except (ValueError, AttributeError, TypeError):
        return 'neolab-mcp'
    if not name:
        return 'neolab-mcp'
    cleaned = ''.join(c for c in str(name) if c.isalnum() or c in '._-')[:40]
    return 'neolab-mcp:' + cleaned if cleaned else 'neolab-mcp'


def trace_paths():
    base = credentials_path().parent
    return base / 'trace.on', base / 'trace.jsonl'


def summarize_result(message):
    """Debug summary of a tools/call response: status, rows, truncation, size, preview."""
    if 'error' in message:
        return {'status': 'erreur', 'error': str(message['error'].get('message', message['error']))[:500]}
    result = message.get('result') or {}
    text = ''.join(part.get('text', '') for part in result.get('content', []) if isinstance(part, dict))
    summary = {'status': 'erreur' if result.get('isError') else 'ok', 'bytes': len(text.encode('utf-8'))}
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None

    def walk(node):
        if isinstance(node, dict):
            if node.get('success') is False and node.get('error'):
                summary['status'] = 'erreur'
                summary['error'] = str(node['error'])[:500]
            if node.get('truncated') is True:
                summary['truncated'] = True
            if isinstance(node.get('rows'), list):
                summary['rows'] = summary.get('rows', 0) + len(node['rows'])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(payload)
    summary['preview'] = text[:300]
    return summary


# Sent to the agent with the server's answer to `initialize` (MCP "instructions"): agents that
# support it add this to their context from the first message, so a short question such as
# "combien de copépodes ?" is read as a question about this warehouse, not about the world.
SERVER_INSTRUCTIONS = (
    "Ce serveur donne accès en lecture au warehouse NeoLab (Université Laval) : plancton et océan en Arctique "
    "canadien (Baie de Baffin, détroit de Davis, mer du Labrador, baie d'Hudson...). Il contient les objets et "
    "annotations EcoTaxa (taxons, statut validé/prédit, tailles), les profils et abondances UVP/EcoPart, les CTD "
    "Amundsen (température, salinité, sigma-t, oxygène, nitrate, fluorescence, pH) et les zones maritimes. "
    "Une question sur le plancton, les copépodes, l'UVP, EcoTaxa, les CTD, une campagne, une zone ou ces mesures "
    "porte sur ces données, même courte : y répondre avec execute_sql, jamais de mémoire ni par une recherche web. "
    "Lire d'abord warehouse_context(topic=overview). Si la question est floue (projet, taxon, profondeur, année, "
    "objets validés ou non), dire le choix retenu ou demander une précision, et donner les requêtes exécutées."
)


def with_instructions(line, initialize_id):
    """Add SERVER_INSTRUCTIONS to DbHub's answer to the agent's initialize; any other line unchanged."""
    try:
        message = json.loads(line)
    except ValueError:
        return line
    if not isinstance(message, dict) or message.get('id') != initialize_id or not isinstance(message.get('result'), dict):
        return line
    own = message['result'].get('instructions')
    message['result']['instructions'] = SERVER_INSTRUCTIONS + ('\n\n' + own if own else '')
    return (json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8')


def relay(command, values, trace_file=None):
    """Pass MCP messages between the agent (stdin/stdout) and DbHub, line by line
    (MCP stdio messages are newline-delimited JSON). DbHub starts once the agent's
    initialize arrives, to tag its connection with the agent's name; with tracing
    on, each request/response pair is appended to a private JSONL file."""
    import threading
    import time
    from datetime import datetime, timezone
    first = sys.stdin.buffer.readline()
    if not first:
        return 0
    application = agent_application_name(first)
    try:
        initialize_id = json.loads(first).get('id')
    except (ValueError, AttributeError):
        initialize_id = None
    child = subprocess.Popen(command, env=server_environment(values, application),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    pending, lock = {}, threading.Lock()
    agent = application.split(':', 1)[1] if ':' in application else '?'

    def record(entry):
        if trace_file is None:
            return
        line = json.dumps(entry, ensure_ascii=False) + '\n'
        with lock:
            descriptor = os.open(trace_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, 'a', encoding='utf-8') as handle:
                handle.write(line)

    def note_request(raw):
        if trace_file is None:
            return
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if isinstance(message, dict) and 'id' in message and 'method' in message:
            params = message.get('params') or {}
            with lock:
                pending[message['id']] = (time.monotonic(), message['method'], params.get('name'),
                                          params.get('arguments'))

    def to_server():
        line = first
        try:
            while line:
                note_request(line)
                child.stdin.write(line)
                child.stdin.flush()
                line = sys.stdin.buffer.readline()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    threading.Thread(target=to_server, daemon=True).start()
    for line in iter(child.stdout.readline, b''):
        if initialize_id is not None:
            updated = with_instructions(line, initialize_id)
            if updated is not line:
                initialize_id = None  # done: only the answer to initialize carries the instructions
            line = updated
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
        if trace_file is None:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or 'id' not in message or 'method' in message:
            continue
        with lock:
            started = pending.pop(message['id'], None)
        if started is None:
            continue
        began, method, tool, arguments = started
        entry = {'time': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'agent': agent,
                 'method': method, 'duration_ms': round((time.monotonic() - began) * 1000)}
        if method == 'tools/call':
            entry.update({'tool': tool, 'arguments': arguments, **summarize_result(message)})
        elif 'error' in message:
            entry.update({'status': 'erreur', 'error': str(message['error'])[:500]})
        record(entry)
    return child.wait()


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
                  'WAREHOUSE_DB_SSLMODE': args.sslmode, 'WAREHOUSE_DB_SSLROOTCERT': args.sslrootcert,
                  'WAREHOUSE_DB_PASSWORD': os.environ.get('WAREHOUSE_DB_PASSWORD') or getpass.getpass('Mot de passe: ')}
    values = {**DEFAULTS, **{k: v for k, v in values.items() if k in KEYS and v}}
    if args.from_file and args.sslrootcert:
        values['WAREHOUSE_DB_SSLROOTCERT'] = args.sslrootcert
    missing = [k for k in ('WAREHOUSE_DB_HOST', 'WAREHOUSE_DB_USER', 'WAREHOUSE_DB_PASSWORD') if not values.get(k)]
    if missing:
        raise SystemExit('Valeurs manquantes: ' + ', '.join(missing))
    stored = dict(values)
    if args.keyring:
        # The password goes to the OS keychain; the file keeps only non-secret settings.
        keyring_module().set_password(KEYRING_SERVICE, keyring_account(values), values['WAREHOUSE_DB_PASSWORD'])
        stored.pop('WAREHOUSE_DB_PASSWORD')
        stored['WAREHOUSE_DB_PASSWORD_STORE'] = 'keyring'
    else:
        stored.pop('WAREHOUSE_DB_PASSWORD_STORE', None)
    path = credentials_path()
    write_private(path, ''.join('%s=%s\n' % (k, stored[k]) for k in KEYS if stored.get(k)))
    print('Identifiants enregistrés: %s (compte %s%s). Ils ne sont pas dans le dépôt.' % (
        path, values['WAREHOUSE_DB_USER'], '; mot de passe dans le trousseau du système' if args.keyring else ''))
    print('Suite: python scripts/warehouse_connect.py check')
    return 0


def run(_args):
    marker, log = trace_paths()
    return relay(dbhub_command(), load_settings(), log if marker.exists() else None)


def trace(args):
    """Debug trace of the agent's tool calls, local to this machine (trace on|off|show)."""
    marker, log = trace_paths()
    if args.action == 'on':
        write_private(marker, 'on\n')
        print('Trace activée: chaque appel d\'outil de l\'agent (SQL, durée, lignes, erreurs, extrait du résultat)')
        print('sera ajouté à %s (fichier privé, sur ce poste seulement).' % log)
        print('Redémarrer l\'agent pour qu\'il relance le serveur. Désactiver: trace off.')
        return 0
    if args.action == 'off':
        marker.unlink(missing_ok=True)
        print('Trace désactivée (le fichier %s est conservé; le supprimer si besoin).' % log)
        return 0
    if args.action == 'clear':
        log.unlink(missing_ok=True)
        print('Trace effacée.')
        return 0
    print('Trace %s; fichier: %s' % ('ACTIVE' if marker.exists() else 'inactive', log))
    if not log.exists():
        print('Aucun appel enregistré.')
        return 0
    entries = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
    for entry in entries[-args.last:]:
        what = entry.get('tool') or entry.get('method')
        arguments = entry.get('arguments') or {}
        detail = arguments.get('sql') or arguments.get('topic') or (
            ' '.join('%s=%s' % kv for kv in arguments.items()) if arguments else '')
        detail = ' '.join(str(detail).split())
        if not args.full and len(detail) > 140:
            detail = detail[:137] + '...'
        outcome = entry.get('status', 'ok')
        if 'rows' in entry:
            outcome += ', %d ligne(s)' % entry['rows']
        if entry.get('truncated'):
            outcome += ', TRONQUÉ'
        if entry.get('error'):
            outcome += ': ' + entry['error'][:160]
        print('%s  %-12s %-18s %6d ms  %s' % (entry['time'][:19], entry.get('agent', '?')[:12], what[:18],
                                             entry.get('duration_ms', 0), outcome))
        if detail:
            print('    ' + detail)
    return 0


def registration(client):
    script = str(Path(__file__).resolve())
    python = sys.executable
    if client == 'codex':
        # startup_timeout_sec: Codex abandons a server that has not answered within
        # 10 s by default; the first `npx` download of DbHub can take longer.
        return ('# Option 1: ligne de commande\n'
                'codex mcp add %s -- "%s" "%s" run\n\n'
                '# Option 2: ~/.codex/config.toml\n'
                '[mcp_servers.%s]\ncommand = "%s"\nargs = ["%s", "run"]\nstartup_timeout_sec = 30\n'
                % (SERVER_NAME, python, script, SERVER_NAME, python, script))
    if client == 'gemini':
        return ('# Pour vous seul, tous projets (~/.gemini/settings.json):\n'
                'gemini mcp add -s user %s "%s" "%s" run\n\n'
                '# Gemini désactive tout serveur MCP dans un dossier non approuvé: lancer gemini\n'
                '# depuis un dossier de travail approuvé (invite au premier lancement, ou /permissions).\n'
                % (SERVER_NAME, python, script))
    if client == 'opencode':
        return ('Ajouter dans ~/.config/opencode/opencode.json (tous projets) ou opencode.json à la racine du projet\n'
                '(fusionner la clé "mcp" si le fichier existe déjà). Vérifier: opencode mcp list\n%s\n'
                % json.dumps({'$schema': 'https://opencode.ai/config.json',
                              'mcp': {SERVER_NAME: {'type': 'local', 'command': [python, script, 'run'],
                                                    'enabled': True}}}, indent=2))
    if client == 'cursor':
        return ('Ajouter dans ~/.cursor/mcp.json (tous projets) ou .cursor/mcp.json (ce projet):\n%s\n'
                % registration('json'))
    if client == 'vscode':
        return ('Ajouter dans .vscode/mcp.json (VS Code / GitHub Copilot, mode agent):\n%s\n'
                % json.dumps({'servers': {SERVER_NAME: {'type': 'stdio', 'command': python,
                                                        'args': [script, 'run']}}}, indent=2))
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
    # On stderr: `config json > mcp.json` must produce a valid JSON file.
    print('Les identifiants restent dans %s; redémarrer le client pour charger le serveur.' % credentials_path(),
          file=sys.stderr)
    return 0


class McpSession:
    """Client MCP minimal sur le processus DbHub (une réponse par id)."""

    def __init__(self, command, env):
        import threading
        self.process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        self.next_id = 0
        # Kept for diagnosis only, never printed: DbHub may echo the connection string.
        self.stderr_lines = []
        self.reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self.reader.start()

    def _drain_stderr(self):
        for line in self.process.stderr:
            self.stderr_lines.append(line)

    def stderr_text(self):
        self.reader.join(timeout=2)
        return ''.join(self.stderr_lines)

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
    print('Compte %s sur %s:%s/%s (TLS: %s; DbHub: %s)' % (
        values['WAREHOUSE_DB_USER'], values['WAREHOUSE_DB_HOST'], values['WAREHOUSE_DB_PORT'],
        values['WAREHOUSE_DB_NAME'], values['WAREHOUSE_DB_SSLMODE'], dbhub_origin()))
    expiry = expiry_status(values)
    session = McpSession(dbhub_command(), server_environment(values, 'neolab-check'))
    steps = []
    if expiry:
        steps.append(('validité du mot de passe', 'expiré' not in expiry, expiry))
    try:
        session.request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                       'clientInfo': {'name': 'neolab-check', 'version': '1'}})
        session.notify('notifications/initialized')
        tools = {tool['name'] for tool in session.request('tools/list', {})['tools']}
        missing = {'execute_sql', 'warehouse_context'} - tools
        steps.append(('outils MCP', not missing, 'manquants: %s' % ', '.join(sorted(missing)) if missing else ', '.join(sorted(tools))))
        who = session.sql("SELECT current_user AS role, current_setting('transaction_read_only') AS read_only")[0]
        steps.append(('compte et lecture seule', who['read_only'] == 'on', '%s, lecture seule=%s' % (who['role'], who['read_only'])))
        scope = session.sql('SELECT grantee, source_instance, contract, zone_key, year_min, year_max FROM catalogue.my_access')
        steps.append(('périmètre (catalogue.my_access)', True, '; '.join(
            ' / '.join(str(row[k]) for k in ('grantee', 'source_instance', 'contract', 'zone_key', 'year_min', 'year_max') if row.get(k) is not None)
            for row in scope) or 'aucun droit accordé: aucune donnée lisible'))
        readable = session.sql('SELECT my_scope, count(*) AS n FROM catalogue.my_datasets GROUP BY 1 ORDER BY 1')
        notes = session.sql('SELECT DISTINCT note FROM catalogue.my_datasets WHERE note IS NOT NULL')
        steps.append(('jeux lisibles (catalogue.my_datasets)', True, (', '.join(
            '%s: %s' % (row['my_scope'], row['n']) for row in readable) or 'aucune version chargée dans la base')
            + ''.join('. ' + row['note'] for row in notes)))
        catalog = session.sql('SELECT count(*) AS n FROM catalogue.dataset_catalog')[0]['n']
        steps.append(('catalogue (catalogue.dataset_catalog)', True, '%s version(s) décrite(s)' % catalog))
        context = session.request('tools/call', {'name': 'warehouse_context', 'arguments': {'topic': 'overview'}})
        steps.append(('contexte métier (warehouse_context)', not context.get('isError'), 'fiche overview lue'))
    except Exception as error:  # noqa: BLE001 - toute erreur est un échec de recette, sans détail secret
        if session.process.poll() is not None or 'arrêté' in str(error):
            steps.append(('connexion', False, diagnose(session.stderr_text())))
        else:
            steps.append(('requête', False, str(error)))
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
    p.add_argument('--sslmode', default='require', choices=('disable', 'prefer', 'require', 'verify-ca', 'verify-full'))
    p.add_argument('--sslrootcert', help='certificat d\'autorité du serveur (pour verify-ca / verify-full)')
    p.add_argument('--keyring', action='store_true',
                   help='ranger le mot de passe dans le trousseau du système (module keyring) plutôt que dans le fichier')
    p.set_defaults(handler=init)
    sub.add_parser('check', help='recette complète: connexion, rôle, périmètre, catalogue').set_defaults(handler=check)
    sub.add_parser('run', help='lancer le serveur MCP (commande enregistrée dans le client)').set_defaults(handler=run)
    sub.add_parser('install-dbhub', help='installer DbHub localement (une fois, réseau npm requis)').set_defaults(handler=install_dbhub)
    p = sub.add_parser('trace', help='débogage: journal local des appels d\'outils de l\'agent (on, off, show, clear)')
    p.add_argument('action', choices=('on', 'off', 'show', 'clear'))
    p.add_argument('--last', type=int, default=20, help='show: nombre d\'appels affichés (défaut 20)')
    p.add_argument('--full', action='store_true', help='show: SQL complet')
    p.set_defaults(handler=trace)
    p = sub.add_parser('config', help='afficher la commande ou le fragment de configuration du client')
    p.add_argument('client', choices=('codex', 'claude-code', 'claude-desktop', 'gemini', 'opencode', 'cursor', 'vscode', 'json'))
    p.set_defaults(handler=config)
    args = parser.parse_args(argv)
    if args.command == 'init' and not args.from_file and not (args.host and args.user):
        parser.error('init: --from-file, ou --host et --user')
    return args.handler(args)


if __name__ == '__main__':
    sys.exit(main())
