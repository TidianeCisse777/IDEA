#!/usr/bin/env python3
"""Rejouer une batterie de questions sur un agent IA branché au warehouse par MCP, et noter ses réponses.

Chaque cas (tests/agent_battery/*.json) donne une question de chercheur et la requête SQL qui calcule la
bonne réponse dans la base, au moment du test : les attendus suivent les données. L'agent (Claude Code)
reçoit un compte personnel temporaire, en lecture seule, branché par DbHub comme pour un utilisateur;
aucun mot de passe de la base n'est dans son environnement. Il travaille dans un dossier vide par question.

    python scripts/agent_battery.py                            # tous les cas, 5 agents à la fois
    python scripts/agent_battery.py --only baffin_samples      # un seul cas
    (dossiers de travail et rapport : ~/neolab_agent_battery/<date>, hors du dépôt)
    python scripts/agent_battery.py --cases tests/agent_battery/ecotaxa_cases.json --parallel 3

Note d'un cas : chaque nombre attendu (non nul) doit apparaître dans la réponse (entier exact; décimal à
`tolerance` près), chaque motif `must_mention` doit être trouvé, et les nombres de `must_not_sql` ne doivent
pas apparaître. Connexion propriétaire : WAREHOUSE_POSTGRES_* (environnement ou .env.warehouse), utilisée
seulement pour les attendus et le compte temporaire. Rapport : <out>/report.md et report.json.
`expect_sql` peut être une liste de requêtes : plusieurs bonnes réponses possibles, une seule doit être satisfaite.
Code de sortie : 0 tout réussi, 1 au moins un échec, 2 cas non exécutés (limite d'usage de l'agent) ou erreur d'exécution.
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
MCP_TOOLS = ('mcp__neolab-warehouse__run_sql_query', 'mcp__neolab-warehouse__find_tables_and_columns',
             'mcp__neolab-warehouse__read_data_guide')
# A case with "tools": "files" (charts, maps) may also write and run code in its own empty folder.
FILE_TOOLS = ('Bash', 'Write', 'Read', 'Edit', 'Glob')
DATA_SUFFIXES = ('.csv', '.tsv', '.json', '.md', '.txt')
SECRET_PREFIXES = ('WAREHOUSE_', 'PG', 'ECOTAXA_', 'NEOLAB_')
# A number as an agent writes it in French: 1 687 393 (space, no-break or narrow no-break space
# between thousands), 2,23 or 2.23 for decimals.
NUMBER = re.compile(r'(?<![\w.,])-?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\d])')


def numbers_in(text: str) -> list[float]:
    found = []
    text = text.replace('\u2212', '-')  # agents often write the true minus sign: −0,2 °C
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


def produced_files(work: Path) -> list[str]:
    return sorted(str(p.relative_to(work)) for p in work.rglob('*') if p.is_file())


def files_text(work: Path, limit: int = 2_000_000) -> str:
    """Text of the data files an agent wrote (the CSV it plotted, its provenance notes)."""
    parts = []
    for path in sorted(work.rglob('*')):
        if path.is_file() and path.suffix.lower() in DATA_SUFFIXES and path.stat().st_size <= limit:
            parts.append(path.read_text(encoding='utf-8', errors='replace'))
    return '\n'.join(parts)


def grade(case: dict, answer: str, expected: list[float], forbidden: list[float], work: Path | None = None,
          sql_queries: int | None = None) -> dict:
    searched = answer
    if case.get('values_in') == 'answer_and_files' and work is not None:
        searched = answer + '\n' + files_text(work)
    found = numbers_in(searched)
    tolerance = case.get('tolerance')
    missing = [v for v in expected if v != 0 and not present(v, found, tolerance)]
    mentions = [p for p in case.get('must_mention', []) if not re.search(p, answer)]
    wrong = [v for v in forbidden if v != 0 and present(v, numbers_in(answer), 0)]
    files = produced_files(work) if work is not None and work.exists() else []
    absent = [pattern for pattern in case.get('expect_files', [])
              if not any(Path(f).match(pattern) for f in files)]
    # An answer about the data must come from the data: without one query, it is from memory.
    no_query = sql_queries is not None and sql_queries == 0
    return {'passed': not (missing or mentions or wrong or absent or no_query), 'missing_values': missing,
            'answered_without_querying': no_query,
            'missing_mentions': mentions, 'forbidden_values_found': wrong, 'missing_files': absent, 'files': files}


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


TURN_FIELDS = ('question', 'expect_sql', 'must_mention', 'must_not_sql', 'tolerance', 'values_in', 'expect_files')


# The agent's own usage limit is not an agent error: such a case is reported as not run.
USAGE_LIMIT = re.compile(r"(?i)hit your .{0,40}limit|usage limit|rate limit")


def turns_of(case: dict) -> list[dict]:
    """A case is one question, or a conversation: "turns", each with its own question and checks."""
    if 'turns' in case:
        return case['turns']
    return [{k: case[k] for k in TURN_FIELDS if k in case}]


def read_stream(path: Path) -> dict:
    run = {'answer': '', 'turns': None, 'cost_usd': None, 'sql_queries': 0, 'session_id': None}
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        run['session_id'] = event.get('session_id') or run['session_id']
        if event.get('type') == 'assistant':
            for item in event['message'].get('content', []):
                if item.get('type') == 'tool_use' and item['name'].endswith('run_sql_query'):
                    run['sql_queries'] += 1
        if event.get('type') == 'result':
            run.update(answer=event.get('result') or '', turns=event.get('num_turns'), cost_usd=event.get('total_cost_usd'))
    return run


def run_case(case: dict, out: Path, mcp_config: Path, model: str | None, timeout: int, workspace: bool = False) -> dict:
    """Ask each turn in the same agent session (--resume), in the case's own empty folder (or, with
    workspace, a NeoLab working folder: the instructions files of warehouse_connect.py workspace)."""
    work = out / case['id']
    work.mkdir(parents=True, exist_ok=True)
    if workspace:
        subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_connect.py'), 'workspace', str(work)],
                       check=True, capture_output=True, text=True)
    tools = MCP_TOOLS + (FILE_TOOLS if case.get('tools') == 'files' else ())
    started, session, conversation, code = time.time(), None, [], 0
    turns = turns_of(case)
    for number, turn in enumerate(turns, 1):
        command = ['claude', '-p', turn['question'], '--mcp-config', str(mcp_config), '--strict-mcp-config',
                   '--allowedTools', ','.join(tools), '--output-format', 'stream-json', '--verbose']
        if session:
            command += ['--resume', session]
        if model:
            command += ['--model', model]
        stem = case['id'] if len(turns) == 1 else f"{case['id']}.t{number}"
        with open(out / f'{stem}.jsonl', 'w') as log, open(out / f'{stem}.err', 'w') as err:
            try:
                code = subprocess.run(command, cwd=work, env=agent_env(), stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=err, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                code = 'timeout'
        run = read_stream(out / f'{stem}.jsonl')
        conversation.append(dict(run, question=turn['question']))
        session = run['session_id']
        if code != 0 or not session:
            break  # a failed turn ends the conversation; the remaining turns count as unanswered
    # e.g. "You've hit your 5-hour limit · resets 6:20am (UTC)": a short answer naming the limit.
    limited = any(len(t['answer'] or '') < 200 and USAGE_LIMIT.search(t['answer'] or '') for t in conversation)
    return {'id': case['id'], 'exit': code, 'seconds': round(time.time() - started), 'not_run': bool(limited),
            'answer': conversation[-1]['answer'] if conversation else '',
            'turns': sum(t['turns'] or 0 for t in conversation),
            'cost_usd': sum(t['cost_usd'] or 0 for t in conversation),
            'sql_queries': sum(t['sql_queries'] for t in conversation), 'conversation': conversation}


def temporary_account(tmp: Path, grant: list[str] | None = None) -> tuple[str, Path, Path]:
    """A read account for the agent: everything (default), or the rights a case names in "account"
    (warehouse_user.py create options, e.g. ["--source", "ecotaxa,ecopart", "--zone", "Baie de Baffin"])."""
    name = 'battery_' + uuid.uuid4().hex[:8]
    home = tmp / name
    home.mkdir(mode=0o700)
    env = dict(os.environ)
    subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_user.py'), 'create', name, *(grant or ['--all-access']),
                    '--note', 'batterie de tests agent (temporaire)', '--out-dir', str(home)],
                   env=env, check=True, capture_output=True, text=True)
    credentials = home / 'credentials.env'
    subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_connect.py'), 'init', '--from-file', str(home / f'{name}.env')],
                   env=dict(env, NEOLAB_WAREHOUSE_CREDENTIALS=str(credentials)), check=True, capture_output=True, text=True)
    (home / f'{name}.env').unlink()
    mcp = home / 'mcp.json'
    mcp.write_text(json.dumps({'mcpServers': {'neolab-warehouse': {
        'command': sys.executable, 'args': [str(ROOT / 'scripts/warehouse_connect.py'), 'run'],
        'env': {'NEOLAB_WAREHOUSE_CREDENTIALS': str(credentials)}}}}))
    return name, credentials, mcp


def merge_grades(per_turn: list[dict], sql_queries: int) -> dict:
    """One verdict per case; a conversation's misses are prefixed with their turn."""
    label = (lambda g, item: f"tour {g['turn']} : {item}") if len(per_turn) > 1 else (lambda g, item: item)
    merged = {'passed': all(g['passed'] for g in per_turn) and sql_queries > 0,
              'answered_without_querying': sql_queries == 0, 'per_turn': per_turn,
              'files': per_turn[-1].get('files', [])}
    for key in ('missing_values', 'missing_mentions', 'forbidden_values_found', 'missing_files'):
        merged[key] = [label(g, show(item)) if len(per_turn) > 1 else item for g in per_turn for item in g.get(key, [])]
    return merged


