"""Pure contracts shared by the EcoTaxa–EcoPart join and its audit."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


OFFICIAL_DEPTH_COLUMN = "object_depth_min"
SAMPLED_VOLUME_COLUMN = "ecopart_Sampled volume [L]"


def depth_bin_5m(depth: pd.Series) -> pd.Series:
    """Map depths to the documented EcoPart grid of 5 m bin centres."""
    numeric = pd.to_numeric(depth, errors="coerce")
    return (numeric // 5.0) * 5.0 + 2.5


def audit_ecotaxa_ecopart_dataframe(
    dataframe: pd.DataFrame,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit one persisted object-level EcoTaxa–EcoPart join without rebuilding it."""
    meta = meta or {}
    required = {
        "sample_id",
        "object_id",
        OFFICIAL_DEPTH_COLUMN,
        "depth_bin",
        SAMPLED_VOLUME_COLUMN,
    }
    missing = sorted(required.difference(dataframe.columns))
    anomalies: list[str] = []
    if missing:
        anomalies.extend(f"missing:{column}" for column in missing)

    depth_column = meta.get("depth_col_used")
    if depth_column != OFFICIAL_DEPTH_COLUMN:
        anomalies.append(OFFICIAL_DEPTH_COLUMN)

    if "object_id" in dataframe.columns:
        object_ids = dataframe["object_id"].dropna()
        duplicate_object_ids = int(object_ids.duplicated().sum())
        sampled_zero_object_bins = int(dataframe["object_id"].isna().sum())
    else:
        duplicate_object_ids = 0
        sampled_zero_object_bins = 0
    if duplicate_object_ids:
        anomalies.append("duplicate_object_id")
    declared_zero_bins = int(meta.get("n_zero_object_bins", 0))
    if sampled_zero_object_bins != declared_zero_bins:
        anomalies.append("zero_object_bin_count_mismatch")

    n_sample_depth_bins = (
        int(dataframe[["sample_id", "depth_bin"]].drop_duplicates().shape[0])
        if {"sample_id", "depth_bin"}.issubset(dataframe.columns)
        else 0
    )

    if SAMPLED_VOLUME_COLUMN in dataframe.columns:
        volume = pd.to_numeric(dataframe[SAMPLED_VOLUME_COLUMN], errors="coerce")
        missing_volume_rows = int(volume.isna().sum())
        non_positive_volume_rows = int((volume.notna() & (volume <= 0)).sum())
        volume_frame = dataframe[["sample_id", "depth_bin"]].copy()
        volume_frame["_volume"] = volume
        conflicting_volume_bins = 0
        for _, group in volume_frame.groupby(
            ["sample_id", "depth_bin"], dropna=False
        ):
            values = group["_volume"].dropna().to_numpy(dtype=float)
            if len(values) and not np.all(
                np.isclose(values, values.mean(), rtol=1e-6, atol=1e-9)
            ):
                conflicting_volume_bins += 1
    else:
        missing_volume_rows = len(dataframe)
        non_positive_volume_rows = 0
        conflicting_volume_bins = 0
    if missing_volume_rows:
        anomalies.append("missing_volume")
    if non_positive_volume_rows:
        anomalies.append("non_positive_volume")
    if conflicting_volume_bins:
        anomalies.append("conflicting_volume")

    if {OFFICIAL_DEPTH_COLUMN, "depth_bin"}.issubset(dataframe.columns):
        object_rows = (
            dataframe["object_id"].notna()
            if "object_id" in dataframe.columns
            else pd.Series(True, index=dataframe.index)
        )
        depth = pd.to_numeric(
            dataframe.loc[object_rows, OFFICIAL_DEPTH_COLUMN], errors="coerce"
        )
        centre = pd.to_numeric(
            dataframe.loc[object_rows, "depth_bin"], errors="coerce"
        )
        distance = (depth - centre).abs()
        objects_outside_5m_bin = int(
            (distance.isna() | ~np.isfinite(distance) | (distance > 2.5)).sum()
        )
        max_depth_distance_m = (
            float(distance.max()) if distance.notna().any() else None
        )
    else:
        objects_outside_5m_bin = len(dataframe)
        max_depth_distance_m = None
    if objects_outside_5m_bin:
        anomalies.append("object_outside_5m_bin")

    return {
        "verdict": "validated" if not anomalies else "refused",
        "anomalies": anomalies,
        "depth_column": depth_column,
        "n_rows": int(len(dataframe)),
        "n_matched": int(meta.get("n_matched", 0)),
        "n_sample_depth_bins": n_sample_depth_bins,
        "duplicate_object_ids": duplicate_object_ids,
        "sampled_zero_object_bins": sampled_zero_object_bins,
        "missing_volume_rows": missing_volume_rows,
        "non_positive_volume_rows": non_positive_volume_rows,
        "conflicting_volume_bins": conflicting_volume_bins,
        "objects_outside_5m_bin": objects_outside_5m_bin,
        "max_depth_distance_m": max_depth_distance_m,
    }
