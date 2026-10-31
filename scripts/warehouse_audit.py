#!/usr/bin/env python3
"""Relire l'audit des requêtes du warehouse : qui a lu quoi, quand, et avec quel outil.

Les requêtes des comptes personnels (et de warehouse_reader) sont écrites par PostgreSQL
dans son journal CSV (log_statement par compte, voir docs/WAREHOUSE_AUDIT.md). Ce script le
relit par SQL avec le compte propriétaire, ou depuis des fichiers copiés (--file).

    python scripts/warehouse_audit.py                          # 50 dernières requêtes
    python scripts/warehouse_audit.py --user ines --since 2026-10-01
    python scripts/warehouse_audit.py --summary                # par compte
    python scripts/warehouse_audit.py --errors                 # refus et échecs seulement
    python scripts/warehouse_audit.py --csv > audit.csv        # export complet

Lecture seule : rien n'est modifié, ni dans la base ni dans le journal.
"""
from __future__ import annotations
import argparse
import csv
import io
import os
import sys
from collections import OrderedDict
from pathlib import Path

# Colonnes du journal csvlog de PostgreSQL 13 à 16 (les plus anciennes n'ont pas les 3 dernières).
COLUMNS = ('log_time', 'user_name', 'database_name', 'process_id', 'connection_from', 'session_id',
           'session_line_num', 'command_tag', 'session_start_time', 'virtual_transaction_id',
           'transaction_id', 'error_severity', 'sql_state_code', 'message', 'detail', 'hint',
           'internal_query', 'internal_query_pos', 'context', 'query', 'query_pos', 'location',
           'application_name', 'backend_type', 'leader_pid', 'query_id')
STATEMENT_PREFIXES = ('statement: ', 'execute ')
# DbHub wraps each read in a read-only transaction: shown only with --all.
TRANSACTION_CONTROL = ('BEGIN', 'COMMIT', 'ROLLBACK', 'START TRANSACTION', 'END')


def is_transaction_control(sql: str) -> bool:
    return sql.strip().rstrip(';').upper().startswith(TRANSACTION_CONTROL) and len(sql.split()) <= 3


def parse(text: str) -> list[dict]:
    rows = []
    for values in csv.reader(io.StringIO(text)):
        if values:
            rows.append(dict(zip(COLUMNS, values)))
    return rows


def classify(row: dict) -> tuple[str, str] | None:
    """('requête', sql) for a logged statement, ('erreur', message) for a failure, else None."""
    message = row.get('message', '')
    if row.get('error_severity') == 'LOG' and message.startswith(STATEMENT_PREFIXES):
        sql = message.split(': ', 1)[1] if ': ' in message else message
        return 'requête', sql.strip()
    if row.get('error_severity') in ('ERROR', 'FATAL') and row.get('user_name'):
        return 'erreur', '%s%s' % (message, (' | ' + row['query']) if row.get('query') else '')
    return None


