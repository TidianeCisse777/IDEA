"""LangChain tools for OGSL environmental profiles."""
from __future__ import annotations

import hashlib
import io
import json
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from langchain_core.tools import tool

from core.environment_resolver import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    DEFAULT_TIME_END_CANDIDATES,
    compute_bbox_time_window,
    detect_column,
    match_ctd_rows,
    parse_source_coords,
    resolve_source_dataframe,
)
from core.enrich_scoping import scope_dataframe
from core.erddap_batching import (
    source_batch_positions,
    spatial_subbatch_positions,
    unique_coordinate_positions,
    run_batches_in_parallel,
)
from core.ogsl_client import query_ogsl as _query_ogsl, OGSL_DATASET_ID, OGSL_VARIABLES
from core.ogsl_enrichment import build_station_windows, enrich_with_ogsl as _enrich_with_ogsl_helper
from tools.dataset_registry import (
    OGSL,
    OGSL_ENRICHED,
    dataset_variable_name,
    enrichment_source_note,
    store_dataset,
)
from tools.public_url import download_url
from tools.point_enrichment import (
    MatchResult,
    QueryPoints,
    RequiredCoords,
    format_method_block,
    run_point_enrichment,
)
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)

_OGSL_TABLEDAP_URL = (
    f"https://erddap.ogsl.ca/erddap/tabledap/{OGSL_DATASET_ID}.csvp"
)
_OGSL_CORE_COLUMNS = (
    "time",
    "latitude",
    "longitude",
    "cruiseID",
    "stationID",
    "cast_number",
    "PRES",
)
# Friendly-name → OGSL-native mapping (Bio-ORACLE-style names → ERDDAP cols).
_OGSL_FRIENDLY_VARS: dict[str, str] = {
    "temperature": "TE90", "temp": "TE90", "température": "TE90",
    "te90": "TE90",
    "salinity": "PSAL", "salinité": "PSAL", "salinite": "PSAL", "sal": "PSAL",
    "psal": "PSAL",
    "oxygen": "OXYM", "oxygène": "OXYM", "oxygene": "OXYM", "o2": "OXYM",
    "oxym": "OXYM",
    "ph": "PHPH", "phph": "PHPH",
    "nitrate": "NTRA", "no3": "NTRA", "ntra": "NTRA",
    "chlorophyll": "FLOR", "chlorophylle": "FLOR", "chl": "FLOR",
    "fluorescence": "FLOR", "flor": "FLOR",
    "density": "SIGT", "densité": "SIGT", "sigma": "SIGT", "sigt": "SIGT",
    "turbidity": "TRB", "trb": "TRB",
    "iron": "FLOR",
    "dfe": "FLOR",
}


def _normalize_ogsl_var(value: str) -> str:
    if not isinstance(value, str):
        return str(value)
    return _OGSL_FRIENDLY_VARS.get(value.strip().lower(), value)


