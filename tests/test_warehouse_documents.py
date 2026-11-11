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
        sql = (ROOT / 'sql' / 'warehouse_documents_migration.sql').read_text(encoding='utf-8')
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


class FiletUvpCompareTests(unittest.TestCase):
    SQL = (ROOT / 'sql' / 'warehouse_filet_uvp_compare.sql').read_text(encoding='utf-8')

    def test_aggregate_stage_with_its_parts_is_refused(self):
        self.assertIn("'COPEPODID' = ANY(p_filet_stages) AND p_filet_stages && copepodid", self.SQL)
        self.assertIn("'ALL_STAGES' = ANY(p_filet_stages) AND cardinality(p_filet_stages) > 1", self.SQL)

    def test_uvp_volume_counts_every_bin_of_the_layer(self):
        # Volume from the bins (empty ones included), not from the objects found.
        self.assertIn('FROM explore.uvp_particle_sizes', self.SQL)
        self.assertIn('b.depth_min_m >= l.dmin AND b.depth_max_m <= l.dmax', self.SQL)

    def test_deployed_after_the_views_it_reads(self):
        import deploy_warehouse_postgres as deploy
        self.assertEqual(deploy.ALWAYS_FILES[-1], 'warehouse_filet_uvp_compare.sql')

    def test_missing_size_is_unknown_not_zero(self):
        # Amundsen 2023 gives no ESD: the size filter must not turn those objects into « 0 too small ».
        for name in ('warehouse_ecotaxa_object_size_migration.sql', 'warehouse_explore_catalog_migration.sql'):
            self.assertIn('coalesce(o.esd_px, 2 * sqrt(o.area_px / pi()))',
                          (ROOT / 'sql' / name).read_text(encoding='utf-8'), name)
        self.assertIn('uvp_n_objects_no_size', self.SQL)
        self.assertIn('CASE WHEN coalesce(o.no_size, 0) = 0 THEN', self.SQL)

    def test_station_filter_and_single_signatures(self):
        self.assertIn('p_filet_stations text[] DEFAULT NULL', self.SQL)
        self.assertIn('DROP FUNCTION IF EXISTS explore.filet_uvp_pairs(double precision, double precision, boolean, boolean);', self.SQL)


class UvpCtdLinkTests(unittest.TestCase):
    SQL = (ROOT / 'sql' / 'warehouse_uvp_ctd_links.sql').read_text(encoding='utf-8')

    def test_links_follow_only_accepted_ecotaxa_ctd_links(self):
        # explore.uvp_ctd was empty: CTD loaded after EcoPart; the links are now rebuilt at every deploy.
        self.assertIn("c.match_status = 'accepted'", self.SQL)
        self.assertIn('ON CONFLICT DO NOTHING', self.SQL)
        self.assertNotIn('distance', self.SQL.lower().split('aucun lien par proximité')[0][-50:])
        import deploy_warehouse_postgres as deploy
        self.assertIn('warehouse_uvp_ctd_links.sql', deploy.ALWAYS_FILES)


class DataQaTests(unittest.TestCase):
    """Traps found by the data QA of 11 November 2026."""

    def test_comparison_counts_one_ecotaxa_copy_per_uvp_profile(self):
        # 199 GreenEdge 2016 profiles are linked to two identical EcoTaxa copies: UVP abundance was doubled.
        sql = (ROOT / 'sql' / 'warehouse_filet_uvp_compare.sql').read_text(encoding='utf-8')
        self.assertIn('min(u.ecotaxa_project_id) AS project_id', sql)
        self.assertIn('src.project_id = z.project_id', sql)
        self.assertIn('uvp_ecotaxa_project_id integer', sql)

    def test_uvp_sheets_warn_about_copies_and_object_sizes_expose_the_project(self):
        import warehouse_context as context
        for name in ('uvp_objects', 'uvp_object_sizes', 'uvp_taxon_abundance', 'uvp_samples'):
            self.assertIn('COPIES ECOTAXA', context.VIEWS[name]['caveats'], name)
        view = (ROOT / 'sql' / 'warehouse_ecotaxa_object_size_migration.sql').read_text(encoding='utf-8')
        self.assertIn('e.project_id AS ecotaxa_project_id', view)

    def test_empty_views_and_source_anomalies_are_stated(self):
        import warehouse_context as context
        publish = (ROOT / 'scripts' / 'publish_warehouse_context.py').read_text(encoding='utf-8')
        self.assertIn('VUE VIDE dans ce déploiement', publish)
        for name in ('taxon_mapping', 'filet_uvp_abundance', 'filet_ctd'):
            self.assertRegex(context.VIEWS[name]['caveats'], r'(?i)vide|aucun lien', name)
        self.assertIn('22497', context.VIEWS['filet_data']['caveats'])

    def test_uvp_views_keep_one_ecotaxa_copy_per_profile(self):
        # The copies are filtered in the views themselves: an agent cannot count GreenEdge 2016 twice.
        docs_dir = ROOT / 'sql'
        for name in ('warehouse_ecotaxa_object_size_migration.sql', 'warehouse_ecotaxa_project_title_migration.sql',
                     'warehouse_uvp_abundance_zone_migration.sql', 'warehouse_ecopart_migration.sql'):
            self.assertIn('e2.project_id <', (docs_dir / name).read_text(encoding='utf-8'), name)

        def definition(name, view):
            text = (docs_dir / name).read_text(encoding='utf-8')
            start = text.index('CREATE OR REPLACE VIEW explore.%s AS' % view)
            return text[start:text.index(';', start)]
        self.assertEqual(definition('warehouse_ecotaxa_object_size_migration.sql', 'uvp_objects'),
                         definition('warehouse_ecopart_migration.sql', 'uvp_objects'))