def events(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        kind = classify(row)
        if not kind:
            continue
        params = row.get('detail', '')
        out.append({'time': row.get('log_time', ''), 'user': row.get('user_name', ''),
                    'database': row.get('database_name', ''), 'application': row.get('application_name', ''),
                    'session': row.get('session_id', ''), 'kind': kind[0], 'text': kind[1],
                    'parameters': params[len('parameters: '):] if params.startswith('parameters: ') else params})
    return out


def read_from_server() -> list[str]:
    import psycopg
    env = os.environ
    if not env.get('WAREHOUSE_POSTGRES_PASSWORD'):
        raise SystemExit('WAREHOUSE_POSTGRES_PASSWORD est requis (compte propriétaire), ou utiliser --file.')
    conn = psycopg.connect(host=env.get('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
                           port=int(env.get('WAREHOUSE_POSTGRES_PORT', '55432')),
                           dbname=env.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
                           user=env.get('WAREHOUSE_POSTGRES_USER', 'neolab'),
                           password=env['WAREHOUSE_POSTGRES_PASSWORD'])
    with conn:
        try:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM pg_ls_logdir() WHERE name LIKE '%.csv' ORDER BY name").fetchall()]
            directory = conn.execute("SELECT current_setting('log_directory')").fetchone()[0]
            return [conn.execute('SELECT pg_read_file(%s)', (directory.rstrip('/') + '/' + name,)).fetchone()[0]
                    for name in names]
        except psycopg.errors.InsufficientPrivilege:
            raise SystemExit('Lecture du journal refusée : il faut un superuser, ou les rôles pg_monitor et '
                             'pg_read_server_files. Sinon, copier les fichiers *.csv du journal et utiliser --file.')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--user', help='un compte précis')
    ap.add_argument('--since', help='date ou horodatage ISO (inclus), ex. 2026-10-01')
    ap.add_argument('--until', help='date ou horodatage ISO (exclu)')
    ap.add_argument('--errors', action='store_true', help='refus et échecs seulement')
    ap.add_argument('--all', action='store_true', help='inclure BEGIN/COMMIT ajoutés par DbHub')
    ap.add_argument('--summary', action='store_true', help='une ligne par compte')
    ap.add_argument('--limit', type=int, default=50, help='nombre de lignes affichées (défaut 50, 0 = toutes)')
    ap.add_argument('--full', action='store_true', help='ne pas tronquer le SQL')
    ap.add_argument('--csv', action='store_true', help='export CSV complet sur la sortie standard')
    ap.add_argument('--file', action='append', type=Path, help='fichier csvlog local (répétable) au lieu du serveur')
    args = ap.parse_args(argv)
    # The log writes '2026-10-31 15:47:52.545 UTC'; accept ISO input with a 'T' too.
    args.since = args.since.replace('T', ' ') if args.since else None
    args.until = args.until.replace('T', ' ') if args.until else None

    texts = [p.read_text(encoding='utf-8', errors='replace') for p in args.file] if args.file else read_from_server()
    found = events([row for text in texts for row in parse(text)])
    found = [e for e in found
             if (not args.user or e['user'] == args.user)
             and (not args.since or e['time'] >= args.since)
             and (not args.until or e['time'] < args.until)
             and (not args.errors or e['kind'] == 'erreur')
             and (args.all or e['kind'] == 'erreur' or not is_transaction_control(e['text']))]
    found.sort(key=lambda e: e['time'])

    if args.csv:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(found[0]) if found else
                                ['time', 'user', 'database', 'application', 'session', 'kind', 'text', 'parameters'])
        writer.writeheader()
        writer.writerows(found)
        return 0
    if not found:
        print('Aucune requête auditée pour ce filtre. (Comptes audités: voir docs/WAREHOUSE_AUDIT.md.)')
        return 0
    if args.summary:
        per_user: OrderedDict[str, dict] = OrderedDict()
        for e in found:
            s = per_user.setdefault(e['user'], {'requêtes': 0, 'erreurs': 0, 'sessions': set(), 'apps': set(),
                                                'première': e['time'], 'dernière': e['time']})
            s['requêtes' if e['kind'] == 'requête' else 'erreurs'] += 1
            s['sessions'].add(e['session'])
            s['apps'].add(e['application'] or '?')
            s['dernière'] = e['time']
        print('%-20s %8s %7s %8s  %-23s %-23s %s' % ('compte', 'requêtes', 'erreurs', 'sessions', 'première',
                                                    'dernière', 'outils'))
        for user, s in per_user.items():
            print('%-20s %8d %7d %8d  %-23s %-23s %s' % (user, s['requêtes'], s['erreurs'], len(s['sessions']),
                                                        s['première'][:23], s['dernière'][:23],
                                                        ', '.join(sorted(s['apps']))))
        return 0
    shown = found[-args.limit:] if args.limit else found
    for e in shown:
        text = ' '.join(e['text'].split())
        if not args.full and len(text) > 160:
            text = text[:157] + '...'
        params = (' [%s]' % e['parameters']) if e['parameters'] else ''
        flag = 'ERREUR ' if e['kind'] == 'erreur' else ''
        print('%s  %-16s %-24s %s%s%s' % (e['time'][:19], e['user'], (e['application'] or '?')[:24], flag,
                                         text, params))
    if args.limit and len(found) > args.limit:
        print('… %d ligne(s) plus anciennes non affichées (--limit 0 pour tout voir).' % (len(found) - args.limit))
    return 0


if __name__ == '__main__':
    sys.exit(main())
