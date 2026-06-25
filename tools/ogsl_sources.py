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
from core.erddap_batching import (
    source_batch_positions,
    spatial_subbatch_positions,
    unique_coordinate_positions,
    run_batches_in_parallel,
)
from core.ogsl_client import query_ogsl as _query_ogsl, OGSL_DATASET_ID, OGSL_VARIABLES
from core.ogsl_enrichment import build_station_windows, enrich_with_ogsl as _enrich_with_ogsl_helper
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.public_url import download_url
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
                latest_alias="ogsl",
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
    ) -> str:
        """Enrichit la table chargée avec OGSL ISMER CTD par lat/lon/time.

        Auto-détecte les colonnes lat/lon/time/depth. Interroge OGSL ERDDAP
        par lots bbox + fenêtre temps en parallèle, puis matche localement au
        plus proche voisin. Si plusieurs fichiers sont en session, passe
        `source_variable` (ex. `df_file_filet_arctic_2018`) pour cibler un
        dataset précis.
        """
        source = resolve_source_dataframe(_store, thread_id, source_variable)
        if source is None:
            if source_variable:
                return (
                    f"Variable source introuvable en session : `{source_variable}`."
                )
            return "Aucune table chargée à enrichir."

        lat_col = latitude_column or detect_column(source.columns, DEFAULT_LAT_CANDIDATES)
        lon_col = longitude_column or detect_column(source.columns, DEFAULT_LON_CANDIDATES)
        time_col = time_column or detect_column(source.columns, DEFAULT_TIME_CANDIDATES)
        time_end_col = detect_column(source.columns, DEFAULT_TIME_END_CANDIDATES)
        depth_col = depth_column or detect_column(source.columns, DEFAULT_DEPTH_CANDIDATES)

        missing = [
            name
            for name, value in (
                ("latitude", lat_col),
                ("longitude", lon_col),
                ("time", time_col),
            )
            if value is None
        ]
        if missing:
            return (
                "Enrichissement OGSL impossible : colonnes manquantes — "
                f"{', '.join(missing)}. Préciser via `latitude_column`, "
                "`longitude_column`, `time_column`."
            )

        # Default pack aligned with Amundsen so users get a coherent set of
        # variables across CTD sources (physical niche + redox + productivity).
        # OGSL uses "PHPH" for pH (Amundsen uses "pH").
        selected_variables = list(
            variables or ["TE90", "PSAL", "SIGT", "OXYM", "PHPH", "NTRA", "FLOR"]
        )

        coords = parse_source_coords(
            source,
            lat_col=lat_col,
            lon_col=lon_col,
            time_col=time_col,
            time_end_col=time_end_col,
            depth_col=depth_col,
        )
        if coords.empty_groups:
            return (
                "Enrichissement OGSL impossible : colonnes "
                f"{', '.join(coords.empty_groups)} entièrement vides dans la table "
                "chargée. Aucune coordonnée exploitable."
            )
        src_lat = coords.latitude
        src_lon = coords.longitude
        src_time = coords.time
        src_time_end = coords.time_end
        src_depth = coords.depth

        unique_positions, row_to_unique = unique_coordinate_positions(
            src_lat=src_lat,
            src_lon=src_lon,
            src_time=src_time,
            src_depth=src_depth,
        )
        unique_lat = src_lat.iloc[unique_positions].reset_index(drop=True)
        unique_lon = src_lon.iloc[unique_positions].reset_index(drop=True)
        unique_time = src_time.iloc[unique_positions].reset_index(drop=True)
        unique_time_end = (
            src_time_end.iloc[unique_positions].reset_index(drop=True)
            if src_time_end is not None
            else None
        )
        unique_depth = (
            src_depth.iloc[unique_positions].reset_index(drop=True)
            if src_depth is not None
            else None
        )
        n_unique = len(unique_positions)
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
            spatial_bin_degrees=float(initial_batch_spatial_degrees),
            max_positions=int(max_source_points_per_batch),
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
                    "min": max(0.0, float(valid_depth.min()) - float(depth_padding_dbar)),
                    "max": float(valid_depth.max()) + float(depth_padding_dbar),
                }
            bbox, time_window = compute_bbox_time_window(
                src_lat=batch_lat,
                src_lon=batch_lon,
                src_time=batch_time,
                time_padding_hours=time_tolerance_hours,
            )
            try:
                with counters_lock:
                    counters["erddap_calls"] += 1
                fetch_kwargs = {
                    "bbox": bbox,
                    "time_window": time_window,
                    "variables": selected_variables,
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
            if len(ctd) > int(max_ctd_rows_per_batch):
                return False, (
                    f"too_many_ctd_rows:{len(ctd)}>"
                    f"{int(max_ctd_rows_per_batch)}"
                )

            matches = match_ctd_rows(
                src_lat=batch_lat,
                src_lon=batch_lon,
                src_time=batch_time,
                src_time_end=batch_time_end,
                src_depth=batch_depth,
                ctd=ctd,
                ctd_pres_col="PRES",
                variables_for_value_check=selected_variables,
                spatial_tolerance_km=spatial_tolerance_km,
                time_tolerance_hours=time_tolerance_hours,
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
            max_workers=int(max_workers),
        )

        fallback_subbatch_jobs: list[list[int]] = []
        for positions, (ok, error) in zip(batch_positions, initial_results):
            if ok:
                continue
            subbatches = spatial_subbatch_positions(
                positions=positions,
                src_lat=unique_lat,
                src_lon=unique_lon,
                spatial_bin_degrees=float(batch_spatial_degrees),
                src_time=unique_time,
                max_positions=int(max_source_points_per_batch),
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
            max_workers=int(max_workers),
        )
        for sub_ok, sub_error in fallback_results:
            if not sub_ok and sub_error:
                fetch_failures.append(sub_error)

        erddap_calls = counters["erddap_calls"]

        statuses = [unique_statuses[code] for code in row_to_unique]
        station_ids = [unique_station_ids[code] for code in row_to_unique]
        cruise_ids = [unique_cruise_ids[code] for code in row_to_unique]
        cast_numbers = [unique_cast_numbers[code] for code in row_to_unique]
        ctd_times_matched = [unique_ctd_times_matched[code] for code in row_to_unique]
        distances_km = [unique_distances_km[code] for code in row_to_unique]
        time_deltas_min = [unique_time_deltas_min[code] for code in row_to_unique]
        pres_values = [unique_pres_values[code] for code in row_to_unique]
        te90_values = [unique_te90_values[code] for code in row_to_unique]
        psal_values = [unique_psal_values[code] for code in row_to_unique]
        oxym_values = [unique_oxym_values[code] for code in row_to_unique]

        enriched = source.copy(deep=True)
        n = len(enriched)
        enriched["ogsl_match_status"] = statuses
        enriched["ogsl_dataset_id"] = [OGSL_DATASET_ID] * n
        enriched["ogsl_station_id"] = station_ids
        enriched["ogsl_cruise_id"] = cruise_ids
        enriched["ogsl_cast_number"] = cast_numbers
        enriched["ogsl_time"] = ctd_times_matched
        enriched["ogsl_distance_km"] = distances_km
        enriched["ogsl_time_delta_min"] = time_deltas_min
        enriched["ogsl_pres_dbar"] = pres_values
        enriched["ogsl_te90_degC"] = te90_values
        enriched["ogsl_psal_psu"] = psal_values
        enriched["ogsl_oxym_umol_kg"] = oxym_values

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
            latest_alias="ogsl_enriched",
        )
        plural = "matchées" if n_matched > 1 else "matchée"
        method_lines = [
            "Méthode :",
            (
                f"- Colonnes source détectées : latitude={lat_col!r}, "
                f"longitude={lon_col!r}, time={time_col!r}"
                + (f", depth={depth_col!r}" if depth_col else "")
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
                f"- Requêtes ERDDAP : {erddap_calls} lot(s) temps-espace "
                f"({len(batch_positions)} lot(s) initiaux par mois/grille "
                f"{float(initial_batch_spatial_degrees):g}°, "
                f"{fallback_months} lot(s) splitté(s) en "
                f"{fallback_subbatches} sous-lot(s) grille "
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
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines)
        )

    return [query_ogsl, enrich_with_ogsl]
