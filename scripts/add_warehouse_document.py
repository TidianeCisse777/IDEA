#!/usr/bin/env python3
"""Charger des documents écrits dans le warehouse, consultables par les agents (search_documents,
read_document) : protocoles, notes de méthode, rapports, publications.

    python scripts/add_warehouse_document.py add protocole.md --key filet-protocole --title "Protocole FILET" \\
        --kind protocole [--author …] [--date 2024-07-01] [--url …] [--dataset-key filet] [--summary …]
    python scripts/add_warehouse_document.py sync          # documents du dépôt (docs/warehouse_documents.json)
    python scripts/add_warehouse_document.py list
    python scripts/add_warehouse_document.py remove filet-protocole

Formats : .md (sections aux titres #, ##, ###), .txt (paragraphes), .pdf (texte extrait par pdftotext,
s'il est installé). Le texte est conservé tel quel et découpé en sections d'au plus ~3 000 caractères;
recharger la même clé remplace le document (rien ne change si le fichier et ses métadonnées sont identiques).
Connexion : variables WAREHOUSE_POSTGRES_* du déploiement (compte propriétaire).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs' / 'warehouse_documents.json'
KINDS = ('protocole', 'méthode', 'note', 'rapport', 'publication', 'autre')
MAX_SECTION = 3000
HEADING = re.compile(r'^(#{1,3})\s+(.+?)\s*#*\s*$')


def read_text(path: Path) -> str:
    """Text of a .md, .txt or .pdf file; UTF-8, else Windows-1252 (exports from Excel or Word)."""
    if path.suffix.lower() == '.pdf':
        if not shutil.which('pdftotext'):
            raise SystemExit(f'{path.name} : pdftotext (poppler-utils) manque; convertir le PDF en .txt ou .md.')
        result = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True)
        if result.returncode:
            raise SystemExit(f'{path.name} : extraction du texte impossible.')
        raw = result.stdout
    elif path.suffix.lower() in ('.md', '.txt', '.markdown'):
        raw = path.read_bytes()
    else:
        raise SystemExit(f'{path.name} : format non pris en charge (.md, .txt, .pdf).')
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(encoding).replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            continue
    raise SystemExit(f'{path.name} : encodage illisible.')


def _chunks(body: str) -> list[str]:
    """Split a long body at paragraph boundaries; a single paragraph longer than the limit stays whole."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    chunks, current = [], ''
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > MAX_SECTION:
            chunks.append(current)
            current = paragraph
        else:
            current = f'{current}\n\n{paragraph}' if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def sections(text: str, markdown: bool) -> list[tuple[str | None, str]]:
    """(heading, body) in document order. Markdown: one section per #, ## or ### heading (headings inside
    code blocks ignored); a long section continues as « heading (suite) »."""
    parts: list[tuple[str | None, list[str]]] = [(None, [])]
    fenced = False
    for line in text.split('\n'):
        if line.lstrip().startswith('```'):
            fenced = not fenced
        match = HEADING.match(line) if markdown and not fenced else None
        if match:
            parts.append((match.group(2).strip(), []))
        else:
            parts[-1][1].append(line)
    result = []
    for heading, lines in parts:
        for index, chunk in enumerate(_chunks('\n'.join(lines))):
            result.append((heading if index == 0 or heading is None else f'{heading} (suite)', chunk))
        if heading and not any(line.strip() for line in lines):
            result.append((heading, heading))  # heading alone: kept so the outline stays complete
    return result


def connect():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import psycopg
    from publish_warehouse_context import connect as context_connect
    return context_connect(psycopg)


