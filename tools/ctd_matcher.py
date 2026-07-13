"""Shared base for CTD nearest-profile PointMatchers (Amundsen, OGSL).

Both sources match a loaded table to the nearest CTD profile via the same
machinery: ERDDAP bbox batching, a finer spatial fallback for failed batches,
`match_ctd_rows` nearest selection, and per-unique-point status/value/diagnostic
accumulation. That machinery lives here once; each source subclass supplies
only what varies:

- `_fetch(**kwargs)`      — the source's ERDDAP bbox fetch function.
- `_init_queryable(...)`  — initial per-point statuses + which positions may be
                            queried (Amundsen gates on its fixed time range;
                            OGSL queries every point with a valid coord).
- `_extra_columns(...)`   — source-specific value columns (station ids, oxygen…)
                            on top of the shared dataset_id/time/distance/
                            time_delta/pres/te90/psal block.
- `_extra_diagnostics(...)` — optional extra diagnostics for the method block.
"""
from __future__ import annotations

import threading

import pandas as pd

from core.environment_resolver import compute_bbox_time_window, match_ctd_rows
from core.erddap_batching import (
    run_batches_in_parallel,
    source_batch_positions,
    spatial_subbatch_positions,
)
from tools.point_enrichment import MatchResult, QueryPoints, RequiredCoords


