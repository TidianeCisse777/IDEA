"""UVP metrics pipeline — Python port of the dataset-prep stage from Vilgrain
& Bourgouin (2026) ``Code - UVP_metrics_from_raw_data.R`` (lines 32-118).

Reads the raw EcoTaxa + EcoPart exports and produces the three intermediate
tables on which the metrics M1-M6 are computed in the original R script:

- ``taxa_db``         : cleaned EcoTaxa rows + ``depth_bin`` (5 m) +
                       ``sampled_volume`` joined from EcoPart.
- ``part_db``         : cleaned EcoPart rows + station/lat/lon joined from
                       EcoTaxa, filtered to the first ``--depth-cap`` meters.
- ``taxa_morpho_db``  : EcoTaxa morphological descriptors slice
                       (``object_area`` → ``object_skeleton_area``) keyed by
                       sample_id / object_id.

Usage::

    python scripts/uvp_metrics_pipeline.py \\
        --ecotaxa-tsv UVP_metrics_for_MCA/data/ecotaxa_hawkechannel_30jan.tsv \\
        --ecopart-tsv UVP_metrics_for_MCA/data/ecopart_hawkechannel_30jan.tsv \\
        --output-dir  UVP_metrics_for_MCA/intermediate

The R reference uses ``round_any(depth, 5, floor) + 2.5`` for ``depth_bin``
and ``encoding=WINDOWS-1252`` for the EcoPart TSV — both reproduced here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


TAXA_RENAME: dict[str, str] = {
    "sample_cruise": "cruise",
    "sample_ship": "ship",
    "sample_stationid": "station",
    "sample_id": "sample_id",
    "object_lat": "lat",
    "object_lon": "lon",
    "object_date": "date",
    "object_time": "time",
    "object_id": "object_id",
    "object_depth_min": "depth",
    "object_annotation_status": "status",
    "object_annotation_category": "category",
    "object_annotation_hierarchy": "hierarchy",
    "sample_ctdrosettefilename": "ctd_filename",
}

TAXA_MORPHO_ID_RENAME: dict[str, str] = {
    "sample_stationid": "station",
    "sample_id": "sample_id",
    "object_lat": "lat",
    "object_lon": "lon",
    "object_id": "object_id",
    "object_annotation_category": "category",
    "object_depth_min": "depth",
}

PART_RENAME: dict[str, str] = {
    "Profile": "sample_id",
    "Project": "ecopart_project_name",
    "Depth [m]": "depth_bin",
    "Sampled volume [L]": "sampled_volume",
}

PART_LPM_FIRST = "LPM (1-2 µm) [# l-1]"
PART_LPM_LAST = "LPM biovolume (>16.4 mm) [mm3 l-1]"
MORPHO_FIRST = "object_area"
MORPHO_LAST = "object_skeleton_area"

TAXA_FINAL_COLUMN_ORDER = [
    "cruise", "ship", "station", "sample_id", "lat", "lon",
    "date", "time", "object_id",
    "depth", "depth_bin", "sampled_volume",
    "status", "category", "hierarchy", "ctd_filename",
]


def _slice_columns(df: pd.DataFrame, first: str, last: str) -> list[str]:
    cols = list(df.columns)
    try:
        start = cols.index(first)
        end = cols.index(last) + 1
    except ValueError as exc:
        raise SystemExit(f"Column slice {first!r}:{last!r} not found: {exc}") from exc
    return cols[start:end]


def _check_columns(df: pd.DataFrame, required: set[str], source: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing {source} columns: {sorted(missing)}")


def _depth_bin(depth: pd.Series, accuracy: int = 5) -> pd.Series:
    """Replicate R ``round_any(x, 5, floor) + 2.5`` from the original script."""
    return np.floor(depth.astype(float) / accuracy) * accuracy + (accuracy / 2)


def build_intermediate_tables(
    ecotaxa_tsv: Path,
    ecopart_tsv: Path,
    depth_cap_meters: int = 200,
) -> dict[str, pd.DataFrame]:
    print(f"Reading EcoTaxa TSV : {ecotaxa_tsv}")
    taxa_raw = pd.read_csv(ecotaxa_tsv, sep="\t", low_memory=False)
    print(f"  {len(taxa_raw):,} rows, {len(taxa_raw.columns)} columns")

    print(f"Reading EcoPart TSV : {ecopart_tsv}")
    part_raw = pd.read_csv(
        ecopart_tsv, sep="\t", encoding="windows-1252", low_memory=False
    )
    print(f"  {len(part_raw):,} rows, {len(part_raw.columns)} columns")

    image_pixelsize = taxa_raw["acq_pixel"].dropna().unique()
    image_volume = taxa_raw["acq_volimage"].dropna().unique()
    print(f"  acq_pixel = {image_pixelsize}, acq_volimage = {image_volume}")

    _check_columns(taxa_raw, set(TAXA_RENAME), "EcoTaxa")
    taxa_db = taxa_raw[list(TAXA_RENAME)].rename(columns=TAXA_RENAME)

    _check_columns(taxa_raw, set(TAXA_MORPHO_ID_RENAME), "EcoTaxa (morpho id)")
    morpho_cols = _slice_columns(taxa_raw, MORPHO_FIRST, MORPHO_LAST)
    taxa_morpho_db = pd.concat(
        [
            taxa_raw[list(TAXA_MORPHO_ID_RENAME)].rename(
                columns=TAXA_MORPHO_ID_RENAME
            ),
            taxa_raw[morpho_cols],
        ],
        axis=1,
    )
    print(
        f"  taxa_db : {len(taxa_db):,} rows | "
        f"taxa_morpho_db : {len(taxa_morpho_db):,} rows "
        f"({len(morpho_cols)} morpho cols)"
    )

    _check_columns(part_raw, set(PART_RENAME), "EcoPart")
    part = part_raw.rename(columns=PART_RENAME)
    lpm_cols = _slice_columns(part, PART_LPM_FIRST, PART_LPM_LAST)
    part_db = part[
        ["sample_id", "ecopart_project_name", "depth_bin", "sampled_volume"]
        + lpm_cols
    ].copy()

    sample_loc = (
        taxa_db[["sample_id", "station", "lat", "lon"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    part_db = part_db.merge(sample_loc, on="sample_id", how="left")
    front = ["sample_id", "ecopart_project_name", "station", "lat", "lon", "depth_bin"]
    rest = [c for c in part_db.columns if c not in front]
    part_db = part_db[front + rest]
    print(
        f"  part_db (pre-cap) : {len(part_db):,} rows | "
        f"{part_db['sample_id'].nunique()} sample_ids "
        f"| {len(lpm_cols)} LPM cols"
    )

    n_casts_taxa = taxa_db["sample_id"].nunique()
    n_casts_part = part_db["sample_id"].nunique()
    if n_casts_taxa != n_casts_part:
        print(
            f"  ⚠ sample_id count mismatch: taxa={n_casts_taxa} part={n_casts_part}"
        )
    else:
        print(f"  ✓ {n_casts_taxa} casts on both sides")

    taxa_db["depth_bin"] = _depth_bin(taxa_db["depth"])
    sv = (
        part_db[["sample_id", "depth_bin", "sampled_volume"]]
        .drop_duplicates(subset=["sample_id", "depth_bin"])
    )
    taxa_db = taxa_db.merge(sv, on=["sample_id", "depth_bin"], how="left")
    taxa_db = taxa_db.reindex(columns=TAXA_FINAL_COLUMN_ORDER)

    n_before = len(part_db)
    part_db = part_db[part_db["depth_bin"] < depth_cap_meters].copy()
    print(
        f"  part_db capped < {depth_cap_meters}m : "
        f"{len(part_db):,} rows (was {n_before:,})"
    )

    return {
        "taxa_db": taxa_db,
        "part_db": part_db,
        "taxa_morpho_db": taxa_morpho_db,
        "image_pixelsize": image_pixelsize,
        "image_volume": image_volume,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ecotaxa-tsv", required=True, type=Path)
    parser.add_argument("--ecopart-tsv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--depth-cap", type=int, default=200,
        help="Cap depth_bin for part_db (default 200m, matching the R script).",
    )
    parser.add_argument(
        "--format", choices=["parquet", "csv"], default="parquet",
        help="Output format (parquet default; csv if you need to inspect by eye).",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    tables = build_intermediate_tables(
        args.ecotaxa_tsv, args.ecopart_tsv, args.depth_cap
    )

    suffix = ".parquet" if args.format == "parquet" else ".csv"
    writer = (
        (lambda df, path: df.to_parquet(path, index=False))
        if args.format == "parquet"
        else (lambda df, path: df.to_csv(path, index=False))
    )

    print(f"\nWriting intermediate tables to {args.output_dir}/")
    for name in ("taxa_db", "part_db", "taxa_morpho_db"):
        path = args.output_dir / f"{name}{suffix}"
        writer(tables[name], path)
        print(f"  {path}  ({len(tables[name]):,} rows)")


if __name__ == "__main__":
    main()
