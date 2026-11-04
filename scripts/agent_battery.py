#!/usr/bin/env python3
"""Rejouer une batterie de questions sur un agent IA branché au warehouse par MCP, et noter ses réponses.

Chaque cas (tests/agent_battery/*.json) donne une question de chercheur et la requête SQL qui calcule la
bonne réponse dans la base, au moment du test : les attendus suivent les données. L'agent (Claude Code)
reçoit un compte personnel temporaire, en lecture seule, branché par DbHub comme pour un utilisateur;
aucun mot de passe de la base n'est dans son environnement. Il travaille dans un dossier vide par question.

    python scripts/agent_battery.py                            # tous les cas, 5 agents à la fois
    python scripts/agent_battery.py --only baffin_samples      # un seul cas
    python scripts/agent_battery.py --cases tests/agent_battery/ecotaxa_cases.json --parallel 3

Note d'un cas : chaque nombre attendu (non nul) doit apparaître dans la réponse (entier exact; décimal à
`tolerance` près), chaque motif `must_mention` doit être trouvé, et les nombres de `must_not_sql` ne doivent
pas apparaître. Connexion propriétaire : WAREHOUSE_POSTGRES_* (environnement ou .env.warehouse), utilisée
seulement pour les attendus et le compte temporaire. Rapport : <out>/report.md et report.json.
Code de sortie : 0 tout réussi, 1 au moins un échec, 2 erreur d'exécution.
Coût : chaque question est une session d'agent facturée (≈ 0,10 à 0,25 $ au tarif API).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / 'tests/agent_battery/ecotaxa_cases.json'
MCP_TOOLS = ('mcp__neolab-warehouse__execute_sql', 'mcp__neolab-warehouse__search_objects',
             'mcp__neolab-warehouse__warehouse_context')
SECRET_PREFIXES = ('WAREHOUSE_', 'PG', 'ECOTAXA_', 'NEOLAB_')
# A number as an agent writes it in French: 1 687 393 (space, no-break or narrow no-break space
# between thousands), 2,23 or 2.23 for decimals.
NUMBER = re.compile(r'(?<![\w.,])-?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\d])')


def numbers_in(text: str) -> list[float]:
    found = []
    for match in NUMBER.findall(text):
        cleaned = re.sub(r'[   ]', '', match).replace(',', '.')
        try:
            found.append(float(cleaned))
        except ValueError:
            continue
    return found


def present(value: float, found: list[float], tolerance: float | None) -> bool:
    if tolerance is None:
        tolerance = 0 if float(value).is_integer() else max(abs(value) * 0.005, 0.005)
    return any(abs(f - value) <= tolerance + 1e-9 for f in found)


def grade(case: dict, answer: str, expected: list[float], forbidden: list[float]) -> dict:
    found = numbers_in(answer)
    tolerance = case.get('tolerance')
    missing = [v for v in expected if v != 0 and not present(v, found, tolerance)]
    mentions = [p for p in case.get('must_mention', []) if not re.search(p, answer)]
    wrong = [v for v in forbidden if v != 0 and present(v, found, 0)]
    return {'passed': not (missing or mentions or wrong), 'missing_values': missing,
            'missing_mentions': mentions, 'forbidden_values_found': wrong}


def owner_connection():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env.warehouse')
    except ImportError:
        pass
    import psycopg
    if not os.getenv('WAREHOUSE_POSTGRES_PASSWORD'):
        raise SystemExit('WAREHOUSE_POSTGRES_PASSWORD est requis (compte propriétaire, pour les attendus).')
    return psycopg.connect(host=os.getenv('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
                           port=os.getenv('WAREHOUSE_POSTGRES_PORT', '55432'),
                           dbname=os.getenv('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
                           user=os.getenv('WAREHOUSE_POSTGRES_USER', 'neolab'),
                           password=os.environ['WAREHOUSE_POSTGRES_PASSWORD'])


def values(conn, query: str | None) -> list[float]:
    if not query:
        return []
    rows = conn.execute(query).fetchall()
    return [float(v) for row in rows for v in row if v is not None]


def agent_env() -> dict:
    """The agent's environment: everything it needs to run, no database or source credential."""
    return {k: v for k, v in os.environ.items() if not k.startswith(SECRET_PREFIXES)}


