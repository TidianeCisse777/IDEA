"""LangChain tools for OGSL environmental profiles."""
from __future__ import annotations

import hashlib
import io
import json
import math
import uuid
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from langchain_core.tools import tool

from core.ogsl_client import query_ogsl as _query_ogsl, OGSL_DATASET_ID, OGSL_VARIABLES
from core.ogsl_enrichment import build_station_windows, enrich_with_ogsl
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

_LAT_CANDIDATES = ("latitude", "lat", "object_lat", "sample_lat")
_LON_CANDIDATES = ("longitude", "lon", "object_lon", "sample_long", "sample_lon")
_TIME_CANDIDATES = (
    "object_date",
    "time",
    "date",
    "sampling_date",
    "yyyy-mm-dd hh:mm",
    "datetime",
)
_DEPTH_CANDIDATES = (
    "object_depth_min",
    "depth",
    "pressure",
    "pres",
    "Depth [m]",
    "depth_m",
)


def _detect_column(columns, candidates: tuple[str, ...]) -> str | None:
    lower_to_real = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        match = lower_to_real.get(candidate.lower())
        if match is not None:
            return match
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


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

            enriched = enrich_with_ogsl(
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
    ) -> str:
        """Enrichit la table chargée avec OGSL ISMER CTD par lat/lon/time.

        Auto-détecte les colonnes lat/lon/time/depth. Interroge OGSL ERDDAP
        par bbox + fenêtre temps puis matche localement au plus proche voisin.
        Pas besoin de stationID — fonctionne directement sur un fichier
        EcoTaxa qui n'a que latitude/longitude/object_date.
        """
        session = _store.get(thread_id)
        source = session.get("df") if session else None
        if not isinstance(source, pd.DataFrame) or source.empty:
            return "Aucune table chargée à enrichir."

        lat_col = latitude_column or _detect_column(source.columns, _LAT_CANDIDATES)
        lon_col = longitude_column or _detect_column(source.columns, _LON_CANDIDATES)
        time_col = time_column or _detect_column(source.columns, _TIME_CANDIDATES)
        depth_col = depth_column or _detect_column(source.columns, _DEPTH_CANDIDATES)

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

        src_lat = pd.to_numeric(source[lat_col], errors="coerce")
        src_lon = pd.to_numeric(source[lon_col], errors="coerce")
        src_time = pd.to_datetime(source[time_col], errors="coerce", utc=True)

        empty_groups = [
            label
            for label, series in (
                ("latitude", src_lat),
                ("longitude", src_lon),
                ("time", src_time),
            )
            if series.notna().sum() == 0
        ]
        if empty_groups:
            return (
                "Enrichissement OGSL impossible : colonnes "
                f"{', '.join(empty_groups)} entièrement vides dans la table "
                "chargée. Aucune coordonnée exploitable."
            )

        lat_padding = 0.25
        lon_padding = 0.25
        time_padding_hours = time_tolerance_hours
        bbox = {
            "lat_min": float(src_lat.min()) - lat_padding,
            "lat_max": float(src_lat.max()) + lat_padding,
            "lon_min": float(src_lon.min()) - lon_padding,
            "lon_max": float(src_lon.max()) + lon_padding,
        }
        time_window = {
            "start": (
                src_time.min() - pd.Timedelta(hours=time_padding_hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": (
                src_time.max() + pd.Timedelta(hours=time_padding_hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        ctd = _fetch_ogsl_bbox(
            bbox=bbox, time_window=time_window, variables=selected_variables
        )

        ctd_lat = pd.to_numeric(ctd["latitude"], errors="coerce") if not ctd.empty else pd.Series(dtype=float)
        ctd_lon = pd.to_numeric(ctd["longitude"], errors="coerce") if not ctd.empty else pd.Series(dtype=float)
        ctd_time = (
            pd.to_datetime(ctd["time"], errors="coerce", utc=True)
            if "time" in ctd.columns
            else pd.Series([pd.NaT] * len(ctd))
        )
        ctd_pres = (
            pd.to_numeric(ctd["PRES"], errors="coerce")
            if "PRES" in ctd.columns
            else pd.Series([float("nan")] * len(ctd))
        )
        src_depth = (
            pd.to_numeric(source[depth_col], errors="coerce") if depth_col else None
        )
        time_tolerance = pd.Timedelta(hours=float(time_tolerance_hours))

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

        for position in range(len(source)):
            if ctd.empty:
                statuses.append("no_match")
                station_ids.append(pd.NA); cruise_ids.append(pd.NA)
                cast_numbers.append(pd.NA); ctd_times_matched.append(pd.NA)
                distances_km.append(pd.NA); time_deltas_min.append(pd.NA)
                pres_values.append(pd.NA); te90_values.append(pd.NA)
                psal_values.append(pd.NA); oxym_values.append(pd.NA)
                continue
            src_t = src_time.iloc[position]
            time_deltas = (ctd_time - src_t).abs()
            within_time = (
                time_deltas <= time_tolerance
                if not pd.isna(src_t)
                else pd.Series([True] * len(ctd))
            )
            if not within_time.any():
                statuses.append("no_match")
                station_ids.append(pd.NA); cruise_ids.append(pd.NA)
                cast_numbers.append(pd.NA); ctd_times_matched.append(pd.NA)
                distances_km.append(pd.NA); time_deltas_min.append(pd.NA)
                pres_values.append(pd.NA); te90_values.append(pd.NA)
                psal_values.append(pd.NA); oxym_values.append(pd.NA)
                continue

            distances = pd.Series(
                [
                    _haversine_km(
                        src_lat.iloc[position], src_lon.iloc[position],
                        ctd_lat.iloc[j], ctd_lon.iloc[j],
                    )
                    if within_time.iloc[j]
                    else float("inf")
                    for j in range(len(ctd))
                ]
            )
            nearest_distance = float(distances.min())
            if nearest_distance > float(spatial_tolerance_km):
                statuses.append("no_match")
                station_ids.append(pd.NA); cruise_ids.append(pd.NA)
                cast_numbers.append(pd.NA); ctd_times_matched.append(pd.NA)
                distances_km.append(pd.NA); time_deltas_min.append(pd.NA)
                pres_values.append(pd.NA); te90_values.append(pd.NA)
                psal_values.append(pd.NA); oxym_values.append(pd.NA)
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
            best_te90 = best.get("TE90")
            best_psal = best.get("PSAL")
            best_oxym = best.get("OXYM")
            requested_values = [
                best.get(variable)
                for variable in selected_variables
                if variable in best.index
            ]
            all_nan = bool(requested_values) and all(
                pd.isna(value) for value in requested_values
            )
            statuses.append("matched_no_value" if all_nan else "matched")
            station_ids.append(best.get("stationID"))
            cruise_ids.append(best.get("cruiseID"))
            cast_numbers.append(best.get("cast_number"))
            ctd_times_matched.append(best.get("time"))
            distances_km.append(round(float(distances.iloc[chosen_idx]), 3))
            time_deltas_min.append(
                round(best_dt.total_seconds() / 60.0, 1)
                if pd.notna(best_dt)
                else pd.NA
            )
            pres_values.append(best.get("PRES"))
            te90_values.append(best_te90)
            psal_values.append(best_psal)
            oxym_values.append(best_oxym)

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
