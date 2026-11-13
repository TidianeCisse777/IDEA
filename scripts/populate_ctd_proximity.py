#!/usr/bin/env python3
"""Relier par proximité (espace, temps) les profils UVP et les déploiements FILET sans CTD aux profils CTD
d'Amundsen Science (ERDDAP), et charger les profils CTD nécessaires.

    python scripts/populate_ctd_proximity.py [--dry-run]

Sources ERDDAP (https://erddap.amundsenscience.com) : CTD de rosette amundsen12713 (2014-2024) et jeux de campagne
ArcticNet 2010-2013 (mêmes variables); CTD montée sur le Bioness (amundsen12716 : pression, température ITS-90,
salinité PSS-78, numéro de filet, d'après les métadonnées ERDDAP). La CTD du filet Hydrobios (amundsen12717) n'est pas
utilisée : ses pression, température et salinité sont vides (NaN) sur tout le jeu ERDDAP. Jamais de lien vers un
profil CTD sans pression.

Règle : pour chaque cible (profil UVP sans lien CTD par fichier; déploiement FILET), le profil CTD le plus proche
de chaque source applicable (rosette pour tous; filet Hydrobios ou Bioness pour ces engins), au score
distance/10 km + écart/6 h. Gardé si ≤ 10 km et ≤ 12 h : « accepted » si ≤ 5 km et ≤ 6 h, sinon « candidate ».
Distance haversine entre positions; écart entre l'heure du début de profil CTD et celle de la cible (UTC). Les liens
« proximity » sont remplacés à chaque exécution; les liens par fichier (EcoTaxa) ne sont jamais touchés.

Avant la proximité : un échantillon EcoTaxa dont ctd_rosette_filename n'est qu'un numéro de cast (« 079 », Amundsen
2023-2024) est relié au profil de rosette de ce numéro, à ≤ 24 h de l'échantillon (le fichier cité fait foi; jamais de
repli sur la position). Ces liens remplacent les liens par fichier de ces échantillons, puis les liens UVP–CTD par
fichier sont recalculés (sql/warehouse_uvp_ctd_links.sql).
Connexion : variables WAREHOUSE_POSTGRES_* (compte propriétaire). Bibliothèque standard + psycopg.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERDDAP = 'https://erddap.amundsenscience.com/erddap/tabledap'
ROSETTE = ['amundsen12713', 'amundsen11150', 'amundsen11151', 'amundsen11153', 'amundsen11154', 'amundsen11155',
           'amundsen11943', 'amundsen11156', 'amundsen11922', 'amundsen11919', 'amundsen11920', 'amundsen11921',
           'amundsen11923', 'amundsen11924', 'amundsen11927', 'amundsen11926']
# amundsen12717 (CTD of the Hydrobios net) is not used: Pres, Temp and Sal are NaN for the whole dataset on the
# ERDDAP (only Net is filled, checked 12 November 2026), so its profiles carry no measurement to compare.
NET = {'amundsen12716': 'bioness'}
ROSETTE_VARS = {'PRES': 'PRES', 'TE90': 'TE90', 'PSAL': 'PSAL', 'SIGT': 'SIGT', 'OXYM': 'OXYM', 'pH': 'pH',
                'NTRA': 'NTRA', 'FLOR': 'FLOR'}
NET_VARS = {'Pres': 'PRES', 'Temp': 'TE90', 'Sal': 'PSAL', 'Net': 'NET'}
ACCEPT_KM, ACCEPT_H = 5.0, 6.0
CANDIDATE_KM, CANDIDATE_H = 10.0, 12.0
CAST_DATASET, CAST_WINDOW_H = 'amundsen12713', 24.0
CAST_NUMBER = re.compile(r'\s*(\d{1,3})\s*')


def get_csv(dataset: str, query: str, retries: int = 3) -> list[dict]:
    url = f'{ERDDAP}/{dataset}.csv?{query}'
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=600) as response:
                lines = response.read().decode('utf-8').splitlines()
            return list(csv.DictReader([lines[0]] + lines[2:]))      # line 2 holds the units
        except urllib.error.HTTPError as error:
            if error.code == 404:                                    # ERDDAP: no matching row
                return []
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(3 * (attempt + 1))
    return []


def when(text: str) -> datetime:
    return datetime.strptime(text[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)


def cast_index(datasets: list[str] | None = None) -> list[dict]:
    """One row per CTD profile (first scan): dataset, family, filename, time, position, station, cast number."""
    fields = 'filename,cruise_number,cast_number,station,time,latitude,longitude'
    order = urllib.parse.quote('orderByMin("filename,time")')
    casts = []
    for dataset in datasets or ROSETTE + list(NET):
        family = NET.get(dataset, 'rosette')
        windows = ([(f'{y}-01-01T00:00:00Z', f'{y + 1}-01-01T00:00:00Z') for y in range(2014, 2025)]
                   if dataset == 'amundsen12713' else [(None, None)])
        for start, end in windows:
            query = fields + (f'&time>={start}&time<{end}' if start else '') + '&' + order
            for row in get_csv(dataset, query):
                if not row.get('time') or row.get('latitude') in ('', 'NaN') or row.get('longitude') in ('', 'NaN'):
                    continue
                casts.append({'dataset': dataset, 'family': family, 'filename': row['filename'],
                              'time': when(row['time']), 'lat': float(row['latitude']), 'lon': float(row['longitude']),
                              'station': row.get('station') or None, 'cruise': row.get('cruise_number') or None,
                              'cast': row.get('cast_number') or None})
    return casts


def parse_time(value) -> datetime | None:
    """A timestamp from the database or psql text ('2023-09-05 20:24:02+00'), in UTC; None if absent."""
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip().replace(' ', 'T')
    if not text:
        return None
    if re.search(r'[+-]\d\d$', text):
        text += ':00'
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_cast_numbers(samples: list[dict], casts: list[dict]) -> tuple[dict, dict]:
    """EcoTaxa samples citing only a cast number ('079'): that number is the source of truth. Keeps the rosette
    profile (amundsen12713) with this cast_number whose first scan is ≤ 24 h from the sample — the date tells legs
    apart, as each leg restarts its numbering. None or several files: no link, never a fallback on position.
    samples: [{'id', 'cited', 'time'}]. Returns ({sample id: cast}, {sample id: reason})."""
    by_number = {}
    for c in casts:
        if c['dataset'] != CAST_DATASET or c.get('cast') in (None, '', 'NaN'):
            continue
        try:
            by_number.setdefault(int(float(c['cast'])), []).append(c)
        except ValueError:
            continue
    resolved, refused = {}, {}
    for s in samples:
        cited = CAST_NUMBER.fullmatch(str(s['cited'] or ''))
        if not cited:
            continue
        if s['time'] is None:
            refused[s['id']] = 'date absente'
            continue
        hits = {c['filename']: c for c in by_number.get(int(cited.group(1)), [])
                if abs((c['time'] - s['time']).total_seconds()) <= CAST_WINDOW_H * 3600}
        if len(hits) == 1:
            resolved[s['id']] = next(iter(hits.values()))
        else:
            refused[s['id']] = 'ambigu : ' + ', '.join(sorted(hits)) if hits else 'aucun cast de ce numéro à ≤ 24 h'
    return resolved, refused


def cast_number_samples(conn) -> list[dict]:
    rows = conn.execute("""SELECT id, ctd_rosette_filename, coalesce(datetime_min, datetime_max)
        FROM warehouse.ecotaxa_sample WHERE ctd_rosette_filename ~ '^\\s*\\d{1,3}\\s*$'""").fetchall()
    return [{'id': i, 'cited': f, 'time': parse_time(t)} for i, f, t in rows]


def write_cast_number_links(conn, samples: list[dict], resolved: dict, ids: dict[str, int]) -> int:
    """Replaces the filename links of these samples by the cited cast, then recomputes UVP–CTD filename links."""
    written = 0
    with conn.transaction():
        conn.execute("DELETE FROM warehouse.ecotaxa_ctd WHERE relation_type = 'filename_exact' AND ecotaxa_sample_id = ANY(%s)",
                     ([s['id'] for s in samples],))
        when = {s['id']: s['time'] for s in samples}
        for sid, c in resolved.items():
            pid = ids.get(c['filename'])
            if pid is None:
                continue
            gap = round(abs((c['time'] - when[sid]).total_seconds()) / 60, 1)
            conn.execute("""INSERT INTO warehouse.ecotaxa_ctd (ecotaxa_sample_id, ctd_profile_id, relation_type, filename_match,
                station_match, distance_km, time_gap_minutes, match_status, evidence)
                VALUES (%s, %s, 'filename_exact', TRUE, NULL, NULL, %s, 'accepted', %s)
                ON CONFLICT (ecotaxa_sample_id, ctd_profile_id) DO UPDATE SET relation_type = 'filename_exact',
                filename_match = TRUE, match_status = 'accepted', time_gap_minutes = EXCLUDED.time_gap_minutes,
                evidence = EXCLUDED.evidence""",
                (sid, pid, gap, f"EcoTaxa ctd_rosette_filename = numéro de cast {c['cast']} → {c['filename']} "
                               f"({CAST_DATASET}, ≤ {CAST_WINDOW_H:g} h)"))
            written += 1
        # Proximity is only for profiles without a filename link: drop it where the cited cast now links them.
        conn.execute("""DELETE FROM warehouse.uvp_ctd u WHERE u.link_method = 'proximity' AND EXISTS (
            SELECT 1 FROM warehouse.uvp_ecotaxa l JOIN warehouse.ecotaxa_ctd c ON c.ecotaxa_sample_id = l.ecotaxa_sample_id
            WHERE l.uvp_profile_id = u.uvp_profile_id AND c.match_status = 'accepted')""")
        conn.execute((ROOT / 'sql' / 'warehouse_uvp_ctd_links.sql').read_text(encoding='utf-8'))
    return written


def km(lat1, lon1, lat2, lon2) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def targets(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT 'uvp', p.id::text, NULL::text, p.sampled_at,
               coalesce(p.latitude, (SELECT avg(e.lat_avg) FROM warehouse.uvp_ecotaxa l
                                     JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id WHERE l.uvp_profile_id = p.id)),
               coalesce(p.longitude, (SELECT avg(e.lon_avg) FROM warehouse.uvp_ecotaxa l
                                      JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id WHERE l.uvp_profile_id = p.id))
        FROM warehouse.uvp_profile p
        WHERE NOT EXISTS (SELECT 1 FROM warehouse.uvp_ctd c WHERE c.uvp_profile_id = p.id AND c.link_method = 'filename_transitive')
        UNION ALL
        SELECT 'filet', s.deployment_id::text, lower(min(s.gear)), min(s.deployment_datetime_start) AT TIME ZONE 'UTC',
               avg(s.latitude), avg(s.longitude)
        FROM warehouse.filet_sample s GROUP BY s.deployment_id""").fetchall()
    return [{'kind': k, 'id': i, 'gear': g, 'time': t, 'lat': la, 'lon': lo}
            for k, i, g, t, la, lo in rows if t is not None and la is not None and lo is not None]