def show(value) -> str:
    if isinstance(value, str):
        return value
    return f'{int(value):,}'.replace(',', '\u202f') if float(value).is_integer() else f'{value:g}'.replace('.', ',')


def report(out: Path, results: list[dict]) -> str:
    passed = sum(r['grade']['passed'] for r in results)
    not_run = sum(bool(r.get('not_run')) for r in results)
    cost = sum(r['cost_usd'] or 0 for r in results)
    lines = [f'# Batterie agent — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC', '',
             f'**{passed}/{len(results) - not_run} réussis**'
             + (f' · **{not_run} non exécuté(s) : limite d\'usage de l\'agent atteinte, à relancer**' if not_run else '')
             + f' · {sum(r["turns"] or 0 for r in results)} tours · '
             f'{sum(r["sql_queries"] for r in results)} requêtes SQL · coût estimé {cost:.2f} $ (tarif API)', '',
             '| Cas | Résultat | Attendu | Manque | Durée | Tours |', '|---|---|---|---|---|---|']
    for r in results:
        g = r['grade']
        manque = '; '.join(filter(None, [
            ', '.join(show(v) for v in g['missing_values']),
            ', '.join(g['missing_mentions']),
            ('fichier absent : ' + ', '.join(g['missing_files'])) if g.get('missing_files') else '',
            'répondu sans interroger la base' if g.get('answered_without_querying') else '',
            ('interdit trouvé : ' + ', '.join(show(v) for v in g['forbidden_values_found'])) if g['forbidden_values_found'] else '']))
        verdict = 'non exécuté (limite d\'usage)' if r.get('not_run') else ('✓' if g['passed'] else '✗')
        if r.get('not_run'):
            manque = '—'
        lines.append(f"| {r['id']} | {verdict} | {', '.join(show(v) for v in r['expected'])} | "
                     f"{manque or '—'} | {r['seconds']} s | {r['turns']} |")
    figures = [(r['id'], [f for f in r['grade'].get('files', []) if f.lower().endswith(('.png', '.svg', '.html', '.pdf'))])
               for r in results]
    if any(f for _, f in figures):
        lines += ['', '## Figures produites (à regarder : la notation ne juge pas le rendu)', '']
        lines += [f'- {case} : ' + ', '.join(f'`{case}/{f}`' for f in files) for case, files in figures if files]
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
    ap.add_argument('--out', type=Path, help='dossier du rapport et des dossiers de travail des agents, hors du dépôt '
                    '(défaut : ~/neolab_agent_battery/<date>)')
    ap.add_argument('--model', help='modèle de l\'agent (défaut : celui de Claude Code)')
    ap.add_argument('--timeout', type=int, default=1200, help='secondes par question')
    ap.add_argument('--workspace', action='store_true',
                    help='poser les questions dans un dossier de travail NeoLab (warehouse_connect.py workspace) '
                    'plutôt que dans un dossier vide')
    args = ap.parse_args(argv)
    if not shutil.which('claude'):
        print('Claude Code (commande claude) est introuvable.', file=sys.stderr)
        return 2
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    if args.only:
        wanted = set(args.only.split(','))
        cases = [c for c in cases if c['id'] in wanted]
    # Outside the repository: an agent with file tools must not browse the code, docs or local settings.
    out = args.out or Path.home() / 'neolab_agent_battery' / datetime.now().strftime('%Y%m%d_%H%M%S')
    if ROOT in out.resolve().parents:
        print('--out doit être hors du dépôt : un agent pourrait y lire le code et les réglages locaux.', file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    with owner_connection() as conn:
        # expect_sql may list alternatives (several right answers, e.g. a map with or without the profiles
        # placed from their EcoTaxa sample): the answer passes if it carries all values of one of them.
        expected = {c['id']: [([values(conn, q) for q in (t['expect_sql'] if isinstance(t['expect_sql'], list) else [t.get('expect_sql')])],
                               values(conn, t.get('must_not_sql'))) for t in turns_of(c)] for c in cases}
    tmp = Path(tempfile.mkdtemp(prefix='agent_battery_'))
    os.chmod(tmp, 0o700)
    accounts = {}  # one temporary account per distinct "account" of the cases (all-access by default)
    try:
        for case in cases:
            key = json.dumps(case.get('account'))
            if key not in accounts:
                accounts[key] = temporary_account(tmp, case.get('account'))
        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            results = list(pool.map(lambda c: run_case(c, out, accounts[json.dumps(c.get('account'))][2], args.model,
                                                       args.timeout, args.workspace), cases))
    finally:
        for name, _, _ in accounts.values():
            subprocess.run([sys.executable, str(ROOT / 'scripts/warehouse_user.py'), 'remove', name, '--yes'],
                           capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)
    for case, result in zip(cases, results):
        result['question'] = ' / '.join(t['question'] for t in turns_of(case))
        result['expected'], per_turn = [], []
        for number, (turn, (alternatives, forbidden)) in enumerate(zip(turns_of(case), expected[case['id']]), 1):
            answered = result['conversation'][number - 1] if number <= len(result['conversation']) else {'answer': ''}
            grades = [grade(turn, answered['answer'], values_, forbidden, out / case['id']) for values_ in alternatives]
            best = next((i for i, g in enumerate(grades) if g['passed']), 0)
            result['expected'] += alternatives[best]
            per_turn.append(dict(grades[best], turn=number))
        result['grade'] = merge_grades(per_turn, result['sql_queries'])
        result['grade']['not_run'] = result['not_run']
        if result['not_run']:
            result['grade']['passed'] = False
    print(report(out, results))
    print(f'Rapport : {out / "report.md"}')
    if any(not r['grade']['passed'] and not r.get('not_run') for r in results):
        return 1
    return 2 if any(r.get('not_run') for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
