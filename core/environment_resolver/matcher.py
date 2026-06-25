"""Nearest-neighbour CTD profile matcher shared by Amundsen and OGSL tools."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.environment_resolver.geo import haversine_km


@dataclass
class CtdMatch:
    """One row's match result against a fetched CTD table.

    `status` is one of "matched", "matched_no_value", "no_match".
    For "no_match", `chosen_idx`, `distance_km` and `time_delta_min` are None.
    `time_delta_min` is None when the source time itself is NaT.
    """

    status: str
    chosen_idx: int | None = None
    distance_km: float | None = None
    time_delta_min: float | None = None


def match_ctd_rows(
    *,
    src_lat: pd.Series,
    src_lon: pd.Series,
    src_time: pd.Series,
    src_depth: pd.Series | None,
    ctd: pd.DataFrame,
    ctd_pres_col: str = "PRES",
    variables_for_value_check: list[str],
    spatial_tolerance_km: float,
    time_tolerance_hours: float,
    src_time_end: pd.Series | None = None,
) -> list[CtdMatch]:
    """Match each source row to the nearest CTD row within tolerance windows.

    The match strategy mirrors the original Amundsen/OGSL behaviour:
    1. Drop CTD rows outside the time window. When `src_time_end` is provided
       AND its value is not NaT for the row, the window is the exact deployment
       interval `[src_time, src_time_end]` widened by ±15 min for clock skew.
       Otherwise the window is `src_time ± time_tolerance_hours`.
    2. Compute Haversine distance to each remaining CTD row.
    3. If the nearest distance exceeds `spatial_tolerance_km`, mark "no_match".
    4. Among rows tied at the nearest distance (same profile), pick the row
       whose CTD pressure is closest to `src_depth` (when available).
    5. If all requested variables are NaN on the chosen row, downgrade the
       status to "matched_no_value".
    """
    matches: list[CtdMatch] = []
    if ctd.empty:
        return [CtdMatch(status="no_match")] * len(src_lat)

    ctd_lat = pd.to_numeric(ctd["latitude"], errors="coerce")
    ctd_lon = pd.to_numeric(ctd["longitude"], errors="coerce")
    ctd_time = (
        pd.to_datetime(ctd["time"], errors="coerce", utc=True)
        if "time" in ctd.columns
        else pd.Series([pd.NaT] * len(ctd))
    )
    ctd_pres = (
        pd.to_numeric(ctd[ctd_pres_col], errors="coerce")
        if ctd_pres_col in ctd.columns
        else pd.Series([float("nan")] * len(ctd))
    )
    time_tolerance = pd.Timedelta(hours=float(time_tolerance_hours))
    window_slack = pd.Timedelta(minutes=15)

    n_rows = len(src_lat)
    for position in range(n_rows):
        src_t = src_time.iloc[position]
        src_t_end = (
            src_time_end.iloc[position]
            if src_time_end is not None
            else pd.NaT
        )
        time_deltas = (ctd_time - src_t).abs()
        if pd.notna(src_t) and pd.notna(src_t_end):
            within_time = (ctd_time >= src_t - window_slack) & (
                ctd_time <= src_t_end + window_slack
            )
        elif not pd.isna(src_t):
            within_time = time_deltas <= time_tolerance
        else:
            within_time = pd.Series([True] * len(ctd))
        if not within_time.any():
            matches.append(CtdMatch(status="no_match"))
            continue

        distances = pd.Series(
            [
                haversine_km(
                    src_lat.iloc[position],
                    src_lon.iloc[position],
                    ctd_lat.iloc[j],
                    ctd_lon.iloc[j],
                )
                if within_time.iloc[j]
                else float("inf")
                for j in range(len(ctd))
            ]
        )
        nearest_distance = float(distances.min())
        if nearest_distance > float(spatial_tolerance_km):
            matches.append(CtdMatch(status="no_match"))
            continue

        profile_mask = distances.eq(nearest_distance)
        profile_indices = list(distances[profile_mask].index)
        if src_depth is not None and not pd.isna(src_depth.iloc[position]):
            target_depth = float(src_depth.iloc[position])
            depth_deltas = (ctd_pres.iloc[profile_indices] - target_depth).abs()
            chosen_idx = int(depth_deltas.idxmin())
        else:
            chosen_idx = profile_indices[0]

        best = ctd.iloc[chosen_idx]
        best_dt = time_deltas.iloc[chosen_idx]
        requested_values = [
            best.get(variable)
            for variable in variables_for_value_check
            if variable in best.index
        ]
        all_nan = bool(requested_values) and all(
            pd.isna(value) for value in requested_values
        )

        matches.append(
            CtdMatch(
                status="matched_no_value" if all_nan else "matched",
                chosen_idx=chosen_idx,
                distance_km=round(float(distances.iloc[chosen_idx]), 3),
                time_delta_min=(
                    round(best_dt.total_seconds() / 60.0, 1)
                    if pd.notna(best_dt)
                    else None
                ),
            )
        )

    return matches
