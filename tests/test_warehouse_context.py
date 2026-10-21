"""Contexte métier transmis au client MCP, indépendamment de l'historique chat."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from warehouse_context import VIEWS, column_description


class WarehouseContextTests(unittest.TestCase):
    def test_every_scientific_view_has_a_grain_and_caveat(self):
        self.assertEqual(len(VIEWS), 16)
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


if __name__ == '__main__':
    unittest.main()
