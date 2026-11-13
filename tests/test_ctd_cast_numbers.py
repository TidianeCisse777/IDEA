"""Liens EcoTaxa → CTD quand EcoTaxa ne cite que le numéro de cast (Amundsen 2023-2024).

Le numéro cité fait foi (décision du 13 novembre 2026) : constaté sur la base, l'ancienne résolution par position
liait 20 profils au cast voisin du même jour (ex. cité 079, lié à 080). Sans réseau ni base.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import populate_ctd_proximity as prox  # noqa: E402

T0 = datetime(2023, 9, 5, 20, 24, 2, tzinfo=timezone.utc)


def cast(number, hours, filename=None, dataset='amundsen12713', lat=70.0, lon=-60.0):
    return {'dataset': dataset, 'family': 'rosette', 'cast': str(number), 'time': T0 + timedelta(hours=hours),
            'filename': filename or f'AS_CTD_2023_02_{int(float(number)):03d}.csv.nc', 'lat': lat, 'lon': lon,
            'station': '305', 'cruise': '2302'}


def sample(cited, sid=1, when=T0):
    return {'id': sid, 'cited': cited, 'time': when}


class CastNumberResolution(unittest.TestCase):
    def test_the_cited_cast_wins_over_a_nearer_one(self):
        # Three casts the same day at the same station; 080 is the nearest in time and position.
        casts = [cast(78, -3), cast(79, 1.8), cast(80, 0.1, lat=70.0001)]
        resolved, refused = prox.resolve_cast_numbers([sample('079')], casts)
        self.assertEqual(resolved[1]['filename'], 'AS_CTD_2023_02_079.csv.nc')
        self.assertEqual(refused, {})

    def test_numbers_are_compared_as_numbers(self):
        resolved, _ = prox.resolve_cast_numbers([sample(' 79 '), sample('079', sid=2)], [cast('79.0', 2)])
        self.assertEqual(sorted(resolved), [1, 2])

    def test_two_legs_with_the_same_number_within_24_h_give_no_link(self):
        casts = [cast(79, 2), cast(79, 20, filename='AS_CTD_2023_03_079.csv.nc')]
        resolved, refused = prox.resolve_cast_numbers([sample('079')], casts)
        self.assertEqual(resolved, {})
        self.assertTrue(refused[1].startswith('ambigu'))

    def test_the_date_tells_legs_apart(self):
        casts = [cast(79, 2), cast(79, 24 * 30, filename='AS_CTD_2023_03_079.csv.nc')]
        resolved, _ = prox.resolve_cast_numbers([sample('079')], casts)
        self.assertEqual(resolved[1]['filename'], 'AS_CTD_2023_02_079.csv.nc')

    def test_no_fallback_on_position_when_the_cited_cast_is_missing(self):
        casts = [cast(80, 0.1), cast(79, 48)]          # 079 exists, but two days away
        resolved, refused = prox.resolve_cast_numbers([sample('079')], casts)
        self.assertEqual(resolved, {})
        self.assertIn(1, refused)

    def test_only_rosette_casts_and_only_bare_numbers(self):
        casts = [cast(79, 1, dataset='amundsen12716', filename='bioness_079')]
        resolved, refused = prox.resolve_cast_numbers([sample('079')], casts)
        self.assertEqual(resolved, {})
        # Full file names are resolved elsewhere (normalised name), never as cast numbers.
        resolved, refused = prox.resolve_cast_numbers(
            [sample('2105016'), sample('sbe19plus_01907420_2015_04_18-uvp', 2), sample('xx', 3)], [cast(79, 1)])
        self.assertEqual((resolved, refused), ({}, {}))

    def test_a_sample_without_date_is_not_linked(self):
        resolved, refused = prox.resolve_cast_numbers([sample('079', when=None)], [cast(79, 1)])
        self.assertEqual((resolved, refused), ({}, {1: 'date absente'}))


class Times(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(prox.parse_time('2023-09-05 20:24:02+00'), T0)
        self.assertEqual(prox.parse_time('2023-09-05T20:24:02Z'), T0)
        self.assertEqual(prox.parse_time('2023-09-05 20:24:02'), T0)
        self.assertIsNone(prox.parse_time(''))
        self.assertIsNone(prox.parse_time(None))


class LoaderUsesTheSameRule(unittest.TestCase):
    def test_amundsen_loader_no_longer_resolves_by_position(self):
        text = (ROOT / 'scripts' / 'populate_amundsen_ctd.py').read_text(encoding='utf-8')
        self.assertNotIn('resolve_by_position', text)
        self.assertIn('resolve_cast_numbers', text)
        self.assertNotIn('*80', text)


if __name__ == '__main__':
    unittest.main()
