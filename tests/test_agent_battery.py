"""Notation de la batterie agent (scripts/agent_battery.py), sans base ni agent."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import agent_battery as ab  # noqa: E402

CASES = {c['id']: c for c in json.loads((ROOT / 'tests/agent_battery/ecotaxa_cases.json').read_text())['cases']}


class NumberReadingTests(unittest.TestCase):
    def test_french_thousands_and_decimals(self):
        text = 'Le projet 14622 compte 1 687 393 objets (1 687 393), dont 187 567 validés; 2,23 mm; 11,1 %.'
        found = ab.numbers_in(text)
        for value in (14622, 1687393, 187567, 2.23, 11.1):
            self.assertIn(value, found)

    def test_separate_numbers_are_not_merged(self):
        # "73 profils" next to a year must not read as 732024.
        self.assertIn(73, ab.numbers_in('73 profils, du 4 octobre 2024'))
        self.assertNotIn(732024, ab.numbers_in('73 profils, du 4 octobre 2024'))


class MinusSignTests(unittest.TestCase):
    def test_true_minus_sign(self):
        self.assertIn(-0.2, ab.numbers_in('environ \u22120,2 \u00b0C'))


class ReportFormatTests(unittest.TestCase):
    def test_values_shown_as_people_write_them(self):
        self.assertEqual(ab.show(1687393.0), '1\u202f687\u202f393')
        self.assertEqual(ab.show(2.23), '2,23')


class GradingTests(unittest.TestCase):
    def test_correct_answer_passes(self):
        g = ab.grade(CASES['loki2015_validated'], '1 687 393 objets, dont 187 567 validés.', [1687393, 187567], [])
        self.assertTrue(g['passed'])

    def test_missing_value_fails(self):
        g = ab.grade(CASES['loki2015_validated'], '1 687 393 objets, environ 11 % validés.', [1687393, 187567], [])
        self.assertFalse(g['passed'])
        self.assertEqual(g['missing_values'], [187567])

    def test_summed_duplicates_fail(self):
        # GreenEdge 2016: adding 149 to its copies 20880 + 20890 double-counts the images.
        answer = 'Au total 3 021 726 objets (149 : 1 520 846, 20880 : 713 156, 20890 : 787 724).'
        g = ab.grade(CASES['greenedge2016_total'], answer, [1520846], [3021726])
        self.assertFalse(g['passed'])
        self.assertEqual(g['forbidden_values_found'], [3021726])

    def test_size_in_the_wrong_unit_fails(self):
        # The UVP6 bug: a copepod reported at 2 226 mm instead of 2,23 mm.
        case = CASES['amundsen2023_copepod_size']
        self.assertFalse(ab.grade(case, 'Taille moyenne : 2 226 mm (ESD non disponible).', [2.23], [])['passed'])
        self.assertTrue(ab.grade(case, 'Taille moyenne : 2,23 mm (ESD non disponible).', [2.23], [])['passed'])

    def test_abundance_from_predictions_alone_fails(self):
        # No validated Calanus in am_leg3: an abundance figure without saying so is wrong.
        case = CASES['leg3_calanus_validated']
        self.assertFalse(ab.grade(case, 'Abondance de Calanus : 36,6 ind/m³.', [0], [])['passed'])
        self.assertTrue(ab.grade(case, 'Aucun objet Calanus validé dans am_leg3.', [0], [])['passed'])

    def test_answer_without_any_query_fails(self):
        # Seen live: an agent answered the 500 m density question from climatology, without the database.
        case = CASES['loki2015_validated']
        answer = '1 687 393 objets, dont 187 567 validés.'
        self.assertFalse(ab.grade(case, answer, [1687393, 187567], [], sql_queries=0)['passed'])
        self.assertTrue(ab.grade(case, answer, [1687393, 187567], [], sql_queries=2)['passed'])

    def test_agent_environment_carries_no_credentials(self):
        import os
        os.environ['WAREHOUSE_POSTGRES_PASSWORD'] = 'secret'
        os.environ['PGPASSWORD'] = 'secret'
        try:
            env = ab.agent_env()
            self.assertFalse([k for k in env if k.startswith(ab.SECRET_PREFIXES)])
        finally:
            os.environ.pop('WAREHOUSE_POSTGRES_PASSWORD')
            os.environ.pop('PGPASSWORD')


if __name__ == '__main__':
    unittest.main()
