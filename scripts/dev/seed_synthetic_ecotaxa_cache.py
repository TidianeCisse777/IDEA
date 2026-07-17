"""Seed an isolated, deterministic EcoTaxa cache for exploration tests.

This fixture deliberately never touches ``data/ecotaxa_cache.sqlite`` unless
the caller explicitly supplies that path. It covers every zone in the NeoLab
registry with multiple projects, stations, casts, samples, and synthetic
objects.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample
from core.geo import load_registry

DEFAULT_OUTPUT = Path("data/ecotaxa_cache_synthetic.sqlite")
DEFAULT_REGISTRY = Path("data/geo/zones_registry.geojson")


def _date_for(zone_index: int, project_slot: int, cast_slot: int) -> str:
    start = date(2018 + (zone_index % 7), 1, 1)
    return (start + timedelta(days=project_slot * 31 + cast_slot * 9)).isoformat()


def seed_synthetic_cache(
    output: Path | str = DEFAULT_OUTPUT,
    *,
    registry_path: Path | str = DEFAULT_REGISTRY,
    force: bool = False,
) -> dict[str, int | str]:
    """Create a deterministic cache spanning every registered NeoLab zone."""
    output_path = Path(output)
    if output_path.exists() and not force:
        raise FileExistsError(
            f"Refusing to overwrite {output_path}; pass force=True to replace it."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    registry = load_registry(registry_path)
    conn = sqlite3.connect(output_path)
    init_schema(conn)
    conn.executescript(
        """
        CREATE TABLE objects_cache (
            object_id INTEGER PRIMARY KEY,
            sample_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            original_id TEXT NOT NULL,
            object_date TEXT,
            depth_min REAL,
            depth_max REAL,
            taxon TEXT NOT NULL,
            classification_status TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            free_fields_json TEXT
        );
        CREATE INDEX idx_objects_sample ON objects_cache(sample_id);
        CREATE INDEX idx_objects_project ON objects_cache(project_id);
        """
    )

    sample_count = 0
    object_count = 0
    now = "synthetic-2026-07-17"
    taxa = ("Calanus glacialis", "Calanus hyperboreus", "Pseudocalanus", "Copepoda")
    statuses = ("V", "P", "D", "U")

    for zone_index, zone in enumerate(registry.zones):
        point = zone.polygon.representative_point()
        latitude = float(point.y)
        longitude = float(point.x)
        for project_slot in range(3):
            project_id = 70000 + zone_index * 10 + project_slot
            instrument = ("UVP6", "UVP5SD", "Loki")[project_slot]
            project_sample_count = 0
            project_object_count = 0
            project_dates: list[str] = []
            for station_slot in range(2):
                station_id = f"S{station_slot + 1:02d}-{zone_index:02d}"
                for cast_slot in range(3):
                    sample_sequence = station_slot * 3 + cast_slot + 1
                    sample_id = project_id * 1_000_000 + sample_sequence
                    sample_date = _date_for(zone_index, project_slot, cast_slot)
                    cast_number = f"CAST-{zone_index:02d}-{station_slot + 1:02d}-{cast_slot + 1:02d}"
                    free_fields = {
                        "ecoregion": zone.canonical,
                        "source": "synthetic_fixture",
                        "cast_number": cast_number,
                        "station": station_id,
                        "taxa": list(taxa),
                        "status_counts": {status: 2 for status in statuses},
                    }
                    upsert_sample(
                        conn,
                        sample_id=sample_id,
                        project_id=project_id,
                        lat_avg=latitude,
                        lon_avg=longitude,
                        date_min=sample_date,
                        date_max=sample_date,
                        depth_min=5.0 + cast_slot * 10,
                        depth_max=100.0 + cast_slot * 250,
                        original_id=f"synthetic_{zone_index:02d}_{station_slot}_{cast_slot}",
                        station_id=station_id,
                        profile_id=cast_number,
                        free_fields_json=json.dumps(free_fields, ensure_ascii=False),
                        object_count=8,
                        instrument=instrument,
                        last_synced=now,
                    )
                    sample_count += 1
                    project_sample_count += 1
                    project_dates.append(sample_date)
                    for object_slot in range(8):
                        status = statuses[object_slot % len(statuses)]
                        object_id = sample_id * 100 + object_slot + 1
                        conn.execute(
                            """
                            INSERT INTO objects_cache (
                                object_id, sample_id, project_id, original_id,
                                object_date, depth_min, depth_max, taxon,
                                classification_status, latitude, longitude,
                                free_fields_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                object_id,
                                sample_id,
                                project_id,
                                f"{sample_id}_{object_slot + 1:03d}",
                                sample_date,
                                5.0 + cast_slot * 10,
                                100.0 + cast_slot * 250,
                                taxa[object_slot % len(taxa)],
                                status,
                                latitude,
                                longitude,
                                json.dumps({"ecoregion": zone.canonical}),
                            ),
                        )
                        object_count += 1
                        project_object_count += 1

            schema = {
                "title": f"Synthetic {zone.canonical} {instrument}",
                "instrument": instrument,
                "ecoregion": zone.canonical,
                "levels": ["sample", "cast", "object"],
                "columns": ["sample_id", "cast_number", "station", "taxon", "classification_status"],
            }
            conn.execute(
                "INSERT INTO project_schemas_cache VALUES (?, ?, ?)",
                (project_id, json.dumps(schema, ensure_ascii=False), now),
            )
            conn.execute(
                "INSERT INTO project_signatures_cache VALUES (?, ?, ?, ?, ?)",
                (project_id, project_object_count, 50.0, 100.0, now),
            )

    conn.execute(
        """INSERT INTO sync_runs
           (started_at, ended_at, status, projects_synced, samples_synced, error_message)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (now, now, "success", len(registry.zones) * 3, sample_count, None),
    )
    conn.commit()
    conn.close()
    return {
        "output": str(output_path),
        "zones": len(registry.zones),
        "projects": len(registry.zones) * 3,
        "samples": sample_count,
        "objects": object_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    summary = seed_synthetic_cache(args.output, registry_path=args.registry, force=args.force)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
