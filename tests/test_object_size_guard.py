"""Une aire source négative (projet LOKI 11469 : 292 objets) donne une taille inconnue, jamais une erreur SQL."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NegativeArea(unittest.TestCase):
    def test_every_esd_from_area_is_guarded(self):
        for name in ('warehouse_ecotaxa_object_size_migration.sql', 'warehouse_explore_catalog_migration.sql'):
            text = (ROOT / 'sql' / name).read_text(encoding='utf-8')
            uses = re.findall(r'[^\n]*sqrt\(o\.area_px[^\n]*', text)
            self.assertTrue(uses, name)
            for line in uses:
                self.assertIn('CASE WHEN o.area_px >= 0 THEN', line, name)


if __name__ == '__main__':
    unittest.main()
