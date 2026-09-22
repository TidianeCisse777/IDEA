#!/usr/bin/env python3
"""Create FILET–UVP station/time candidates without using source IDs."""

from __future__ import annotations

import argparse
import json

from psycopg.rows import dict_row

from populate_filet import connection


SQL = """
WITH filet AS (
 SELECT s.id,s.sample_id,s.station_name,s.deployment_datetime_start AS sampled_at,
   CASE WHEN upper(regexp_replace(s.station_name,'[^A-Za-z0-9]','','g')) ~ '^G[0-9]'
        THEN substr(upper(regexp_replace(s.station_name,'[^A-Za-z0-9]','','g')),2)
        ELSE upper(regexp_replace(s.station_name,'[^A-Za-z0-9]','','g')) END AS station_norm
 FROM warehouse.filet_sample s
 WHERE s.station_name IS NOT NULL AND s.deployment_datetime_start IS NOT NULL
), uvp AS (
 SELECT p.id,p.sample_name,p.station_key,p.sampled_at,
   CASE WHEN upper(regexp_replace(p.station_key,'[^A-Za-z0-9]','','g')) ~ '^G[0-9]'
        THEN substr(upper(regexp_replace(p.station_key,'[^A-Za-z0-9]','','g')),2)
        ELSE upper(regexp_replace(p.station_key,'[^A-Za-z0-9]','','g')) END AS station_norm
 FROM warehouse.uvp_profile p
 WHERE p.station_key IS NOT NULL AND p.sampled_at IS NOT NULL
), candidates AS (
 SELECT f.id AS filet_sample_id,f.sample_id,f.station_name,f.station_norm,
        f.sampled_at AS filet_sampled_at,u.id AS uvp_profile_id,u.sample_name,
        u.station_key,u.sampled_at AS uvp_sampled_at,
        abs(extract(epoch FROM (f.sampled_at-u.sampled_at))/3600.0) AS time_gap_hours,
        count(*) OVER (PARTITION BY f.id) AS candidate_count
 FROM filet f JOIN uvp u USING (station_norm)
 WHERE abs(extract(epoch FROM (f.sampled_at-u.sampled_at))/3600.0) <= %s
)
SELECT c.*,a.id AS filet_analysis_id
FROM candidates c LEFT JOIN warehouse.filet_analysis a ON a.sample_ref=c.filet_sample_id
ORDER BY c.filet_sample_id,c.uvp_profile_id,a.id
"""


def load(max_gap_hours: float, database_url: str | None = None) -> dict:
    if max_gap_hours <= 0:
        raise ValueError("La fenêtre temporelle doit être positive")
    version_key = f"station-normalisee-{max_gap_hours:g}h"
    with connection(database_url) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""INSERT INTO warehouse.dataset_version
          (source_instance,dataset_key,version_key,file_manifest_uri,sha256)
          VALUES ('derived','filet_uvp_station_time',%s,'warehouse:station-time-match',%s)
          ON CONFLICT (source_instance,dataset_key,version_key) DO UPDATE SET sha256=EXCLUDED.sha256
          RETURNING id""", (version_key, f"station-time-{max_gap_hours:g}h"))
        version_id = cur.fetchone()["id"]
        cur.execute("DELETE FROM warehouse.filet_uvp_match WHERE dataset_version_id=%s", (version_id,))
        candidates = cur.execute(SQL, (max_gap_hours,)).fetchall()
        rows = []
        for candidate in candidates:
            evidence = json.dumps({
                "rule": "station_normalized_exact_and_time_window",
                "max_gap_hours": max_gap_hours,
                "filet_station": candidate["station_name"],
                "uvp_station": candidate["station_key"],
                "station_normalized": candidate["station_norm"],
                "filet_sample": candidate["sample_id"],
                "uvp_profile": candidate["sample_name"],
                "candidate_count_for_filet_sample": candidate["candidate_count"],
            }, ensure_ascii=False)
            rows.append((version_id, candidate["station_norm"], candidate["filet_sample_id"],
                candidate["filet_analysis_id"], candidate["uvp_profile_id"], candidate["filet_sampled_at"],
                candidate["uvp_sampled_at"], candidate["time_gap_hours"],
                "accepted" if candidate["candidate_count"] == 1 else "ambiguous",
                "station_normalized_exact_and_time_window", evidence))
        cur.executemany("""INSERT INTO warehouse.filet_uvp_match
          (dataset_version_id,station_id,filet_sample_id,filet_analysis_id,uvp_profile_id,filet_sampled_at,uvp_sampled_at,time_gap_hours,match_status,match_method,evidence)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        return {"dataset_version_id": version_id, "max_gap_hours": max_gap_hours,
                "candidate_rows": len(rows),
                "accepted": sum(row[8] == "accepted" for row in rows),
                "ambiguous": sum(row[8] == "ambiguous" for row in rows)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-gap-hours", type=float, default=10.0)
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print(load(args.max_gap_hours, args.database_url))


if __name__ == "__main__":
    main()