class OgslMatcher:
    """PointMatcher adapter for OGSL ISMER CTD nearest-profile matching.

    Same shape as AmundsenMatcher (ERDDAP bbox batching + fallback + nearest
    profile) minus the hardcoded time-range gate — OGSL has no fixed coverage
    window. Produces `ogsl_*` value columns + per-unique statuses + batching
    diagnostics; the tool owns store/method block.
    """

    prefix = "ogsl"
    label = "OGSL"

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
        unique_lat = points.latitude
        unique_lon = points.longitude
        unique_time = points.time
        unique_time_end = points.time_end
        unique_depth = points.depth
        n_unique = len(points)

        unique_statuses: list[object] = ["no_match"] * n_unique
        unique_station_ids: list[object] = [pd.NA] * n_unique
        unique_cruise_ids: list[object] = [pd.NA] * n_unique
        unique_cast_numbers: list[object] = [pd.NA] * n_unique
        unique_ctd_times_matched: list[object] = [pd.NA] * n_unique
        unique_distances_km: list[object] = [pd.NA] * n_unique
        unique_time_deltas_min: list[object] = [pd.NA] * n_unique
        unique_pres_values: list[object] = [pd.NA] * n_unique
        unique_te90_values: list[object] = [pd.NA] * n_unique
        unique_psal_values: list[object] = [pd.NA] * n_unique
        unique_oxym_values: list[object] = [pd.NA] * n_unique

        batch_positions = source_batch_positions(
            src_lat=unique_lat,
            src_lon=unique_lon,
            src_time=unique_time,
            spatial_bin_degrees=float(self.initial_batch_spatial_degrees),
            max_positions=int(self.max_source_points_per_batch),
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
                    ctd = _fetch_ogsl_bbox(**fetch_kwargs)
                except TypeError:
                    fetch_kwargs.pop("pres_range", None)
                    ctd = _fetch_ogsl_bbox(**fetch_kwargs)
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
                unique_statuses[unique_position] = match.status
                if match.chosen_idx is None:
                    continue
                best = ctd.iloc[match.chosen_idx]
                unique_station_ids[unique_position] = best.get("stationID")
                unique_cruise_ids[unique_position] = best.get("cruiseID")
                unique_cast_numbers[unique_position] = best.get("cast_number")
                unique_ctd_times_matched[unique_position] = best.get("time")
                unique_distances_km[unique_position] = match.distance_km
                unique_time_deltas_min[unique_position] = (
                    match.time_delta_min
                    if match.time_delta_min is not None
                    else pd.NA
                )
                unique_pres_values[unique_position] = best.get("PRES")
                unique_te90_values[unique_position] = best.get("TE90")
                unique_psal_values[unique_position] = best.get("PSAL")
                unique_oxym_values[unique_position] = best.get("OXYM")
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
            "ogsl_dataset_id": [OGSL_DATASET_ID] * n_unique,
            "ogsl_station_id": unique_station_ids,
            "ogsl_cruise_id": unique_cruise_ids,
            "ogsl_cast_number": unique_cast_numbers,
            "ogsl_time": unique_ctd_times_matched,
            "ogsl_distance_km": unique_distances_km,
            "ogsl_time_delta_min": unique_time_deltas_min,
            "ogsl_pres_dbar": unique_pres_values,
            "ogsl_te90_degC": unique_te90_values,
            "ogsl_psal_psu": unique_psal_values,
            "ogsl_oxym_umol_kg": unique_oxym_values,
        })
        return MatchResult(
            columns=columns,
            statuses=pd.Series(unique_statuses),
            n_matched=unique_statuses.count("matched"),
            diagnostics={
                "erddap_calls": counters["erddap_calls"],
                "batch_count": len(batch_positions),
                "fallback_months": fallback_months,
                "fallback_subbatches": fallback_subbatches,
                "fetch_failures": fetch_failures,
            },
        )

def _fetch_ogsl_bbox(
    *,
    bbox: dict,
    time_window: dict,
    variables: list[str],
    pres_range: dict | None = None,
) -> pd.DataFrame:
    """Fetch OGSL CTD rows within a bbox + time window from ERDDAP tabledap."""
    columns = list(dict.fromkeys([*_OGSL_CORE_COLUMNS, *variables]))
    constraints = [
        f"latitude>={float(bbox['lat_min']):.4f}",
        f"latitude<={float(bbox['lat_max']):.4f}",
        f"longitude>={float(bbox['lon_min']):.4f}",
        f"longitude<={float(bbox['lon_max']):.4f}",
        f"time>={time_window['start']}",
        f"time<={time_window['end']}",
    ]
    if pres_range is not None:
        constraints.extend(
            [
                f"PRES>={float(pres_range['min']):.3f}",
                f"PRES<={float(pres_range['max']):.3f}",
            ]
        )
    query = ",".join(columns) + "&" + "&".join(
        quote(c, safe="><=:-T.Z") for c in constraints
    )
    url = f"{_OGSL_TABLEDAP_URL}?{query}"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return pd.DataFrame(columns=columns)
    response.raise_for_status()
    dataframe = pd.read_csv(io.StringIO(response.text))
    # ERDDAP .csvp suffixes columns with units, e.g. "PRES (decibars)".
    import re
    dataframe = dataframe.rename(
        columns={c: re.sub(r"\s+\([^)]*\)$", "", str(c)) for c in dataframe.columns}
    )
    return dataframe