def load(conn, path: Path, key: str, title: str, kind: str, *, language='fr', author=None, document_date=None,
         url=None, dataset_key=None, summary=None) -> str:
    """Insert or replace one document; returns what was done."""
    if kind not in KINDS:
        raise SystemExit(f'type {kind!r} inconnu : {", ".join(KINDS)}')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', key):
        raise SystemExit(f'clé {key!r} : minuscules, chiffres, - et _ seulement (ex. filet-protocole-2024).')
    if document_date:
        date.fromisoformat(document_date)
    raw = path.read_bytes()
    text = read_text(path)
    parts = sections(text, markdown=path.suffix.lower() in ('.md', '.markdown'))
    if not parts:
        raise SystemExit(f'{path.name} : aucun texte.')
    digest = hashlib.sha256(raw).hexdigest()
    with conn.transaction():
        # The dataset may be loaded after the document: the version link is part of what must match.
        version = None
        if dataset_key:
            version = conn.execute('SELECT max(id) FROM warehouse.dataset_version WHERE dataset_key = %s',
                                   (dataset_key,)).fetchone()[0]
        meta = (title, kind, language, author, document_date, url, path.name, dataset_key, version, summary, digest)
        row = conn.execute('SELECT id, title, kind, language, author, document_date::text, url, source_name, '
                           'dataset_key, dataset_version_id, summary, sha256 FROM warehouse.document WHERE doc_key = %s',
                           (key,)).fetchone()
        if row and tuple(row[1:]) == meta:
            return f'{key} : inchangé'
        if row:
            conn.execute('DELETE FROM warehouse.document WHERE id = %s', (row[0],))
        document_id = conn.execute(
            'INSERT INTO warehouse.document (doc_key, title, kind, language, author, document_date, url, source_name, '
            'dataset_key, dataset_version_id, summary, sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (key, title, kind, language, author, document_date, url, path.name, dataset_key, version, summary,
             digest)).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO warehouse.document_section (document_id, ordinal, heading, body) '
                            'VALUES (%s,%s,%s,%s)',
                            [(document_id, n, heading, body) for n, (heading, body) in enumerate(parts, 1)])
    return f'{key} : {"remplacé" if row else "ajouté"} ({len(parts)} sections)'


def sync(conn, manifest: Path = MANIFEST) -> list[str]:
    """Load every document listed in the repository manifest (paths relative to the repository)."""
    entries = json.loads(manifest.read_text(encoding='utf-8'))['documents']
    done = []
    for entry in entries:
        entry = dict(entry)
        path = ROOT / entry.pop('path')
        key, title, kind = entry.pop('key'), entry.pop('title'), entry.pop('kind')
        entry['document_date'] = entry.pop('date', None)
        done.append(load(conn, path, key, title, kind, **entry))
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('add', help='charger ou remplacer un document')
    p.add_argument('path', type=Path)
    p.add_argument('--key', required=True)
    p.add_argument('--title', required=True)
    p.add_argument('--kind', required=True, choices=KINDS)
    p.add_argument('--language', default='fr')
    p.add_argument('--author')
    p.add_argument('--date', help='AAAA-MM-JJ')
    p.add_argument('--url')
    p.add_argument('--dataset-key', help='jeu de données concerné (ex. filet) : visible seulement avec lui')
    p.add_argument('--summary')
    sub.add_parser('sync', help='charger les documents du dépôt (docs/warehouse_documents.json)')
    sub.add_parser('list', help='lister les documents chargés')
    p = sub.add_parser('remove', help='retirer un document')
    p.add_argument('key')
    args = parser.parse_args(argv)
    with connect() as conn:
        if args.command == 'add':
            print(load(conn, args.path, args.key, args.title, args.kind, language=args.language, author=args.author,
                       document_date=args.date, url=args.url, dataset_key=args.dataset_key, summary=args.summary))
        elif args.command == 'sync':
            print('\n'.join(sync(conn)))
        elif args.command == 'list':
            for row in conn.execute('SELECT doc_key, kind, title, (SELECT count(*) FROM warehouse.document_section s '
                                    'WHERE s.document_id = d.id) FROM warehouse.document d ORDER BY doc_key'):
                print('%s  [%s]  %s  (%s sections)' % row)
        else:
            with conn.transaction():
                gone = conn.execute('DELETE FROM warehouse.document WHERE doc_key = %s', (args.key,)).rowcount
            print(f'{args.key} : {"retiré" if gone else "absent"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