class CtdProfileMatcher:
    """Base PointMatcher for CTD nearest-profile enrichment."""

    prefix: str = "ctd"
    label: str = "CTD"
    dataset_id: str = ""

    def __init__(
        self,
        *,
        selected_variables: list[str],
        spatial_tolerance_km: float,
        time_tolerance_hours: float,
        initial_batch_spatial_degrees: float,
        batch_spatial_degrees: float,
        max_source_points_per_batch: int,
        max_ctd_rows_per_batch: int,
        depth_padding_dbar: float,
        max_workers: int,
    ):
        self.selected_variables = selected_variables
        self.spatial_tolerance_km = spatial_tolerance_km
        self.time_tolerance_hours = time_tolerance_hours
        self.initial_batch_spatial_degrees = initial_batch_spatial_degrees
        self.batch_spatial_degrees = batch_spatial_degrees
        self.max_source_points_per_batch = max_source_points_per_batch
        self.max_ctd_rows_per_batch = max_ctd_rows_per_batch
        self.depth_padding_dbar = depth_padding_dbar
        self.max_workers = max_workers

    # ── shared interface ────────────────────────────────────────────────
    def required_coords(self) -> RequiredCoords:
        return RequiredCoords(lat=True, lon=True, time=True, depth=True)

    def dedup_keys(self, coords) -> pd.Series:
        lat = coords.latitude.reset_index(drop=True)
        lon = coords.longitude.reset_index(drop=True)
        time = (
            coords.time.reset_index(drop=True)
            if coords.time is not None else pd.Series([pd.NA] * len(lat))
        )
        depth = (
            coords.depth.reset_index(drop=True)
            if coords.depth is not None else pd.Series([pd.NA] * len(lat))
        )
        keys = []
        for i in range(len(lat)):
            if pd.isna(lat.iloc[i]) or pd.isna(lon.iloc[i]):
                keys.append(pd.NA)
                continue
            t = time.iloc[i]
            d = depth.iloc[i]
            keys.append((
                round(float(lat.iloc[i]), 6),
                round(float(lon.iloc[i]), 6),
                "<NA>" if pd.isna(t) else str(t),
                "<NA>" if pd.isna(d) else round(float(d), 3),
            ))
        return pd.Series(keys)

    def match(self, points: QueryPoints) -> MatchResult:
        n_unique = len(points)
        unique_lat = points.latitude
        unique_lon = points.longitude
        unique_time = points.time
        unique_time_end = points.time_end
        unique_depth = points.depth

        statuses, candidate_positions = self._init_queryable(points)
        matched: list = [None] * n_unique

        batch_positions = source_batch_positions(
            src_lat=unique_lat,
            src_lon=unique_lon,
            src_time=unique_time,
            spatial_bin_degrees=float(self.initial_batch_spatial_degrees),
            max_positions=int(self.max_source_points_per_batch),
            candidate_positions=candidate_positions,
        )
        counters = {"erddap_calls": 0}
        fallback_months = 0
        fallback_subbatches = 0
        fetch_failures: list[str] = []
        counters_lock = threading.Lock()

        def _fetch_and_match_positions(positions: list[int]) -> tuple[bool, str | None]:
            batch_lat = unique_lat.iloc[positions].reset_index(drop=True)
            batch_lon = unique_lon.iloc[positions].reset_index(drop=True)
            batch_time = unique_time.iloc[positions].reset_index(drop=True)
            batch_time_end = (
                unique_time_end.iloc[positions].reset_index(drop=True)
                if unique_time_end is not None
                else None
            )
            batch_depth = (
                unique_depth.iloc[positions].reset_index(drop=True)
                if unique_depth is not None
                else None
            )
            pres_range = None
            if batch_depth is not None and batch_depth.notna().any():
                valid_depth = batch_depth.dropna()
                pres_range = {
                    "min": max(0.0, float(valid_depth.min()) - float(self.depth_padding_dbar)),
                    "max": float(valid_depth.max()) + float(self.depth_padding_dbar),
                }
            bbox, time_window = compute_bbox_time_window(
                src_lat=batch_lat,
                src_lon=batch_lon,
                src_time=batch_time,
                time_padding_hours=self.time_tolerance_hours,
            )
            try:
                with counters_lock:
                    counters["erddap_calls"] += 1
                fetch_kwargs = {
                    "bbox": bbox,
                    "time_window": time_window,
                    "variables": self.selected_variables,
                }
                if pres_range is not None:
                    fetch_kwargs["pres_range"] = pres_range
                try:
                    ctd = self._fetch(**fetch_kwargs)
                except TypeError:
                    fetch_kwargs.pop("pres_range", None)
                    ctd = self._fetch(**fetch_kwargs)
            except Exception as exc:
                return False, str(exc)
            if len(ctd) > int(self.max_ctd_rows_per_batch):
                return False, (
                    f"too_many_ctd_rows:{len(ctd)}>"
                    f"{int(self.max_ctd_rows_per_batch)}"
                )

            matches = match_ctd_rows(
                src_lat=batch_lat,
                src_lon=batch_lon,
                src_time=batch_time,
                src_time_end=batch_time_end,
                src_depth=batch_depth,
                ctd=ctd,
                ctd_pres_col="PRES",
                variables_for_value_check=self.selected_variables,
                spatial_tolerance_km=self.spatial_tolerance_km,
                time_tolerance_hours=self.time_tolerance_hours,
            )
            for local_position, match in enumerate(matches):
                unique_position = positions[local_position]
                statuses[unique_position] = match.status
                if match.chosen_idx is None:
                    continue
                matched[unique_position] = (ctd.iloc[match.chosen_idx], match)
            return True, None

        initial_results = run_batches_in_parallel(
            batch_positions,
            _fetch_and_match_positions,
            max_workers=int(self.max_workers),
        )

        fallback_subbatch_jobs: list[list[int]] = []
        for positions, (ok, error) in zip(batch_positions, initial_results):
            if ok:
                continue
            subbatches = spatial_subbatch_positions(
                positions=positions,
                src_lat=unique_lat,
                src_lon=unique_lon,
                spatial_bin_degrees=float(self.batch_spatial_degrees),
                src_time=unique_time,
                max_positions=int(self.max_source_points_per_batch),
            )
            if len(subbatches) <= 1:
                if error:
                    fetch_failures.append(error)
                continue
            fallback_months += 1
            fallback_subbatches += len(subbatches)
            fallback_subbatch_jobs.extend(subbatches)

        fallback_results = run_batches_in_parallel(
            fallback_subbatch_jobs,
            _fetch_and_match_positions,
            max_workers=int(self.max_workers),
        )
        for sub_ok, sub_error in fallback_results:
            if not sub_ok and sub_error:
                fetch_failures.append(sub_error)

        columns = pd.DataFrame({
            **self._common_columns(matched, n_unique),
            **self._extra_columns(matched, n_unique),
        })
        diagnostics = {
            "erddap_calls": counters["erddap_calls"],
            "batch_count": len(batch_positions),
            "fallback_months": fallback_months,
            "fallback_subbatches": fallback_subbatches,
            "fetch_failures": fetch_failures,
        }
        diagnostics.update(self._extra_diagnostics(points, candidate_positions))
        return MatchResult(
            columns=columns,
            statuses=pd.Series(statuses),
            n_matched=statuses.count("matched"),
            diagnostics=diagnostics,
        )

    # ── shared column block ─────────────────────────────────────────────
    def _common_columns(self, matched: list, n_unique: int) -> dict:
        prefix = self.prefix
        dataset_id = [self.dataset_id] * n_unique
        time: list = [pd.NA] * n_unique
        distance: list = [pd.NA] * n_unique
        time_delta: list = [pd.NA] * n_unique
        pres: list = [pd.NA] * n_unique
        te90: list = [pd.NA] * n_unique
        psal: list = [pd.NA] * n_unique
        for position, item in enumerate(matched):
            if item is None:
                continue
            best, match = item
            time[position] = best.get("time")
            distance[position] = match.distance_km
            time_delta[position] = (
                match.time_delta_min if match.time_delta_min is not None else pd.NA
            )
            pres[position] = best.get("PRES")
            te90[position] = best.get("TE90")
            psal[position] = best.get("PSAL")
        return {
            f"{prefix}_dataset_id": dataset_id,
            f"{prefix}_time": time,
            f"{prefix}_distance_km": distance,
            f"{prefix}_time_delta_min": time_delta,
            f"{prefix}_pres_dbar": pres,
            f"{prefix}_te90_degC": te90,
            f"{prefix}_psal_psu": psal,
        }

    # ── hooks subclasses implement ──────────────────────────────────────
    def _fetch(self, **kwargs):  # pragma: no cover - abstract
        raise NotImplementedError

    def _init_queryable(self, points: QueryPoints) -> tuple[list, list[int] | None]:
        """Default: query every point (batching drops NaN coords itself)."""
        return ["no_match"] * len(points), None

    def _extra_columns(self, matched: list, n_unique: int) -> dict:  # pragma: no cover
        raise NotImplementedError

    def _extra_diagnostics(self, points: QueryPoints, candidate_positions) -> dict:
        return {}
