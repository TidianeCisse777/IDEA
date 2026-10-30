"""Contexte métier transmis au client MCP, indépendamment de l'historique chat."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from warehouse_context import VIEWS, GRAPHICS, column_description


class WarehouseContextTests(unittest.TestCase):
    def test_every_scientific_view_has_a_grain_and_caveat(self):
        self.assertEqual(len(VIEWS), 17)
        for name, item in VIEWS.items():
            for key in ('purpose', 'grain', 'joins', 'caveats', 'example'):
                self.assertTrue(item[key], (name, key))

    def test_zero_denominators_taxonomy_and_fanout_are_explicit(self):
        self.assertIn('SUM', VIEWS['uvp_taxon_abundance']['caveats'])
        self.assertIn('annotation_policy', VIEWS['uvp_taxon_abundance']['caveats'])
        self.assertIn('versions', VIEWS['filet_uvp_abundance']['caveats'])
        self.assertIn('multipl', VIEWS['uvp_objects']['caveats'])

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


if __name__ == '__main__':
    unittest.main()