def make_ogsl_tools(thread_id: str) -> list:
    """Create LangChain OGSL tools for one thread."""

    @tool
    def query_ogsl(
        station_column: str,
        time_column: str,
        depth_column: str | None = None,
        variables: list[str] | None = None,
        time_tolerance_hours: float = 24,
        depth_tolerance_m: float = 10,
        confirmed: bool = False,
    ) -> str:
        """Enrich the active table with matching OGSL CTD profiles.

        Pass station and sampling-time column names from the loaded table, plus
        an optional depth column. The tool builds one remote query window per
        unique station, stores raw OGSL data as `df_ogsl`, and creates a
        same-cardinality enriched table. Variable names must use OGSL codes.
        """
        try:
            session = _store.get(thread_id)
            source = session.get("df") if session else None
            if not isinstance(source, pd.DataFrame) or source.empty:
                return "No active table is available for OGSL station lookup."
            required_columns = [station_column, time_column]
            if depth_column:
                required_columns.append(depth_column)
            missing_columns = [
                column for column in required_columns if column not in source.columns
            ]
            if missing_columns:
                return (
                    "Columns not found in the active table: "
                    + ", ".join(missing_columns)
                )

            # Garde-fou : si la colonne depth est entièrement vide, l'ignorer
            # silencieusement plutôt que de bloquer 100 % des matches sur un
            # `missing_depth` artificiel. Évite le piège où l'agent passe une
            # colonne `object_depth_min` ou autre nominalement présente mais
            # toujours NaN dans certains exports EcoTaxa.
            depth_ignored = False
            if depth_column and source[depth_column].notna().sum() == 0:
                depth_column = None
                depth_ignored = True

            station_windows, _ = build_station_windows(
                source,
                station_column=station_column,
                time_column=time_column,
                tolerance_hours=time_tolerance_hours,
            )
            if not station_windows:
                return f"No station IDs found in column: {station_column}"
            if len(station_windows) > 10 and not confirmed:
                return (
                    f"Confirmation required: {len(station_windows)} unique stations "
                    "will trigger the same number of OGSL requests. Ask the user "
                    "for confirmation, then call again with confirmed=true."
                )

            selected_variables = variables or ["PRES", "TE90", "PSAL", "OXYM"]
            raw_output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.csv"
            result = _query_ogsl(
                {
                    "station_windows": station_windows,
                    "variables": selected_variables,
                },
                output_path=raw_output_path,
            )
            raw_dataframe = pd.read_csv(raw_output_path)
            query_payload = {
                "station_windows": station_windows,
                "variables": selected_variables,
                "time_tolerance_hours": time_tolerance_hours,
                "depth_tolerance_m": depth_tolerance_m,
            }
            query_id = hashlib.sha256(
                json.dumps(query_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()[:12]
            raw_variable_name = dataset_variable_name(
                "ogsl",
                result["dataset_id"],
                query_id,
            )
            store_dataset(
                _store,
                thread_id,
                raw_dataframe,
                variable_name=raw_variable_name,
                meta={
                    "source": "ogsl",
                    "dataset_id": result["dataset_id"],
                    "station_windows": station_windows,
                    "variables": selected_variables,
                    "n_rows": len(raw_dataframe),
                },
                latest_alias=OGSL,
            )

            enriched = _enrich_with_ogsl_helper(
                source,
                raw_dataframe,
                station_column=station_column,
                time_column=time_column,
                depth_column=depth_column,
                variables=selected_variables,
                time_tolerance_hours=time_tolerance_hours,
                depth_tolerance_m=depth_tolerance_m,
            )
            enriched_output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.csv"
            enriched.to_csv(enriched_output_path, index=False)
            enriched_variable_name = dataset_variable_name(
                "ogsl_enriched", query_id
            )
            store_dataset(
                _store,
                thread_id,
                enriched,
                variable_name=enriched_variable_name,
                meta={
                    "source": "ogsl_enrichment",
                    "dataset_id": result["dataset_id"],
                    "raw_variable_name": raw_variable_name,
                    "station_column": station_column,
                    "time_column": time_column,
                    "depth_column": depth_column,
                    "time_tolerance_hours": time_tolerance_hours,
                    "depth_tolerance_m": depth_tolerance_m,
                    "n_rows": len(enriched),
                },
            )
            status_counts = enriched["ogsl_match_status"].value_counts().to_dict()
            depth_note = (
                "\nNote: depth_column was empty in the source table and was ignored."
                if depth_ignored else ""
            )
            return (
                f"OGSL loaded - {result['row_count']} raw rows from "
                f"{len(station_windows)} station requests.\n"
                f"Raw data: `{raw_variable_name}` and `df_ogsl`.\n"
                f"Enriched data: `{enriched_variable_name}` "
                f"({len(enriched)} rows).\n"
                f"Match status: {status_counts}.{depth_note}\n"
                f"Raw download: {download_url(raw_output_path.name)}\n"
                f"Enriched download: {download_url(enriched_output_path.name)}"
            )
        except Exception as exc:
            return f"Error while accessing OGSL: {exc}"

    @tool
    def enrich_with_ogsl(
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        time_column: str | None = None,
        depth_column: str | None = None,
        variables: list[str] | None = None,
        spatial_tolerance_km: float = 25.0,
        time_tolerance_hours: float = 24.0,
        source_variable: str | None = None,
        initial_batch_spatial_degrees: float = 5.0,
        batch_spatial_degrees: float = 5.0,
        max_source_points_per_batch: int = 50,
        max_ctd_rows_per_batch: int = 20000,
        depth_padding_dbar: float = 25.0,
        max_workers: int = 6,
        zone_name: str | None = None,
        date_range: list | None = None,
    ) -> str:
        """Enrichit la table chargée avec OGSL ISMER CTD par lat/lon/time.

        Auto-détecte les colonnes lat/lon/time/depth. Interroge OGSL ERDDAP
        par lots bbox + fenêtre temps en parallèle, puis matche localement au
        plus proche voisin. Si plusieurs fichiers sont en session, passe
        `source_variable` (ex. `df_file_filet_arctic_2018`) pour cibler un
        dataset précis.
        """
        raw_variables = list(
            variables or ["TE90", "PSAL", "SIGT", "OXYM", "PHPH", "NTRA", "FLOR"]
        )
        selected_variables: list[str] = []
        for v in raw_variables:
            translated = _normalize_ogsl_var(v)
            if translated not in selected_variables:
                selected_variables.append(translated)

        matcher = OgslMatcher(
            selected_variables=selected_variables,
            spatial_tolerance_km=spatial_tolerance_km,
            time_tolerance_hours=time_tolerance_hours,
            initial_batch_spatial_degrees=initial_batch_spatial_degrees,
            batch_spatial_degrees=batch_spatial_degrees,
            max_source_points_per_batch=max_source_points_per_batch,
            max_ctd_rows_per_batch=max_ctd_rows_per_batch,
            depth_padding_dbar=depth_padding_dbar,
            max_workers=max_workers,
        )
        outcome = run_point_enrichment(
            _store,
            thread_id,
            matcher=matcher,
            source_variable=source_variable,
            latitude_column=latitude_column,
            longitude_column=longitude_column,
            time_column=time_column,
            depth_column=depth_column,
            zone_name=zone_name,
            date_range=date_range,
        )
        if outcome.error:
            return outcome.error

        enriched = outcome.enriched
        n = outcome.n_rows
        n_unique = outcome.n_unique
        diag = outcome.diagnostics

        variable_name = dataset_variable_name("ogsl_enriched", uuid.uuid4().hex[:12])
        status_counts = enriched["ogsl_match_status"].value_counts().to_dict()
        n_matched = int(status_counts.get("matched", 0))
        n_no_value = int(status_counts.get("matched_no_value", 0))
        n_no_match = int(status_counts.get("no_match", 0))
        store_dataset(
            _store, thread_id, enriched,
            variable_name=variable_name,
            meta={
                "source": "ogsl_enrichment",
                "n_rows": n,
                "matched_rows": n_matched,
            },
            latest_alias=OGSL_ENRICHED,
        )
        plural = "matchées" if n_matched > 1 else "matchée"
        method_lines = format_method_block(outcome) + [
            (
                f"- Colonnes source détectées : latitude={outcome.lat_col!r}, "
                f"longitude={outcome.lon_col!r}, time={outcome.time_col!r}"
                + (f", depth={outcome.depth_col!r}" if outcome.depth_col else "")
            ),
            f"- Dataset interrogé : OGSL ERDDAP `{OGSL_DATASET_ID}`",
            (
                f"- Tolérances : spatial={spatial_tolerance_km:g} km, "
                f"temps={time_tolerance_hours:g} h"
            ),
            f"- Variables récupérées : {', '.join(selected_variables)}",
            (
                f"- Points source uniques interrogés : {n_unique} sur "
                f"{n} ligne(s)"
            ),
            (
                f"- Bornes batch : max_source_points={int(max_source_points_per_batch)}, "
                f"max_ctd_rows={int(max_ctd_rows_per_batch)}, "
                f"depth_padding_dbar={float(depth_padding_dbar):g}"
            ),
            (
                f"- Requêtes ERDDAP : {diag['erddap_calls']} lot(s) temps-espace "
                f"({diag['batch_count']} lot(s) initiaux par mois/grille "
                f"{float(initial_batch_spatial_degrees):g}°, "
                f"{diag['fallback_months']} lot(s) splitté(s) en "
                f"{diag['fallback_subbatches']} sous-lot(s) grille "
                f"{float(batch_spatial_degrees):g}°)"
            ),
            (
                f"- Statuts : matched={n_matched}, "
                f"matched_no_value={n_no_value}, no_match={n_no_match}"
            ),
        ]
        matched_mask = enriched["ogsl_match_status"].isin(
            ["matched", "matched_no_value"]
        )
        if matched_mask.any():
            dist_series = pd.to_numeric(
                enriched.loc[matched_mask, "ogsl_distance_km"], errors="coerce"
            ).dropna()
            time_series = pd.to_numeric(
                enriched.loc[matched_mask, "ogsl_time_delta_min"], errors="coerce"
            ).dropna()
            if len(dist_series) or len(time_series):
                quality_bits: list[str] = []
                if len(dist_series):
                    quality_bits.append(
                        f"distance_km min={dist_series.min():.2f} "
                        f"med={dist_series.median():.2f} max={dist_series.max():.2f}"
                    )
                if len(time_series):
                    quality_bits.append(
                        f"time_delta_min min={time_series.min():.1f} "
                        f"med={time_series.median():.1f} max={time_series.max():.1f}"
                    )
                method_lines.append(
                    "- Qualité d'appariement (sur lignes matched) : "
                    + " ; ".join(quality_bits)
                )
        fetch_failures = diag.get("fetch_failures", [])
        if fetch_failures:
            method_lines.append(
                f"- Avertissement : {len(fetch_failures)} lot(s) ERDDAP en erreur, "
                "lignes conservées avec `no_match`."
            )
        if n_no_match:
            method_lines.append(
                f"- Note : {n_no_match} ligne(s) sans match — la zone-date "
                "n'est probablement pas couverte par OGSL ISMER CTD."
            )
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) avec profil trouvé mais "
                "valeurs CTD manquantes à l'origine."
            )
        return (
            f"Enrichissement OGSL — {n} ligne(s), {n_matched} {plural}.\n"
            f"{outcome.source_note}\n"
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines)
        )

    return [query_ogsl, enrich_with_ogsl]
