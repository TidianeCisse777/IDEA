"""Contexte métier transmis au client MCP, indépendamment de l'historique chat."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from warehouse_context import VIEWS, GRAPHICS, column_description


class WarehouseContextTests(unittest.TestCase):
    def test_every_scientific_view_has_a_grain_and_caveat(self):
        self.assertEqual(len(VIEWS), 29)
        for name, item in VIEWS.items():
            for key in ('purpose', 'grain', 'joins', 'caveats', 'example'):
                self.assertTrue(item[key], (name, key))

    def test_zero_denominators_taxonomy_and_fanout_are_explicit(self):
        self.assertIn('SUM', VIEWS['uvp_taxon_abundance']['caveats'])
        self.assertIn('annotation_policy', VIEWS['uvp_taxon_abundance']['caveats'])
        self.assertIn('versions', VIEWS['filet_uvp_abundance']['caveats'])
        self.assertIn('multipl', VIEWS['uvp_objects']['caveats'])

    def test_taxa_are_found_in_the_small_view_and_groups_by_lineage(self):
        # 7 novembre 2026: taxon searches over ecotaxa_objects took 31.8 s (limit 30 s), and
        # "copepods" were listed from memory; a stage category (female+lateral<Metridia longa) is
        # type M like a fragment, so taxon_type must not be used to drop fragments.
        self.assertIn('ecotaxa_sample_taxa', VIEWS['ecotaxa_objects']['caveats'])
        caveats = VIEWS['ecotaxa_sample_taxa']['caveats']
        for text in ("'Copepoda' = ANY(taxon_lineage)", 'de mémoire', 'part<', 'like<', 'ne veut pas dire fragment'):
            self.assertIn(text, caveats)
        self.assertIn('ne veut pas dire fragment', column_description('ecotaxa_taxa', 'taxon_type'))
        self.assertIn('ce sample', column_description('ecotaxa_sample_taxa', 'n_validated'))
        self.assertIn('projet', column_description('ecotaxa_projects', 'n_validated'))

    def test_taxon_identifiers_depend_on_source(self):
        self.assertNotEqual(column_description('filet_data', 'taxon_id'),
                            column_description('uvp_objects', 'taxon_id'))
        self.assertIn('officiel', column_description('uvp_taxon_abundance', 'taxon_key'))

    def test_unknown_units_are_not_invented(self):
        self.assertIn('confirmer', column_description('filet_samples', 'net_mesh_size'))
        self.assertIn('litres', column_description('ecopart_bins', 'sampled_volume_l'))

    def test_graphics_require_real_complete_results_and_reproducible_outputs(self):
        text = ' '.join(GRAPHICS.values())
        for requirement in ('Matplotlib', 'pandas', 'Plotly', '1 000', 'tronqu',
                            'PNG', 'SVG', 'CSV', 'SQL', 'vide', 'NULL'):
            self.assertIn(requirement, text)

    def test_graphics_guard_against_defects_seen_in_real_agent_runs(self):
        # 3 novembre 2026: a figure saved under a mistyped absolute path, a final render
        # never re-read, an abundance figure built on predicted objects only.
        text = ' '.join(GRAPHICS.values())
        for requirement in ('chemins relatifs', 'vérifier qu’ils existent', 'APRÈS la dernière modification',
                            'validated_only', 'all_loaded_objects'):
            self.assertIn(requirement, text)

    def test_graphics_express_confidence_without_inventing_scientific_validation(self):
        text = ' '.join(GRAPHICS.values())
        for requirement in ('confirmed', 'exploratory', 'uncertain', 'Exploratoire',
                            'validation', 'profondeur', 'unités'):
            self.assertIn(requirement, text)

    def test_maps_keep_coordinate_order_projection_and_network_limits_explicit(self):
        text = ' '.join(GRAPHICS.values())
        for requirement in ('Cartopy', 'Folium', 'PlateCarree', '[latitude, longitude]',
                            '[longitude, latitude]', 'WGS84', 'HTML', 'tuiles'):
            self.assertIn(requirement, text)

    def test_oceanographic_libraries_do_not_authorize_implicit_physical_conversions(self):
        text = ' '.join(GRAPHICS.values())
        for requirement in ('oceans', 'gsw', 'TEOS-10', 'cmocean', 'xarray',
                            'salinité pratique/absolue', 'pression et profondeur', 'hypothèses'):
            self.assertIn(requirement, text)


class OverviewTransparencyTests(unittest.TestCase):
    def test_agents_show_the_queries_and_results_behind_their_numbers(self):
        from publish_warehouse_context import OVERVIEW
        for requirement in ('Requêtes exécutées', 'texte exact', 'nombre de lignes renvoyées',
                            'réellement exécutées', 'sans les reformuler'):
            self.assertIn(requirement, OVERVIEW)


class CopepodStageReferenceTests(unittest.TestCase):
    """The stage reference must say exactly what the schema and the FILET loader already do."""

    def setUp(self):
        import ast
        import re
        root = Path(__file__).resolve().parents[1]
        sql = (root / 'docs/warehouse_copepod_stage_migration.sql').read_text(encoding='utf-8')
        values = sql.split('VALUES', 1)[1].split('ON CONFLICT', 1)[0]
        values = re.sub(r'\bNULL\b', 'None', re.sub(r'\btrue\b', 'True', re.sub(r'\bfalse\b', 'False', values)))
        # (code, label, phase, order, sex, is_aggregate, aggregate_of, has_biomass, status, note)
        self.rows = {row[0]: row for row in ast.literal_eval('[' + values + ']')}
        schema = (root / 'docs/warehouse_schema_proposal.sql').read_text(encoding='utf-8')
        check = re.search(r"stage text NOT NULL CHECK \(stage IN \((.*?)\)\)", schema, re.S).group(1)
        generated = re.search(r"is_aggregate boolean GENERATED ALWAYS AS\s*\(stage IN \((.*?)\)\)", schema, re.S).group(1)
        self.schema_stages = set(re.findall(r"'([A-Z0-9_]+)'", check))
        self.schema_aggregates = set(re.findall(r"'([A-Z0-9_]+)'", generated))
        sys.path.insert(0, str(root / 'scripts'))
        import populate_filet
        self.loader = populate_filet

    def test_codes_match_the_schema_and_the_loader(self):
        self.assertEqual(set(self.rows), self.schema_stages)
        self.assertEqual(set(self.rows), set(self.loader.STAGES))

    def test_aggregates_and_biomass_match_what_is_established(self):
        aggregates = {code for code, row in self.rows.items() if row[5]}
        self.assertEqual(aggregates, self.schema_aggregates)
        with_biomass = {code for code, row in self.rows.items() if row[7]}
        self.assertEqual(with_biomass, set(self.loader.STAGES_WITH_BIOMASS))

    def test_nothing_unconfirmed_is_presented_as_validated(self):
        self.assertTrue(all(row[8] in ('convention usuelle, à confirmer', 'à confirmer') for row in self.rows.values()))
        for code in ('COP_NS', 'NAUP_NS', 'COPEPODID', 'NAUPLIUS', 'ALL_STAGES'):
            self.assertEqual(self.rows[code][8], 'à confirmer', code)


if __name__ == '__main__':
    unittest.main()
