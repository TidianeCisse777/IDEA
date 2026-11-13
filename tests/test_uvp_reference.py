"""Position retenue des profils UVP, copie EcoTaxa de référence, tables dérivées tenues à jour (13 novembre 2026).

Constaté sur la base : positions source fausses (profils 2021 de…, copie EcoTaxa 149 de GreenEdge 2016), alors que
la CTD citée dans EcoTaxa est à la bonne heure; abondance UVP et comptes par taxon périmés pour 17498 et 18084.
Contrôles statiques (sans base); le comportement a été vérifié sur une base jetable (ROADMAP, 13 novembre 2026).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / 'sql'
sys.path.insert(0, str(ROOT / 'scripts'))


def text(name: str) -> str:
    return (SQL / name).read_text(encoding='utf-8')


def reference_block(sql: str) -> str:
    """The shared DDL: profile columns and the reference copy view, whitespace-normalised."""
    start = sql.index('ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_latitude')
    end = sql.index('e.project_id;', start) + len('e.project_id;')
    return ' '.join(sql[start:end].split())


class SharedDefinitions(unittest.TestCase):
    def test_ecopart_replay_and_deployment_share_the_reference_ddl(self):
        # populate_ecopart.py replays the EcoPart migration: it must create the same columns and view.
        self.assertEqual(reference_block(text('warehouse_ecopart_migration.sql')),
                         reference_block(text('warehouse_uvp_reference_migration.sql')))

    def test_reference_copy_is_the_closest_to_the_profile_then_the_smallest_project(self):
        block = reference_block(text('warehouse_uvp_reference_migration.sql'))
        self.assertIn('SELECT DISTINCT ON (l.uvp_profile_id) l.uvp_profile_id, e.id AS ecotaxa_sample_id, e.project_id', block)
        self.assertRegex(block, r'ORDER BY l\.uvp_profile_id, round\(.*\)::numeric, 1\) NULLS LAST, e\.project_id;$')
        self.assertIn('least(1, sqrt(', block)       # asin() never gets a value above 1 from rounding

    def test_no_view_keeps_the_old_smallest_project_rule(self):
        for path in SQL.glob('*.sql'):
            self.assertNotIn('e2.project_id < ', path.read_text(encoding='utf-8'), path.name)


class CitedCtdPosition(unittest.TestCase):
    SQL = text('warehouse_uvp_reference_migration.sql')

    def test_source_values_are_kept_before_any_change(self):
        body = self.SQL.split('CREATE OR REPLACE FUNCTION warehouse.apply_uvp_cited_ctd_positions()')[1]
        backup = body.index('SET source_latitude = latitude')
        self.assertLess(backup, body.index("position_source = 'ctd_cite'"))
        self.assertIn('WHERE position_source IS NULL', body)

    def test_only_the_cited_ctd_moves_a_profile_and_its_loss_restores_the_source(self):
        body = self.SQL.split('CREATE OR REPLACE FUNCTION warehouse.apply_uvp_cited_ctd_positions()')[1]
        self.assertEqual(body.count("u.link_method = 'filename_transitive'"), 2)
        self.assertIn('SET latitude = p.source_latitude', body)
        self.assertIn('marine_zone_key = c.marine_zone_key', body)

    def test_applied_after_the_links_and_after_new_ctd_zones(self):
        links = text('warehouse_uvp_ctd_links.sql')
        # positions first (they back up the source values), then the distances that read them
        self.assertLess(links.index('SELECT warehouse.apply_uvp_cited_ctd_positions();'),
                        links.index('SET distance_km = x.distance_km'))
        prox = (ROOT / 'scripts' / 'populate_ctd_proximity.py').read_text(encoding='utf-8')
        self.assertLess(prox.index("assign(table='ctd_profile')"), prox.index('apply_uvp_cited_ctd_positions()'))

    def test_views_take_the_profile_zone_once_the_position_comes_from_the_ctd(self):
        for name in ('warehouse_ecopart_migration.sql', 'warehouse_ecotaxa_object_size_migration.sql',
                     'warehouse_ecotaxa_project_title_migration.sql'):
            self.assertIn("CASE WHEN u.position_source = 'ctd_cite' THEN u.marine_zone_key", text(name), name)


class DerivedTablesStayFresh(unittest.TestCase):
    SQL = text('warehouse_derived_refresh.sql')

    def test_counts_then_abundance_are_refreshed_at_every_deployment(self):
        tail = self.SQL[self.SQL.rindex('$$;'):]
        self.assertLess(tail.index('refresh_ecotaxa_sample_taxon(true)'), tail.index('refresh_uvp_taxon_abundance()'))

    def test_abundance_is_recomputed_only_when_its_source_changed(self):
        self.assertIn("signature IS NOT DISTINCT FROM", self.SQL)
        self.assertIn('RETURN -1;', self.SQL)
        for source in ('warehouse.ecotaxa_sample_taxon', 'warehouse.uvp_object_bin', 'warehouse.uvp_bin'):
            self.assertIn(source, self.SQL.split('uvp_abundance_signature()')[1].split('$$;')[0], source)

    def test_one_definition_of_the_abundance(self):
        loader = (ROOT / 'scripts' / 'populate_ecopart.py').read_text(encoding='utf-8')
        self.assertNotIn('INSERT INTO warehouse.uvp_taxon_abundance', loader)
        self.assertIn('warehouse.insert_uvp_taxon_abundance(%s)', loader)
        self.assertIn("'validated_only', o.annotation_status = 'validated'", self.SQL)

    def test_state_table_is_a_declared_catalog(self):
        audit = text('warehouse_access_control.sql').split('CREATE OR REPLACE VIEW catalogue.access_audit')[1]
        self.assertIn("'derived_refresh'", audit.split('UNION ALL')[0])

    def test_status_reports_freshness(self):
        status = (ROOT / 'docker' / 'allinone' / 'neolab-status').read_text(encoding='utf-8')
        self.assertIn('warehouse.uvp_abundance_is_fresh()', status)


class DeploymentOrder(unittest.TestCase):
    def test_order_in_deploy_and_compose(self):
        import deploy_warehouse_postgres as deploy
        files = list(deploy.ALWAYS_FILES)
        reference = files.index('warehouse_uvp_reference_migration.sql')
        for later in ('warehouse_uvp_particle_sizes_view.sql', 'warehouse_ecotaxa_object_size_migration.sql',
                      'warehouse_ecotaxa_project_title_migration.sql', 'warehouse_uvp_abundance_zone_migration.sql',
                      'warehouse_uvp_ctd_links.sql'):
            self.assertLess(reference, files.index(later), later)
        refresh = files.index('warehouse_derived_refresh.sql')
        self.assertGreater(refresh, files.index('warehouse_ecotaxa_taxa_migration.sql'))
        self.assertEqual(files[-1], 'warehouse_filet_uvp_compare.sql')
        compose = (ROOT / 'docker-compose.warehouse.yml').read_text(encoding='utf-8')
        order = re.findall(r'/docker-entrypoint-initdb\.d/(\d+_[\w.]+)', compose)
        self.assertLess(order.index('005_warehouse_ctd_zone.sql'), order.index('006_5_warehouse_uvp_reference.sql'))
        self.assertLess(order.index('006_5_warehouse_uvp_reference.sql'), order.index('007_warehouse_ecotaxa_sizes.sql'))
        self.assertIn('022_0_warehouse_derived_refresh.sql', order)


class ContextSheets(unittest.TestCase):
    def test_new_columns_are_documented(self):
        import warehouse_context as context
        for column in ('position_source', 'source_latitude', 'source_longitude'):
            self.assertTrue(context.column_description('uvp_samples', column))
        self.assertIn('CTD', context.column_description('uvp_samples', 'latitude'))
        self.assertIn('uvp_canonical_sample', context.VIEWS['uvp_objects']['caveats'])


if __name__ == '__main__':
    unittest.main()


class AuditFollowUps(unittest.TestCase):
    """Points 4 to 9 of the audit of 13 November 2026."""

    def test_particles_below_detection_are_unknown_not_zero(self):
        view = text('warehouse_uvp_particle_sizes_view.sql')
        self.assertIn('CASE WHEN p.size_max_um <= u.particle_min_detected_um THEN NULL ELSE p.supplied_concentration END', view)
        self.assertIn('AS below_detection', view)
        self.assertIn('p.supplied_concentration AS supplied_concentration_source', view)
        self.assertIn('round(p.size_max_um::numeric, 3)::double precision AS size_max_um', view)
        refresh = text('warehouse_derived_refresh.sql')
        self.assertIn('min(p.size_min_um) FILTER (WHERE p.supplied_concentration > 0)', refresh)

    def test_particle_sheet_uses_the_only_loaded_value(self):
        import warehouse_context as context
        sheet = context.VIEWS['uvp_particle_sizes']
        self.assertIn('supplied_concentration', sheet['example'])
        self.assertNotIn('particle_count', sheet['example'])

    def test_filename_links_show_their_distance_and_gap(self):
        links = text('warehouse_uvp_ctd_links.sql')
        tail = links[links.index('SELECT warehouse.apply_uvp_cited_ctd_positions();'):]
        self.assertIn('SET distance_km = x.distance_km, time_gap_hours = x.time_gap_hours', tail)
        self.assertIn("WHERE u.link_method = 'filename_transitive'", tail)
        self.assertIn('coalesce(p.source_latitude, e.lat_avg)', tail)

    def test_ctd_targets_never_average_copies_nor_versions(self):
        prox = (ROOT / 'scripts' / 'populate_ctd_proximity.py').read_text(encoding='utf-8')
        targets = prox.split('def targets(conn)')[1].split('def match(')[0]
        self.assertNotIn('avg(e.lat_avg)', targets)
        self.assertIn('warehouse.uvp_canonical_sample k', targets)
        self.assertIn('GROUP BY s.dataset_version_id, s.deployment_id', targets)
        self.assertIn("WHERE s.dataset_version_id || '|' || s.deployment_id = %s", prox)

    def test_sheets_warn_about_gaps_and_particular_profiles(self):
        import warehouse_context as context
        for name in ('ecopart_bins', 'uvp_taxon_abundance', 'uvp_objects'):
            self.assertIn('TRANCHES MANQUANTES', context.VIEWS[name]['caveats'], name)
        for name in ('uvp_samples', 'ecopart_bins', 'uvp_taxon_abundance'):
            self.assertIn('de320_004_lighttest', context.VIEWS[name]['caveats'], name)
        for column in ('below_detection', 'supplied_concentration_source'):
            self.assertTrue(context.column_description('uvp_particle_sizes', column))
