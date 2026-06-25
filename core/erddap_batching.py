"""Shared helpers to batch source rows into bounded ERDDAP queries.

Used by `tools/amundsen_sources.py` and `tools/ogsl_sources.py` to keep large
NeoLabs/EcoTaxa enrichments robust: deduplicate repeated coordinates, group
queries by month + coarse spatial grid, and split rejected batches more finely.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

import pandas as pd


def chunk_positions_by_time(
    positions: list[int],
    *,
    src_time: pd.Series,
    max_positions: int,
) -> list[list[int]]:
    if max_positions <= 0 or len(positions) <= max_positions:
        return [positions]
    sorted_positions = sorted(
        positions,
        key=lambda position: (
            2**63 - 1
            if pd.isna(src_time.iloc[position])
            else pd.Timestamp(src_time.iloc[position]).value
        ),
    )
    return [
        sorted_positions[start : start + max_positions]
        for start in range(0, len(sorted_positions), max_positions)
    ]


def source_batch_positions(
    *,
    src_lat: pd.Series,
    src_lon: pd.Series,
    src_time: pd.Series,
    spatial_bin_degrees: float | None = None,
    max_positions: int = 50,
    candidate_positions: list[int] | None = None,
) -> list[list[int]]:
    """Group source rows into bounded ERDDAP query batches.

    Month-first batching keeps the normal path small for interactive use. Very
    broad months are split by a coarse grid to avoid huge ERDDAP responses.
    A finer fallback split is reserved for failed batches inside the tool.
    """
    valid = src_lat.notna() & src_lon.notna() & src_time.notna()
    if candidate_positions is not None:
        candidate_mask = pd.Series([False] * len(src_lat))
        candidate_mask.iloc[candidate_positions] = True
        valid = valid & candidate_mask
    if not bool(valid.any()):
        return []

    frame = pd.DataFrame(
        {
            "position": range(len(src_lat)),
            "latitude": src_lat.to_numpy(),
            "longitude": src_lon.to_numpy(),
            "time": src_time.to_numpy(),
        }
    )
    frame = frame.loc[valid.to_numpy()].copy()
    frame["time_batch"] = pd.to_datetime(frame["time"], utc=True).dt.strftime("%Y-%m")

    batches: list[list[int]] = []
    for _, month_group in frame.groupby("time_batch", sort=True):
        if spatial_bin_degrees is None or spatial_bin_degrees <= 0:
            batches.extend(
                chunk_positions_by_time(
                    month_group["position"].astype(int).tolist(),
                    src_time=src_time,
                    max_positions=max_positions,
                )
            )
            continue

        lat_span = float(month_group["latitude"].max() - month_group["latitude"].min())
        lon_span = float(month_group["longitude"].max() - month_group["longitude"].min())
        if lat_span <= spatial_bin_degrees and lon_span <= spatial_bin_degrees:
            batches.extend(
                chunk_positions_by_time(
                    month_group["position"].astype(int).tolist(),
                    src_time=src_time,
                    max_positions=max_positions,
                )
            )
            continue

        month_group = month_group.copy()
        month_group["lat_batch"] = month_group["latitude"].map(
            lambda value: math.floor(float(value) / spatial_bin_degrees)
        )
        month_group["lon_batch"] = month_group["longitude"].map(
            lambda value: math.floor(float(value) / spatial_bin_degrees)
        )
        for _, group in month_group.groupby(["lat_batch", "lon_batch"], sort=True):
            batches.extend(
                chunk_positions_by_time(
                    group["position"].astype(int).tolist(),
                    src_time=src_time,
                    max_positions=max_positions,
                )
            )

    return batches


def spatial_subbatch_positions(
    *,
    positions: list[int],
    src_lat: pd.Series,
    src_lon: pd.Series,
    spatial_bin_degrees: float,
    src_time: pd.Series | None = None,
    max_positions: int = 50,
) -> list[list[int]]:
    if spatial_bin_degrees <= 0 or len(positions) <= 1:
        if src_time is None:
            return [positions]
        return chunk_positions_by_time(
            positions,
            src_time=src_time,
            max_positions=max_positions,
        )

    frame = pd.DataFrame(
        {
            "position": positions,
            "latitude": src_lat.iloc[positions].to_numpy(),
            "longitude": src_lon.iloc[positions].to_numpy(),
        }
    )
    frame["lat_batch"] = frame["latitude"].map(
        lambda value: math.floor(float(value) / spatial_bin_degrees)
    )
    frame["lon_batch"] = frame["longitude"].map(
        lambda value: math.floor(float(value) / spatial_bin_degrees)
    )
    batches: list[list[int]] = []
    for _, group in frame.groupby(["lat_batch", "lon_batch"], sort=True):
        group_positions = group["position"].astype(int).tolist()
        if src_time is None:
            batches.append(group_positions)
        else:
            batches.extend(
                chunk_positions_by_time(
                    group_positions,
                    src_time=src_time,
                    max_positions=max_positions,
                )
            )
    return batches


def unique_coordinate_positions(
    *,
    src_lat: pd.Series,
    src_lon: pd.Series,
    src_time: pd.Series,
    src_depth: pd.Series | None,
) -> tuple[list[int], list[int]]:
    """Return first source position per unique coordinate key and row mapping."""
    key_frame = pd.DataFrame(
        {
            "latitude": src_lat.round(6),
            "longitude": src_lon.round(6),
            "time": src_time.astype("string"),
            "depth": (
                src_depth.round(3)
                if src_depth is not None
                else pd.Series([pd.NA] * len(src_lat))
            ),
        }
    ).fillna("<NA>")
    keys = pd.Index(list(key_frame.itertuples(index=False, name=None)))
    codes, _ = pd.factorize(keys, sort=False)
    first_positions: dict[int, int] = {}
    for position, code in enumerate(codes):
        first_positions.setdefault(int(code), position)
    unique_positions = [
        first_positions[code]
        for code in sorted(first_positions, key=lambda value: first_positions[value])
    ]
    row_to_unique = [int(code) for code in codes]
    return unique_positions, row_to_unique


def run_batches_in_parallel(
    batches: list[list[int]],
    worker,
    *,
    max_workers: int = 6,
) -> list[tuple[bool, str | None]]:
    """Run a per-batch worker concurrently and return results in batch order.

    `worker(positions)` must be self-contained (no shared mutable state aside
    from pre-allocated slots indexed by `positions`). Returns the list of
    `(ok, error)` tuples in the same order as `batches`.
    """
    if not batches:
        return []
    effective_workers = max(1, min(int(max_workers), len(batches)))
    if effective_workers == 1:
        return [worker(positions) for positions in batches]
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        return list(pool.map(worker, batches))