def match(target_rows: list[dict], casts: list[dict]) -> list[dict]:
    links = []
    for t in target_rows:
        families = ['rosette'] + ([t['gear']] if t['kind'] == 'filet' and t['gear'] in NET.values() else [])
        for family in families:
            best = None
            for c in casts:
                if c['family'] != family:
                    continue
                hours = abs((c['time'] - t['time']).total_seconds()) / 3600
                if hours > CANDIDATE_H:
                    continue
                distance = km(t['lat'], t['lon'], c['lat'], c['lon'])
                if distance > CANDIDATE_KM:
                    continue
                score = distance / 10 + hours / 6
                if best is None or score < best[0]:
                    best = (score, distance, hours, c)
            if best:
                _, distance, hours, c = best
                status = 'accepted' if distance <= ACCEPT_KM and hours <= ACCEPT_H else 'candidate'
                links.append({**t, 'cast': c, 'distance': round(distance, 2), 'hours': round(hours, 2), 'status': status})
    return links


def version_id(conn, dataset: str) -> int:
    return conn.execute("""INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, file_manifest_uri, sha256)
        VALUES ('amundsen_ctd', %s, 'current', %s, 'erddap-live') ON CONFLICT (source_instance, dataset_key, version_key)
        DO UPDATE SET file_manifest_uri = EXCLUDED.file_manifest_uri RETURNING id""", (dataset, f'{ERDDAP}/{dataset}')).fetchone()[0]


