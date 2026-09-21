#!/usr/bin/env python3
"""Compare raw EcoPart bins with PostgreSQL and audit actual EcoTaxa joins."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from populate_ecopart import ROOT, connection, export_rows, log, save_json


def validate(directory: Path) -> dict:
    """Use independent SQL invariants and raw export volume/depth oracles."""
    report = {"projects": [], "checks": {}}
    with connection() as conn:
        imports = conn.execute("""SELECT i.*,v.file_manifest_uri,v.sha256
            FROM warehouse.ecopart_project_import i JOIN warehouse.dataset_version v
            ON v.id=i.dataset_version_id ORDER BY i.ecopart_project_id""").fetchall()
        conn.execute("""CREATE TEMP TABLE expected_bin
            (profile text,lower_m double precision,volume numeric) ON COMMIT PRESERVE ROWS""")
        for item in imports:
            path = Path(item["file_manifest_uri"])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
            rows = export_rows(path)
            conn.execute("TRUNCATE expected_bin")
            with conn.cursor().copy("COPY expected_bin FROM STDIN") as copy:
                for row in rows:
                    copy.write_row((row["profile"], row["depth_min"], row["volume"]))
            mismatch = conn.execute(
                """WITH actual AS (
                SELECT p.sample_name,b.depth_min_m,b.sampled_volume_l
                FROM warehouse.uvp_profile p JOIN warehouse.uvp_bin b ON b.profile_id=p.id
                WHERE p.dataset_version_id=%s)
                SELECT count(*) AS n FROM expected_bin e FULL JOIN actual a
                ON a.sample_name=e.profile AND a.depth_min_m=e.lower_m
                WHERE a.sample_name IS NULL OR e.profile IS NULL
                   OR abs(a.sampled_volume_l-e.volume)>0.000000001""",
                (item["dataset_version_id"],),
            ).fetchone()["n"]
            assert mismatch == 0, f"Raw bins mismatch: {item['ecopart_project_id']}"
            report["projects"].append(
                {**item["manifest_json"], "raw_bin_mismatches": mismatch}
            )
            log(
                f"QA source EcoPart {item['ecopart_project_id']}: {len(rows)} bins conformes"
            )
        checks = {
            "object_mapping_wrong_sample": """SELECT count(*) AS n FROM warehouse.uvp_object_bin m
                JOIN warehouse.ecotaxa_object o ON o.id=m.ecotaxa_object_id
                JOIN warehouse.uvp_bin b ON b.id=m.uvp_bin_id
                WHERE NOT EXISTS (SELECT 1 FROM warehouse.uvp_ecotaxa l
                    WHERE l.uvp_profile_id=b.profile_id AND l.ecotaxa_sample_id=o.sample_id)""",
            "object_mapping_wrong_depth": """SELECT count(*) AS n FROM warehouse.uvp_object_bin m
                JOIN warehouse.ecotaxa_object o ON o.id=m.ecotaxa_object_id
                JOIN warehouse.uvp_bin b ON b.id=m.uvp_bin_id
                WHERE floor(o.depth_min_m/5)*5 IS DISTINCT FROM b.depth_min_m""",
            "multiple_bins_per_object_version": """SELECT count(*) AS n FROM (
                SELECT m.ecotaxa_object_id,p.dataset_version_id FROM warehouse.uvp_object_bin m
                JOIN warehouse.uvp_bin b ON b.id=m.uvp_bin_id
                JOIN warehouse.uvp_profile p ON p.id=b.profile_id
                GROUP BY 1,2 HAVING count(*)>1) x""",
            "abundance_wrong_formula": """SELECT count(*) AS n FROM warehouse.uvp_taxon_abundance
                WHERE abundance_uvp_ind_m3 <> n_objects_taxon::numeric/sampled_volume_l*1000""",
            "abundance_count_difference": """SELECT abs(
                (SELECT count(*) FROM warehouse.uvp_object_bin)-
                (SELECT coalesce(sum(n_objects_taxon),0) FROM warehouse.uvp_taxon_abundance)) AS n""",
            "ctd_without_accepted_source_link": """SELECT count(*) AS n FROM warehouse.uvp_ctd c
                WHERE NOT EXISTS (SELECT 1 FROM warehouse.uvp_ecotaxa l
                JOIN warehouse.ecotaxa_ctd e ON e.ecotaxa_sample_id=l.ecotaxa_sample_id
                WHERE l.uvp_profile_id=c.uvp_profile_id AND e.ctd_profile_id=c.ctd_profile_id
                    AND e.match_status='accepted')""",
        }
        for name, statement in checks.items():
            value = conn.execute(statement).fetchone()["n"]
            report["checks"][name] = int(value)
            log(f"QA {name}: {value}")
            assert value == 0, name
        report["coverage"] = conn.execute("""SELECT s.project_id,
            count(DISTINCT s.id) AS samples,
            count(DISTINCT l.ecotaxa_sample_id) AS linked_samples,
            count(DISTINCT p.ecopart_project_id) AS ecopart_projects
            FROM warehouse.ecotaxa_sample s
            LEFT JOIN warehouse.uvp_ecotaxa l ON l.ecotaxa_sample_id=s.id
            LEFT JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id
            GROUP BY s.project_id ORDER BY s.project_id""").fetchall()
        report["zero_object_bins"] = (
            conn.execute("""SELECT count(*) AS n FROM warehouse.uvp_bin b
            WHERE NOT EXISTS(SELECT 1 FROM warehouse.uvp_object_bin m WHERE m.uvp_bin_id=b.id)""").fetchone()[
                "n"
            ]
        )
        # Exercise the zero-preserving abundance surface on a real profile.
        report["abundance_example"] = (
            conn.execute("""SELECT profile_id,taxon_key,annotation_policy,
                sum(n_objects_taxon)::bigint AS objects,sum(sampled_volume_l)::float AS volume_l,
                (sum(n_objects_taxon)/sum(sampled_volume_l)*1000)::float AS ind_m3,
                count(*) FILTER(WHERE n_objects_taxon=0) AS zero_bins
            FROM explore.uvp_taxon_abundance
            WHERE profile_id=(SELECT min(id) FROM warehouse.uvp_profile)
            GROUP BY profile_id,taxon_key,annotation_policy ORDER BY objects DESC LIMIT 5""").fetchall()
        )
    save_json(directory / "validation.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, default=ROOT / "data/warehouse_ecopart"
    )
    args = parser.parse_args()
    result = validate(args.directory)
    print(
        json.dumps(
            {"projects": len(result["projects"]), "checks": result["checks"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
