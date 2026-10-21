"""Contrat de distance : même seuil sur les trois surfaces de comparaison."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SpatialComparisonTests(unittest.TestCase):
    def test_all_endpoints_accept_a_nonnegative_optional_distance(self):
        tree = ast.parse((ROOT / 'warehouse_navigator/app.py').read_text(encoding='utf-8'))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ('coverage', 'map_points', 'filet_uvp'):
            self.assertIn('max_distance_km', [arg.arg for arg in functions[name].args.args])
        source = ast.unparse(tree)
        self.assertIn('ST_Distance', source)
        self.assertIn('geography', source)
        self.assertIn('distance_km', source)

    def test_ui_sends_same_threshold_to_map_metrics_and_pairs(self):
        source = (ROOT / 'warehouse_navigator/static/index.html').read_text(encoding='utf-8')
        self.assertIn('id="distanceKm"', source)
        self.assertIn("params.set('max_distance_km'", source)
        self.assertIn("pairParams.set('max_distance_km'", source)
        self.assertIn('x.distance_km', source)


if __name__ == '__main__':
    unittest.main()