def load_profiles(conn, casts: list[dict]) -> dict[str, int]:
    """Profiles not yet in the warehouse, fetched by filename, 20 at a time; returns filename → ctd_profile.id."""
    known = dict(conn.execute('SELECT source_profile_key, id FROM warehouse.ctd_profile').fetchall())
    wanted = {}
    for c in casts:
        if c['filename'] not in known:
            wanted.setdefault(c['dataset'], {})[c['filename']] = c
    for dataset, by_name in wanted.items():
        variables = NET_VARS if dataset in NET else ROSETTE_VARS
        vid = version_id(conn, dataset)
        names = sorted(by_name)
        for start in range(0, len(names), 20):
            batch = names[start:start + 20]
            regex = '^(' + '|'.join(re.escape(n) for n in batch) + ')$'
            query = 'filename,time,' + ','.join(variables) + '&filename=~' + urllib.parse.quote(f'"{regex}"')
            rows = get_csv(dataset, query)
            with conn.transaction():
                for name in batch:
                    c = by_name[name]
                    known[name] = conn.execute("""INSERT INTO warehouse.ctd_profile
                        (dataset_version_id, source_profile_key, cruise_key, station_key, sampled_at, latitude, longitude)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dataset_version_id, source_profile_key) DO UPDATE
                        SET sampled_at = EXCLUDED.sampled_at RETURNING id""",
                        (vid, name, c['cruise'], c['station'], c['time'], c['lat'], c['lon'])).fetchone()[0]
                buffer, scan = io.StringIO(), {}
                writer = csv.writer(buffer, delimiter='\t', lineterminator='\n')
                for row in rows:
                    pid = known.get(row['filename'])
                    if pid is None:
                        continue
                    index = scan[pid] = scan.get(pid, -1) + 1
                    pressure = row.get('PRES' if 'PRES' in variables else 'Pres') or ''
                    pressure = '' if pressure in ('', 'NaN') else pressure
                    for source_name, key in variables.items():
                        value = row.get(source_name)
                        if value in (None, '', 'NaN'):
                            continue
                        writer.writerow([pid, f'{row["filename"]}:{index}:{key}', index, pressure or '\\N',
                                         (pressure or '\\N') if key == 'PRES' else '\\N', key, source_name, source_name,
                                         value, '\\N'])
                with conn.cursor() as cur:
                    cur.execute("""CREATE TEMP TABLE IF NOT EXISTS stage_ctd (profile_id bigint, source_row_key text,
                        scan_key text, depth_m double precision, pressure_dbar double precision, variable_key text,
                        variable_definition text, sensor_channel text, value double precision, qc text) ON COMMIT DELETE ROWS""")
                    with cur.copy("COPY stage_ctd FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')") as copy:
                        copy.write(buffer.getvalue())
                    cur.execute("""INSERT INTO warehouse.ctd_measurement (profile_id, source_row_key, scan_key, depth_m,
                        pressure_dbar, variable_key, variable_definition, sensor_channel, value, unit, qc)
                        SELECT s.profile_id, s.source_row_key, s.scan_key, s.depth_m, s.pressure_dbar, s.variable_key,
                               v.canonical_name, s.sensor_channel, s.value, v.canonical_unit, s.qc
                        FROM stage_ctd s JOIN warehouse.ctd_variable v ON v.variable_key = s.variable_key
                        ON CONFLICT (profile_id, source_row_key) DO NOTHING""")
            print(f'[ctd] {dataset} : {min(start + 20, len(names))}/{len(names)} profils chargés', flush=True)
    return known


