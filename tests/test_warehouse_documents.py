"""Documents écrits consultables par les agents : découpage, migration, outils MCP."""

import json
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import add_warehouse_document as docs  # noqa: E402


class SectionTests(unittest.TestCase):
    def test_markdown_headings_make_sections_in_order(self):
        text = '# Protocole\nIntro.\n\n## Volume filtré\nDébitmètre.\n```\n# pas un titre\n```\n### Maille\n200 µm.'
        parts = docs.sections(text, markdown=True)
        self.assertEqual([h for h, _ in parts], ['Protocole', 'Volume filtré', 'Maille'])
        self.assertIn('# pas un titre', parts[1][1])

    def test_long_section_is_split_at_paragraphs(self):
        body = '\n\n'.join('p%d ' % i + 'x' * 900 for i in range(8))
        parts = docs.sections('## Long\n' + body, markdown=True)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[0][0], 'Long')
        self.assertEqual(parts[1][0], 'Long (suite)')
        self.assertTrue(all(len(b) <= docs.MAX_SECTION for _, b in parts))
        self.assertEqual(''.join(b for _, b in parts).count('p7 '), 1)

    def test_text_without_headings_keeps_all_text(self):
        parts = docs.sections('Premier paragraphe.\n\nSecond.', markdown=False)
        self.assertEqual(parts, [(None, 'Premier paragraphe.\n\nSecond.')])

    def test_windows_1252_text_is_read(self):
        path = Path(self.id().replace('.', '_') + '.txt')
        tmp = ROOT / 'data' / path.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes('Copépodes à 200 µm'.encode('cp1252'))
        try:
            self.assertEqual(docs.read_text(tmp), 'Copépodes à 200 µm')
        finally:
            tmp.unlink()


class ContractTests(unittest.TestCase):
    def test_manifest_points_to_repository_files(self):
        manifest = json.loads(docs.MANIFEST.read_text(encoding='utf-8'))
        for entry in manifest['documents']:
            self.assertTrue((ROOT / entry['path']).is_file(), entry['path'])
            self.assertIn(entry['kind'], docs.KINDS)

    def test_migration_has_row_security_and_runs_after_access_control(self):
        sql = (ROOT / 'docs' / 'warehouse_documents_migration.sql').read_text(encoding='utf-8')
        for table in ('document', 'document_section'):
            self.assertIn(f'ALTER TABLE warehouse.{table} FORCE ROW LEVEL SECURITY', sql)
        import deploy_warehouse_postgres as deploy
        files = list(deploy.ALWAYS_FILES)
        self.assertGreater(files.index('warehouse_documents_migration.sql'), files.index('warehouse_access_control.sql'))

    def test_both_dbhub_configs_offer_search_and_read(self):
        for name in ('warehouse.toml', 'warehouse.connect.toml'):
            tools = {t['name']: t for t in tomllib.loads((ROOT / 'dbhub' / name).read_text(encoding='utf-8'))['tools']}
            self.assertIn('catalogue.search_documents($1', tools['search_documents']['statement'])
            self.assertIn('catalogue.read_document($1', tools['read_document']['statement'])


if __name__ == '__main__':
    unittest.main()