def run_case(case: dict, out: Path, mcp_config: Path, model: str | None, timeout: int) -> dict:
    work = out / case['id']
    work.mkdir(parents=True, exist_ok=True)
    command = ['claude', '-p', case['question'], '--mcp-config', str(mcp_config), '--strict-mcp-config',
               '--allowedTools', ','.join(MCP_TOOLS), '--output-format', 'stream-json', '--verbose']
    if model:
        command += ['--model', model]
    started = time.time()
    with open(out / f"{case['id']}.jsonl", 'w') as log, open(out / f"{case['id']}.err", 'w') as err:
        try:
            code = subprocess.run(command, cwd=work, env=agent_env(), stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=err, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    result = {'id': case['id'], 'exit': code, 'seconds': round(time.time() - started), 'answer': '',
              'turns': None, 'cost_usd': None, 'sql_queries': 0}
    for line in (out / f"{case['id']}.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') == 'assistant':
            for item in event['message'].get('content', []):
                if item.get('type') == 'tool_use' and item['name'].endswith('execute_sql'):
                    result['sql_queries'] += 1
        if event.get('type') == 'result':
            result.update(answer=event.get('result') or '', turns=event.get('num_turns'),
                          cost_usd=event.get('total_cost_usd'))
    return result


def temporary_account(tmp: Path) -> tuple[str, Path, Path]:
    name = 'battery_' + uuid.uuid4().hex[:8]
    env = dict(os.environ)
    subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_user.py'), 'create', name, '--all-access',
                    '--note', 'batterie de tests agent (temporaire)', '--out-dir', str(tmp)],
                   env=env, check=True, capture_output=True, text=True)
    credentials = tmp / 'credentials.env'
    subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_connect.py'), 'init', '--from-file', str(tmp / f'{name}.env')],
                   env=dict(env, NEOLAB_WAREHOUSE_CREDENTIALS=str(credentials)), check=True, capture_output=True, text=True)
    (tmp / f'{name}.env').unlink()
    mcp = tmp / 'mcp.json'
    mcp.write_text(json.dumps({'mcpServers': {'neolab-warehouse': {
        'command': sys.executable, 'args': [str(ROOT / 'scripts/warehouse_connect.py'), 'run'],
        'env': {'NEOLAB_WAREHOUSE_CREDENTIALS': str(credentials)}}}}))
    return name, credentials, mcp


def show(value: float) -> str:
    return f'{int(value):,}'.replace(',', '\u202f') if float(value).is_integer() else f'{value:g}'.replace('.', ',')


def report(out: Path, results: list[dict]) -> str:
    passed = sum(r['grade']['passed'] for r in results)
    cost = sum(r['cost_usd'] or 0 for r in results)
    lines = [f'# Batterie agent — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC', '',
             f'**{passed}/{len(results)} réussis** · {sum(r["turns"] or 0 for r in results)} tours · '
             f'{sum(r["sql_queries"] for r in results)} requêtes SQL · coût estimé {cost:.2f} $ (tarif API)', '',
             '| Cas | Résultat | Attendu | Manque | Durée | Tours |', '|---|---|---|---|---|---|']
    for r in results:
        g = r['grade']
        manque = '; '.join(filter(None, [
            ', '.join(show(v) for v in g['missing_values']),
            ', '.join(g['missing_mentions']),
            ('interdit trouvé : ' + ', '.join(show(v) for v in g['forbidden_values_found'])) if g['forbidden_values_found'] else '']))
        lines.append(f"| {r['id']} | {'✓' if g['passed'] else '✗'} | {', '.join(show(v) for v in r['expected'])} | "
                     f"{manque or '—'} | {r['seconds']} s | {r['turns']} |")
    lines += ['', 'Réponses complètes : <cas>.jsonl (flux de l\'agent) et report.json.']
    text = '\n'.join(lines) + '\n'
    (out / 'report.md').write_text(text, encoding='utf-8')
    (out / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    ap.add_argument('--only', help='identifiants de cas séparés par des virgules')
    ap.add_argument('--parallel', type=int, default=5)
    ap.add_argument('--out', type=Path, help='dossier du rapport (défaut : data/agent_battery/<date>)')
    ap.add_argument('--model', help='modèle de l\'agent (défaut : celui de Claude Code)')
    ap.add_argument('--timeout', type=int, default=1200, help='secondes par question')
    args = ap.parse_args(argv)
    if not shutil.which('claude'):
        print('Claude Code (commande claude) est introuvable.', file=sys.stderr)
        return 2
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    if args.only:
        wanted = set(args.only.split(','))
        cases = [c for c in cases if c['id'] in wanted]
    out = args.out or ROOT / 'data/agent_battery' / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    with owner_connection() as conn:
        expected = {c['id']: (values(conn, c['expect_sql']), values(conn, c.get('must_not_sql'))) for c in cases}
    tmp = Path(tempfile.mkdtemp(prefix='agent_battery_'))
    os.chmod(tmp, 0o700)
    name = None
    try:
        name, _, mcp = temporary_account(tmp)
        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            results = list(pool.map(lambda c: run_case(c, out, mcp, args.model, args.timeout), cases))
    finally:
        if name:
            subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_user.py'), 'offboard', name],
                           capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)
    for case, result in zip(cases, results):
        result['question'] = case['question']
        result['expected'], forbidden = expected[case['id']]
        result['grade'] = grade(case, result['answer'], result['expected'], forbidden)
    print(report(out, results))
    print(f'Rapport : {out / "report.md"}')
    return 0 if all(r['grade']['passed'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