def write_links(conn, links: list[dict], ids: dict[str, int]) -> dict:
    # Never link to a CTD profile without pressure: its measurements cannot be placed on the water column.
    with_pressure = {pid for (pid,) in conn.execute(
        "SELECT DISTINCT profile_id FROM warehouse.ctd_measurement WHERE variable_key = 'PRES' AND value IS NOT NULL").fetchall()}
    with conn.transaction():
        conn.execute("DELETE FROM warehouse.uvp_ctd WHERE link_method = 'proximity'")
        conn.execute("DELETE FROM warehouse.filet_ctd WHERE link_method = 'proximity'")
        counts = {}
        for link in links:
            c = link['cast']
            pid = ids.get(c['filename'])
            if pid is None or pid not in with_pressure:
                continue
            evidence = json.dumps({'rule': 'nearest CTD by distance/10 km + gap/6 h', 'erddap_dataset': c['dataset'],
                                   'ctd_filename': c['filename'], 'ctd_station': c['station'],
                                   'distance_km': link['distance'], 'time_gap_hours': link['hours']}, ensure_ascii=False)
            values = (pid, evidence, c['family'], link['distance'], link['hours'], link['status'])
            if link['kind'] == 'uvp':
                conn.execute("""INSERT INTO warehouse.uvp_ctd (uvp_profile_id, ctd_profile_id, source_evidence, link_method,
                    ctd_source, distance_km, time_gap_hours, match_status) VALUES (%s,%s,%s,'proximity',%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""", (int(link['id']), *values))
            else:
                conn.execute("""INSERT INTO warehouse.filet_ctd (filet_sample_id, ctd_profile_id, source_evidence, link_method,
                    ctd_source, distance_km, time_gap_hours, match_status)
                    SELECT s.id, %s, %s, 'proximity', %s, %s, %s, %s FROM warehouse.filet_sample s WHERE s.deployment_id::text = %s
                    ON CONFLICT DO NOTHING""", (*values, link['id']))
            key = (link['kind'], c['family'], link['status'])
            counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='compter les liens sans rien écrire ni télécharger de mesures')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / 'scripts'))
    from populate_filet import connection
    casts = cast_index()
    print(f'[ctd] index ERDDAP : {len(casts)} profils CTD', flush=True)
    with connection() as conn:
        cited = cast_number_samples(conn)
        resolved, refused = resolve_cast_numbers(cited, casts)
        print(f'[ctd] numéros de cast EcoTaxa : {len(cited)} échantillons, {len(resolved)} résolus, '
              f'{len(refused)} sans lien' + (f' ({json.dumps(dict(sorted(refused.items())[:5]), ensure_ascii=False)}…)'
                                             if refused else ''), flush=True)
        if not args.dry_run and cited:
            ids = load_profiles(conn, list(resolved.values()))
            print(f'[ctd] liens EcoTaxa par numéro de cast écrits : '
                  f'{write_cast_number_links(conn, cited, resolved, ids)}', flush=True)
        target_rows = targets(conn)
        links = match(target_rows, casts)
        summary = {}
        for link in links:
            key = f"{link['kind']}/{link['cast']['family']}/{link['status']}"
            summary[key] = summary.get(key, 0) + 1
        print(f'[ctd] cibles : {len(target_rows)}; liens : {json.dumps(summary, ensure_ascii=False)}', flush=True)
        known = {k for (k,) in conn.execute('SELECT source_profile_key FROM warehouse.ctd_profile').fetchall()}
        new = {(l['cast']['dataset'], l['cast']['filename']) for l in links if l['cast']['filename'] not in known}
        print(f'[ctd] profils CTD à télécharger : {len(new)} (déjà présents : '
              f'{len({l["cast"]["filename"] for l in links} - {f for _, f in new})})', flush=True)
        if args.dry_run:
            return 0
        ids = load_profiles(conn, [link['cast'] for link in links])
        counts = write_links(conn, links, ids)
        print('[ctd] liens écrits : ' + ', '.join(f'{k[0]}/{k[1]}/{k[2]}={v}' for k, v in sorted(counts.items())), flush=True)
    from assign_filet_zones import assign
    print('[ctd] zones des profils CTD : ' + json.dumps(assign(table='ctd_profile'), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
