"""LangChain tools for OGSL environmental profiles."""
from __future__ import annotations

import hashlib
import io
import json
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
    compute_bbox_time_window,
    detect_column,
    match_ctd_rows,
    parse_source_coords,
    resolve_source_dataframe,
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

def _fetch_ogsl_bbox(*, bbox: dict, time_window: dict, variables: list[str]) -> pd.DataFrame:
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
    ) -> str:
        """Enrichit la table chargée avec OGSL ISMER CTD par lat/lon/time.

        Auto-détecte les colonnes lat/lon/time/depth. Interroge OGSL ERDDAP
        par bbox + fenêtre temps puis matche localement au plus proche voisin.
        Si plusieurs fichiers sont en session, passe `source_variable`
        (ex. `df_file_filet_arctic_2018`) pour cibler un dataset précis.
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

        selected_variables = list(variables or ["TE90", "PSAL", "OXYM"])

        coords = parse_source_coords(
            source,
            lat_col=lat_col,
            lon_col=lon_col,
            time_col=time_col,
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
        src_depth = coords.depth

        bbox, time_window = compute_bbox_time_window(
            src_lat=src_lat,
            src_lon=src_lon,
            src_time=src_time,
            time_padding_hours=time_tolerance_hours,
        )

        ctd = _fetch_ogsl_bbox(
            bbox=bbox, time_window=time_window, variables=selected_variables
        )

        matches = match_ctd_rows(
            src_lat=src_lat,
            src_lon=src_lon,
            src_time=src_time,
            src_depth=src_depth,
            ctd=ctd,
            ctd_pres_col="PRES",
            variables_for_value_check=selected_variables,
            spatial_tolerance_km=spatial_tolerance_km,
            time_tolerance_hours=time_tolerance_hours,
        )

        statuses: list[str] = []
        station_ids: list[object] = []
        cruise_ids: list[object] = []
        cast_numbers: list[object] = []
        ctd_times_matched: list[object] = []
        distances_km: list[object] = []
        time_deltas_min: list[object] = []
        pres_values: list[object] = []
        te90_values: list[object] = []
        psal_values: list[object] = []
        oxym_values: list[object] = []
        for match in matches:
            statuses.append(match.status)
            if match.chosen_idx is None:
                station_ids.append(pd.NA); cruise_ids.append(pd.NA)
                cast_numbers.append(pd.NA); ctd_times_matched.append(pd.NA)
                distances_km.append(pd.NA); time_deltas_min.append(pd.NA)
                pres_values.append(pd.NA); te90_values.append(pd.NA)
                psal_values.append(pd.NA); oxym_values.append(pd.NA)
                continue
            best = ctd.iloc[match.chosen_idx]
            station_ids.append(best.get("stationID"))
            cruise_ids.append(best.get("cruiseID"))
            cast_numbers.append(best.get("cast_number"))
            ctd_times_matched.append(best.get("time"))
            distances_km.append(match.distance_km)
            time_deltas_min.append(
                match.time_delta_min if match.time_delta_min is not None else pd.NA
            )
            pres_values.append(best.get("PRES"))
            te90_values.append(best.get("TE90"))
            psal_values.append(best.get("PSAL"))
            oxym_values.append(best.get("OXYM"))

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
            "- 1 seule requête ERDDAP bbox+fenêtre pour toutes les lignes",
            (
                f"- Statuts : matched={n_matched}, "
                f"matched_no_value={n_no_value}, no_match={n_no_match}"
            ),
        ]
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
