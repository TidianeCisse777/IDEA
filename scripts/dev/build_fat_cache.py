"""Build a fat EcoTaxa cache for e2e testing.

Starts from the real cache (data/ecotaxa_cache.sqlite) and injects realistic
synthetic campaigns: named legs, distributed lat/lon grids within each zone,
nb_validated/predicted/dubious/unclassified, used_taxa, profile_id derived
from original_id, and objects_cache entries.

Output: data/ecotaxa_cache_fat.sqlite  (real data + synthetic)
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from core.ecotaxa_browser.cache.repo import (
    SCHEMA_VERSION,
    init_schema,
    set_schema_version,
    upsert_sample,
)

REAL_CACHE = Path("data/ecotaxa_cache.sqlite")
FAT_CACHE = Path("data/ecotaxa_cache_fat.sqlite")

random.seed(42)

# ---------------------------------------------------------------------------
# Campaigns to inject
# Each entry: (project_id, name, instrument, year, stations)
# stations: list of (lat, lon, station_label) — spread within zone
# ---------------------------------------------------------------------------
CAMPAIGNS: list[dict] = [
    {
        "project_id": 80001,
        "name": "ArcticNet-2017-UVP6-Baffin",
        "instrument": "UVP6",
        "year": 2017,
        "stations": [
            (76.2, -72.5, "BB01"), (77.1, -70.8, "BB02"), (75.5, -74.1, "BB03"),
            (78.3, -68.2, "BB04"), (79.0, -66.0, "BB05"), (80.1, -64.5, "BB06"),
            (74.8, -75.0, "BB07"), (76.8, -69.3, "BB08"),
        ],
        "n_casts_per_station": 3,
        "month_start": "07",
    },
    {
        "project_id": 80002,
        "name": "ArcticNet-2017-Loki-LancasterSound",
        "instrument": "Loki",
        "year": 2017,
        "stations": [
            (74.2, -90.0, "LS01"), (74.8, -88.5, "LS02"), (75.3, -87.0, "LS03"),
            (73.9, -91.5, "LS04"), (75.0, -85.0, "LS05"), (74.5, -92.0, "LS06"),
        ],
        "n_casts_per_station": 2,
        "month_start": "08",
    },
    {
        "project_id": 80010,
        "name": "GreenEdge-2016-UVP5SD-Baffin",
        "instrument": "UVP5SD",
        "year": 2016,
        "stations": [
            (67.5, -63.8, "GE01"), (67.9, -63.2, "GE02"), (68.4, -62.7, "GE03"),
            (68.8, -62.1, "GE04"), (69.2, -61.5, "GE05"), (67.1, -64.3, "GE06"),
            (69.7, -61.0, "GE07"), (70.2, -60.5, "GE08"),
        ],
        "n_casts_per_station": 4,
        "month_start": "05",
    },
    {
        "project_id": 80020,
        "name": "Amundsen-2019-leg1-Labrador",
        "instrument": "UVP6",
        "year": 2019,
        "stations": [
            (57.5, -54.0, "LA01"), (58.2, -55.3, "LA02"), (59.0, -56.1, "LA03"),
            (60.1, -57.5, "LA04"), (61.3, -58.8, "LA05"), (62.0, -60.0, "LA06"),
            (63.1, -59.2, "LA07"), (56.8, -53.5, "LA08"), (55.5, -52.0, "LA09"),
        ],
        "n_casts_per_station": 3,
        "month_start": "06",
    },
    {
        "project_id": 80021,
        "name": "Amundsen-2019-leg2-DavisStrait",
        "instrument": "UVP6",
        "year": 2019,
        "stations": [
            (65.0, -57.5, "DS01"), (66.2, -57.0, "DS02"), (67.1, -56.5, "DS03"),
            (68.0, -56.0, "DS04"), (64.3, -58.2, "DS05"), (69.0, -55.5, "DS06"),
        ],
        "n_casts_per_station": 3,
        "month_start": "07",
    },
    {
        "project_id": 80030,
        "name": "ArcticNet-2020-UVP6-Beaufort",
        "instrument": "UVP6",
        "year": 2020,
        "stations": [
            (71.0, -138.0, "BF01"), (71.5, -135.0, "BF02"), (72.0, -132.0, "BF03"),
            (72.5, -129.0, "BF04"), (73.0, -126.0, "BF05"), (70.5, -141.0, "BF06"),
            (73.5, -123.0, "BF07"), (71.8, -136.5, "BF08"),
        ],
        "n_casts_per_station": 3,
        "month_start": "08",
    },
    {
        "project_id": 80031,
        "name": "ArcticNet-2020-Loki-Beaufort",
        "instrument": "Loki",
        "year": 2020,
        "stations": [
            (70.2, -140.5, "BF09"), (71.2, -137.0, "BF10"), (72.3, -133.5, "BF11"),
            (73.3, -130.0, "BF12"), (74.0, -127.0, "BF13"),
        ],
        "n_casts_per_station": 2,
        "month_start": "09",
    },
    {
        "project_id": 80040,
        "name": "HudsonBay-2018-UVP5SD",
        "instrument": "UVP5SD",
        "year": 2018,
        "stations": [
            (60.0, -85.0, "HB01"), (60.8, -83.5, "HB02"), (61.5, -82.0, "HB03"),
            (62.2, -80.5, "HB04"), (59.3, -86.5, "HB05"), (63.0, -79.0, "HB06"),
            (58.5, -88.0, "HB07"), (63.8, -77.5, "HB08"),
        ],
        "n_casts_per_station": 3,
        "month_start": "07",
    },
    {
        "project_id": 80050,
        "name": "ArcticNet-2022-UVP6-Lincoln",
        "instrument": "UVP6",
        "year": 2022,
        "stations": [
            (82.0, -70.0, "LC01"), (82.5, -68.0, "LC02"), (83.0, -66.0, "LC03"),
            (81.5, -72.0, "LC04"), (83.5, -64.0, "LC05"), (82.8, -74.0, "LC06"),
        ],
        "n_casts_per_station": 2,
        "month_start": "08",
    },
    {
        "project_id": 80060,
        "name": "StLawrence-2021-Loki-Gulf",
        "instrument": "Loki",
        "year": 2021,
        "stations": [
            (48.0, -64.5, "GL01"), (48.5, -63.0, "GL02"), (49.0, -61.5, "GL03"),
            (47.5, -66.0, "GL04"), (49.5, -60.0, "GL05"), (50.0, -59.0, "GL06"),
            (47.0, -67.5, "GL07"),
        ],
        "n_casts_per_station": 4,
        "month_start": "06",
    },
    {
        "project_id": 80070,
        "name": "ArcticNet-2023-UVP6-MultiZone",
        "instrument": "UVP6",
        "year": 2023,
        "stations": [
            # Baffin
            (76.5, -71.0, "MZ01"), (77.5, -69.0, "MZ02"),
            # Beaufort
            (71.5, -136.0, "MZ03"), (72.5, -133.0, "MZ04"),
            # Labrador
            (59.0, -55.0, "MZ05"), (60.5, -57.0, "MZ06"),
            # Davis
            (66.0, -57.5, "MZ07"), (67.5, -56.0, "MZ08"),
        ],
        "n_casts_per_station": 3,
        "month_start": "07",
    },
    {
        "project_id": 80080,
        "name": "Amundsen-2021-leg3-HudsonStrait",
        "instrument": "UVP6",
        "year": 2021,
        "stations": [
            (62.0, -70.0, "HS01"), (62.5, -71.5, "HS02"), (63.0, -73.0, "HS03"),
            (61.5, -68.5, "HS04"), (63.5, -74.5, "HS05"), (61.0, -67.0, "HS06"),
        ],
        "n_casts_per_station": 3,
        "month_start": "09",
    },
]

TAXA = [
    "Calanus glacialis", "Calanus hyperboreus", "Calanus finmarchicus",
    "Pseudocalanus spp.", "Oithona similis", "Metridia longa",
    "Euphausiaceae", "Chaetognatha", "Appendicularia", "Copepoda",
]

STATUSES = ("V", "P", "D", "U")


def _sample_date(year: int, month_start: str, station_idx: int, cast_idx: int) -> str:
    base = date(year, int(month_start), 1)
    return (base + timedelta(days=station_idx * 5 + cast_idx * 2)).isoformat()


def _jitter(value: float, amplitude: float) -> float:
    return value + random.uniform(-amplitude, amplitude)


def _used_taxa_json(n: int = 4) -> str:
    chosen = random.sample(TAXA, min(n, len(TAXA)))
    return json.dumps([{"taxon": t, "count": random.randint(5, 200)} for t in chosen])


def _nb_counts(total: int) -> tuple[int, int, int, int]:
    v = int(total * random.uniform(0.3, 0.7))
    p = int(total * random.uniform(0.1, 0.4))
    d = int(total * random.uniform(0.0, 0.1))
    u = max(0, total - v - p - d)
    return v, p, d, u


def build_fat_cache(
    source: Path = REAL_CACHE,
    output: Path = FAT_CACHE,
    *,
    force: bool = False,
) -> dict:
    if output.exists() and not force:
        raise FileExistsError(f"{output} exists — pass --force to overwrite.")

    print(f"Copying {source} → {output} …")
    shutil.copy2(source, output)

    conn = sqlite3.connect(output)
    conn.row_factory = sqlite3.Row
    init_schema(conn)

    # Ensure objects_cache exists (absent from real cache, present in synthetic)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS objects_cache (
            object_id   INTEGER PRIMARY KEY,
            sample_id   INTEGER NOT NULL,
            project_id  INTEGER NOT NULL,
            original_id TEXT NOT NULL,
            object_date TEXT,
            depth_min   REAL,
            depth_max   REAL,
            taxon       TEXT NOT NULL,
            classification_status TEXT NOT NULL,
            latitude    REAL,
            longitude   REAL,
            free_fields_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_objects_sample ON objects_cache(sample_id);
        CREATE INDEX IF NOT EXISTS idx_objects_project ON objects_cache(project_id);
    """)

    now = "fat-cache-2026-07-20"
    total_samples = 0
    total_objects = 0

    for camp in CAMPAIGNS:
        pid = camp["project_id"]
        instrument = camp["instrument"]
        year = camp["year"]
        month_start = camp["month_start"]
        n_casts = camp["n_casts_per_station"]
        stations = camp["stations"]

        proj_samples = 0
        proj_objects = 0

        for st_idx, (lat, lon, station_label) in enumerate(stations):
            for cast_idx in range(n_casts):
                # Spread samples slightly around the nominal station position
                s_lat = _jitter(lat, 0.15)
                s_lon = _jitter(lon, 0.20)
                s_date = _sample_date(year, month_start, st_idx, cast_idx)
                depth_min = round(_jitter(10.0, 5), 2)
                depth_max = round(_jitter(400.0, 150), 2)
                obj_count = random.randint(20, 300)
                nb_v, nb_p, nb_d, nb_u = _nb_counts(obj_count)

                # profile_id = station + cast (no trailing _N)
                profile_id = f"{camp['name']}_{station_label}_c{cast_idx + 1}"
                original_id = f"{profile_id}_{cast_idx + 1}"

                sample_id = pid * 10_000 + st_idx * 10 + cast_idx + 1

                upsert_sample(
                    conn,
                    sample_id=sample_id,
                    project_id=pid,
                    lat_avg=s_lat,
                    lon_avg=s_lon,
                    date_min=s_date,
                    date_max=s_date,
                    depth_min=depth_min,
                    depth_max=depth_max,
                    original_id=original_id,
                    station_id=station_label,
                    profile_id=profile_id,
                    free_fields_json=json.dumps({"source": "fat_cache"}),
                    object_count=obj_count,
                    instrument=instrument,
                    last_synced=now,
                )
                conn.execute(
                    """UPDATE samples_cache
                       SET nb_validated=?, nb_predicted=?, nb_dubious=?,
                           nb_unclassified=?, used_taxa=?
                       WHERE sample_id=?""",
                    (nb_v, nb_p, nb_d, nb_u, _used_taxa_json(), sample_id),
                )
                proj_samples += 1
                total_samples += 1

                # Insert synthetic objects
                for obj_idx in range(min(obj_count, 12)):
                    status = STATUSES[obj_idx % len(STATUSES)]
                    taxon = TAXA[obj_idx % len(TAXA)]
                    object_id = sample_id * 1000 + obj_idx + 1
                    conn.execute("""
                        INSERT OR IGNORE INTO objects_cache
                        (object_id, sample_id, project_id, original_id, object_date,
                         depth_min, depth_max, taxon, classification_status,
                         latitude, longitude, free_fields_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        object_id, sample_id, pid,
                        f"{original_id}_{obj_idx + 1:03d}",
                        s_date, depth_min, depth_max,
                        taxon, status, s_lat, s_lon,
                        json.dumps({"fat_cache": True}),
                    ))
                    proj_objects += 1
                    total_objects += 1

        # project_schemas_cache + project_signatures_cache
        schema = {
            "title": camp["name"],
            "instrument": instrument,
            "levels": ["sample", "cast", "object"],
            "columns": ["sample_id", "station_id", "profile_id", "taxon"],
        }
        conn.execute(
            "INSERT OR REPLACE INTO project_schemas_cache VALUES (?, ?, ?)",
            (pid, json.dumps(schema), now),
        )
        pct_validated = round(100 * random.uniform(0.3, 0.9), 1)
        conn.execute(
            "INSERT OR REPLACE INTO project_signatures_cache VALUES (?, ?, ?, ?, ?)",
            (pid, proj_objects, pct_validated, 100.0, now),
        )
        print(f"  {camp['name']}: {proj_samples} samples, {proj_objects} objects")

    conn.execute("""
        INSERT INTO sync_runs (started_at, ended_at, status, projects_synced, samples_synced, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (now, now, "ok", len(CAMPAIGNS), total_samples, None))

    set_schema_version(conn, SCHEMA_VERSION)
    conn.commit()
    conn.close()

    return {
        "output": str(output),
        "campaigns_injected": len(CAMPAIGNS),
        "samples_added": total_samples,
        "objects_added": total_objects,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REAL_CACHE)
    parser.add_argument("--output", type=Path, default=FAT_CACHE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build_fat_cache(args.source, args.output, force=args.force)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
