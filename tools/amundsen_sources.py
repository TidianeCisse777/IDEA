"""LangChain tools for Amundsen CTD."""
from __future__ import annotations

import io
import uuid
import hashlib
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from langchain_core.tools import tool

_AMUNDSEN_DATASET_ID = "amundsen12713"
_AMUNDSEN_TABLEDAP_URL = (
    f"https://erddap.amundsenscience.com/erddap/tabledap/{_AMUNDSEN_DATASET_ID}.csv"
)
_AMUNDSEN_CORE_COLUMNS = ("time", "latitude", "longitude", "station", "cast_number", "PRES")


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
from core.amundsen_ctd_client import (
    list_amundsen_datasets as _list_amundsen_datasets,
    preview_amundsen_profile as _preview_amundsen_profile,
    query_amundsen_ctd as _query_amundsen_ctd,
)
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.public_url import download_url
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _fetch_amundsen_bbox(*, bbox: dict, time_window: dict, variables: list[str]) -> pd.DataFrame:
    """Fetch Amundsen CTD rows within a bbox + time window from ERDDAP tabledap.

    Returns a DataFrame with `time`, `latitude`, `longitude`, `station`,
    `cast_number`, `PRES`, and the requested variables. ERDDAP CSV emits a
    units row right after the header — it is dropped here.
    """
    columns = list(dict.fromkeys([*_AMUNDSEN_CORE_COLUMNS, *variables]))
    constraints = [
        f"latitude>={float(bbox['lat_min']):.4f}",
        f"latitude<={float(bbox['lat_max']):.4f}",
        f"longitude>={float(bbox['lon_min']):.4f}",
        f"longitude<={float(bbox['lon_max']):.4f}",
        f"time>={time_window['start']}",
        f"time<={time_window['end']}",
    ]
    query = ",".join(columns) + "&" + "&".join(
        quote(constraint, safe="><=:-T.Z") for constraint in constraints
    )
    url = f"{_AMUNDSEN_TABLEDAP_URL}?{query}"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return pd.DataFrame(columns=columns)
    response.raise_for_status()
    lines = response.text.splitlines()
    if len(lines) <= 1:
        return pd.DataFrame(columns=columns)
    body = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else lines[0]
    return pd.read_csv(io.StringIO(body))


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "Aucun résultat Amundsen."
    dataframe = pd.DataFrame(rows)
    available_columns = [column for column in columns if column in dataframe.columns]
    if available_columns:
        dataframe = dataframe.loc[:, available_columns]
    return dataframe.to_markdown(index=False)


def make_amundsen_tools(thread_id: str) -> list:
    """Create LangChain Amundsen CTD tools for one thread."""

    def _source_dataframe(source_variable: str | None = None) -> pd.DataFrame | None:
        if source_variable:
            for key in _store.keys(f"{thread_id}:dataset:"):
                named = _store.get(key)
                if not named:
                    continue
                var_name = (named.get("meta") or {}).get("variable_name") or key.rsplit(":", 1)[-1]
                if var_name == source_variable:
                    dataframe = named.get("df")
                    if isinstance(dataframe, pd.DataFrame) and not dataframe.empty:
                        return dataframe
            return None
        session = _store.get(thread_id)
        dataframe = session.get("df") if session else None
        return dataframe if isinstance(dataframe, pd.DataFrame) and not dataframe.empty else None

    def _nearest_ctd_row(ctd: pd.DataFrame, depth: object | None) -> pd.Series | None:
        if ctd.empty:
            return None
        depth_col = next(
            (column for column in ("Pres", "PRES", "depth") if column in ctd.columns),
            None,
        )
        if depth is None or depth_col is None:
            return ctd.iloc[0]
        depth_values = pd.to_numeric(ctd[depth_col], errors="coerce")
        target_depth = pd.to_numeric(pd.Series([depth]), errors="coerce").iloc[0]
        if pd.isna(target_depth) or depth_values.notna().sum() == 0:
            return ctd.iloc[0]
        nearest_index = (depth_values - float(target_depth)).abs().idxmin()
        return ctd.loc[nearest_index]

    @tool
    def list_amundsen_datasets() -> str:
        """Liste les datasets CTD Amundsen disponibles dans ERDDAP."""
        try:
            datasets = _list_amundsen_datasets()
        except Exception as exc:
            return f"Erreur lors de l'accès à Amundsen : {exc}"
        if not datasets:
            return "Aucun dataset Amundsen trouvé."
        return _format_table(datasets, ["dataset_id", "title", "griddap"])

    @tool
    def preview_amundsen_profile(station: str | None = None, cast_number: int | None = None) -> str:
        """Prévisualise un profil CTD Amundsen avec des alias de jointure."""
        try:
            preview = _preview_amundsen_profile({"station": station, "cast_number": cast_number})
            rows = preview["rows"]
            if not rows:
                return "Aucun profil Amundsen trouvé."
            return _format_table(rows[:10], ["time", "station", "cast_number", "Pres", "Temp", "Sal", "profile_id", "station_id", "cast_id"])
        except Exception as exc:
            return f"Erreur lors de l'accès à Amundsen : {exc}"

    @tool
    def query_amundsen_ctd(station: str | None = None, cast_number: int | None = None) -> str:
        """Extrait un profil CTD Amundsen complet et écrit un TSV téléchargeable."""
        try:
            file_id = uuid.uuid4().hex
            output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
            result = _query_amundsen_ctd({"station": station, "cast_number": cast_number}, output_path=output_path)
            dataframe = pd.read_csv(output_path, sep="\t")
            identity_parts: list[object] = [result["dataset_id"]]
            if station is not None:
                identity_parts.append(station)
            if cast_number is not None:
                identity_parts.extend(["cast", cast_number])
            variable_name = dataset_variable_name("amundsen", *identity_parts)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={
                    "source": f"amundsen:{result['dataset_id']}",
                    "dataset_id": result["dataset_id"],
                    "station": station,
                    "cast_number": cast_number,
                    "n_rows": len(dataframe),
                },
                latest_alias="ctd",
            )
            return (
                f"Amundsen CTD chargé — {result['row_count']} lignes.\n"
                f"Données disponibles dans `{variable_name}` et `df_ctd`.\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {result['download_url']}"
            )
        except Exception as exc:
            return f"Erreur lors de l'accès à Amundsen : {exc}"

    @tool
    def enrich_loaded_table_with_amundsen_ctd(
        station_column: str | None = None,
        cast_column: str | None = None,
        time_column: str | None = None,
        depth_column: str | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        profile_column: str | None = None,
        max_rows: int | None = None,
    ) -> str:
        """Enrichit la table chargée avec la CTD Amundsen quand les clés existent.

        Ce tool est le point d'entrée pour "enrichis ce fichier avec Amundsen".
        Il lit la table active en session, conserve toutes les lignes sources et
        ajoute des colonnes `ctd_*` / `amundsen_*`.

        Pour un enrichissement direct, fournir `station_column` + `cast_column`.
        `depth_column` est optionnel mais recommandé pour prendre la mesure CTD
        la plus proche en profondeur. Si la table n'a pas de station/cast ni de
        latitude/longitude + temps, le tool retourne un diagnostic traçable avec
        `ctd_match_status=missing_sample_metadata` au lieu d'une erreur opaque.
        """
        try:
            source = _source_dataframe()
            if source is None:
                return "Aucune table chargée à enrichir."

            requested_columns = {
                "station_column": station_column,
                "cast_column": cast_column,
                "time_column": time_column,
                "depth_column": depth_column,
                "latitude_column": latitude_column,
                "longitude_column": longitude_column,
                "profile_column": profile_column,
            }
            missing_requested = [
                name
                for name, column in requested_columns.items()
                if column and column not in source.columns
            ]
            if missing_requested:
                return (
                    "Colonnes demandées absentes de la table chargée : "
                    + ", ".join(f"{name}={requested_columns[name]!r}" for name in missing_requested)
                )

            has_station_cast = bool(
                station_column
                and cast_column
                and station_column in source.columns
                and cast_column in source.columns
            )
            has_spatiotemporal = bool(
                latitude_column
                and longitude_column
                and time_column
                and latitude_column in source.columns
                and longitude_column in source.columns
                and time_column in source.columns
            )

            dataframe = source.copy(deep=True)
            if max_rows is not None:
                dataframe = dataframe.head(int(max_rows)).copy()

            if not has_station_cast:
                missing_groups = []
                if not has_spatiotemporal:
                    if not (latitude_column and latitude_column in source.columns):
                        missing_groups.append("latitude")
                    if not (longitude_column and longitude_column in source.columns):
                        missing_groups.append("longitude")
                    if not (time_column and time_column in source.columns):
                        missing_groups.append("time")
                missing_groups.extend(["station", "cast_number"])
                dataframe["ctd_match_status"] = "missing_sample_metadata"
                dataframe["ctd_missing_columns"] = ", ".join(dict.fromkeys(missing_groups))
                if profile_column and profile_column in dataframe.columns:
                    dataframe["ctd_profile_key"] = dataframe[profile_column].astype(str)

                query_fingerprint = hashlib.sha256(
                    (
                        f"{list(dataframe.columns)}|missing_sample_metadata|"
                        f"{len(dataframe.index)}"
                    ).encode("utf-8")
                ).hexdigest()[:12]
                variable_name = dataset_variable_name("amundsen_enriched", query_fingerprint)
                output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
                dataframe.to_csv(output_path, sep="\t", index=False)
                store_dataset(
                    _store,
                    thread_id,
                    dataframe,
                    variable_name=variable_name,
                    meta={
                        "source": "amundsen_enrichment",
                        "match_status": "missing_sample_metadata",
                        "missing_columns": list(dict.fromkeys(missing_groups)),
                        "n_rows": len(dataframe),
                    },
                    latest_alias="ctd_enriched",
                )
                preview = dataframe.head(20).to_markdown(index=False)
                return (
                    "Enrichissement Amundsen impossible avec les métadonnées actuelles : "
                    "station/cast ou latitude/longitude/temps manquants.\n"
                    f"Données diagnostiques disponibles dans `{variable_name}`.\n"
                    f"Aperçu :\n\n{preview}\n\n"
                    f"Télécharger : {download_url(output_path.name)}"
                )

            cache: dict[tuple[str, str], pd.DataFrame] = {}
            statuses = []
            matched_rows: list[dict] = []
            for _, row in dataframe.iterrows():
                station = row.get(station_column)
                cast_number = row.get(cast_column)
                key = (str(station), str(cast_number))
                if pd.isna(station) or pd.isna(cast_number):
                    statuses.append("missing_sample_metadata")
                    matched_rows.append({})
                    continue
                if key not in cache:
                    try:
                        result = _query_amundsen_ctd(
                            {"station": str(station), "cast_number": int(float(cast_number))}
                        )
                        cache[key] = pd.DataFrame(result["rows"]) if "rows" in result else pd.read_csv(result["file_path"], sep="\t")
                    except Exception:
                        cache[key] = pd.DataFrame()
                nearest = _nearest_ctd_row(
                    cache[key],
                    row.get(depth_column) if depth_column else None,
                )
                if nearest is None:
                    statuses.append("no_match")
                    matched_rows.append({})
                    continue
                statuses.append("matched")
                depth_value = row.get(depth_column) if depth_column else None
                ctd_depth = nearest.get("Pres", nearest.get("PRES", nearest.get("depth")))
                try:
                    depth_delta = abs(float(depth_value) - float(ctd_depth)) if depth_value is not None else None
                except (TypeError, ValueError):
                    depth_delta = None
                matched_rows.append(
                    {
                        "amundsen_nearest_time": nearest.get("time"),
                        "amundsen_nearest_lat": nearest.get("latitude"),
                        "amundsen_nearest_lon": nearest.get("longitude"),
                        "amundsen_nearest_depth_m": ctd_depth,
                        "amundsen_nearest_depth_delta_m": depth_delta,
                        "amundsen_temperature_degC_nearest": nearest.get("TE90", nearest.get("Temp")),
                        "amundsen_salinity_psu_nearest": nearest.get("PSAL", nearest.get("Sal")),
                        "amundsen_station": nearest.get("station", station),
                        "amundsen_cast_number": nearest.get("cast_number", cast_number),
                    }
                )

            dataframe["ctd_match_status"] = statuses
            matched = pd.DataFrame(matched_rows)
            for column in matched.columns:
                dataframe[column] = matched[column].values

            query_fingerprint = hashlib.sha256(
                (
                    f"{station_column}|{cast_column}|{depth_column}|"
                    f"{dataframe[[station_column, cast_column]].to_json(orient='records')}"
                ).encode("utf-8")
            ).hexdigest()[:12]
            variable_name = dataset_variable_name("amundsen_enriched", query_fingerprint)
            output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
            dataframe.to_csv(output_path, sep="\t", index=False)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={
                    "source": "amundsen_enrichment",
                    "station_column": station_column,
                    "cast_column": cast_column,
                    "depth_column": depth_column,
                    "n_rows": len(dataframe),
                    "matched_rows": int((dataframe["ctd_match_status"] == "matched").sum()),
                },
                latest_alias="ctd_enriched",
            )
            preview = dataframe.head(20).to_markdown(index=False)
            return (
                f"Enrichissement Amundsen terminé — {len(dataframe)} lignes, "
                f"{int((dataframe['ctd_match_status'] == 'matched').sum())} matchées.\n"
                f"Données disponibles dans `{variable_name}` et `df_ctd_enriched`.\n"
                f"Aperçu :\n\n{preview}\n\n"
                f"Télécharger : {download_url(output_path.name)}"
            )
        except Exception as exc:
            return f"Erreur lors de l'enrichissement Amundsen : {exc}"

    @tool
    def enrich_with_amundsen_ctd(
        source_variable: str | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        time_column: str | None = None,
        depth_column: str | None = None,
        variables: list[str] | None = None,
        spatial_tolerance_km: float = 25.0,
        time_tolerance_hours: float = 24.0,
    ) -> str:
        """Enrichit la table chargée avec la CTD Amundsen par lat/lon/time.

        Auto-détecte les colonnes `latitude`, `longitude` et `time` si elles ne
        sont pas fournies. Interroge Amundsen ERDDAP par bbox + fenêtre temps
        et matche localement au plus proche voisin.
        """
        source = resolve_source_dataframe(_store, thread_id, source_variable)
        if source is None:
            if source_variable:
                return (
                    f"Variable source introuvable en session : `{source_variable}`. "
                    "Vérifie les datasets actifs."
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
                "Enrichissement Amundsen impossible : colonnes manquantes dans la "
                f"table chargée — {', '.join(missing)}. Préciser via "
                "`latitude_column`, `longitude_column`, `time_column`."
            )

        selected_variables = list(variables or ["TE90", "PSAL"])

        coords = parse_source_coords(
            source,
            lat_col=lat_col,
            lon_col=lon_col,
            time_col=time_col,
            depth_col=depth_col,
        )
        if coords.empty_groups:
            return (
                "Enrichissement Amundsen impossible : colonnes "
                f"{', '.join(coords.empty_groups)} entièrement vides dans la table "
                "chargée. Aucune coordonnée exploitable — vérifie le fichier "
                "source."
            )
        src_lat = coords.latitude
        src_lon = coords.longitude
        src_time = coords.time
        src_depth = coords.depth

        bbox, time_window = compute_bbox_time_window(
            src_lat=src_lat, src_lon=src_lon, src_time=src_time
        )

        ctd = _fetch_amundsen_bbox(
            bbox=bbox,
            time_window=time_window,
            variables=selected_variables,
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
        stations: list[object] = []
        casts: list[object] = []
        pres_values: list[object] = []
        te90: list[object] = []
        psal: list[object] = []
        distances_km: list[object] = []
        time_deltas_min: list[object] = []
        ctd_times_matched: list[object] = []
        for match in matches:
            statuses.append(match.status)
            if match.chosen_idx is None:
                stations.append(pd.NA)
                casts.append(pd.NA)
                pres_values.append(pd.NA)
                te90.append(pd.NA)
                psal.append(pd.NA)
                distances_km.append(pd.NA)
                time_deltas_min.append(pd.NA)
                ctd_times_matched.append(pd.NA)
                continue
            best = ctd.iloc[match.chosen_idx]
            stations.append(best.get("station"))
            casts.append(best.get("cast_number"))
            pres_values.append(best.get("PRES"))
            te90.append(best.get("TE90"))
            psal.append(best.get("PSAL"))
            distances_km.append(match.distance_km)
            time_deltas_min.append(
                match.time_delta_min if match.time_delta_min is not None else pd.NA
            )
            ctd_times_matched.append(best.get("time"))

        enriched = source.copy(deep=True)
        n = len(enriched)
        enriched["amundsen_match_status"] = statuses
        enriched["amundsen_dataset_id"] = ["amundsen12713"] * n
        enriched["amundsen_station"] = stations
        enriched["amundsen_cast_number"] = casts
        enriched["amundsen_time"] = ctd_times_matched
        enriched["amundsen_distance_km"] = distances_km
        enriched["amundsen_time_delta_min"] = time_deltas_min
        enriched["amundsen_pres_dbar"] = pres_values
        enriched["amundsen_te90_degC"] = te90
        enriched["amundsen_psal_psu"] = psal

        variable_name = dataset_variable_name("amundsen_enriched", uuid.uuid4().hex[:12])
        store_dataset(
            _store,
            thread_id,
            enriched,
            variable_name=variable_name,
            meta={
                "source": "amundsen_enrichment",
                "n_rows": n,
                "matched_rows": int((enriched["amundsen_match_status"] == "matched").sum()),
            },
            latest_alias="ctd_enriched",
        )
        status_counts = enriched["amundsen_match_status"].value_counts().to_dict()
        n_matched = int(status_counts.get("matched", 0))
        n_no_value = int(status_counts.get("matched_no_value", 0))
        n_no_match = int(status_counts.get("no_match", 0))
        plural = "matchées" if n_matched > 1 else "matchée"

        method_lines = [
            "Méthode :",
            (
                f"- Colonnes source détectées : latitude={lat_col!r}, "
                f"longitude={lon_col!r}, time={time_col!r}"
                + (f", depth={depth_col!r}" if depth_col else "")
            ),
            f"- Dataset interrogé : Amundsen ERDDAP `{_AMUNDSEN_DATASET_ID}`",
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
                "n'est probablement pas couverte par Amundsen Science."
            )
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) avec profil trouvé mais "
                "valeurs CTD manquantes à l'origine."
            )

        return (
            f"Enrichissement Amundsen — {n} ligne(s), {n_matched} {plural}.\n"
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines)
        )

    return [
        list_amundsen_datasets,
        preview_amundsen_profile,
        query_amundsen_ctd,
        enrich_loaded_table_with_amundsen_ctd,
        enrich_with_amundsen_ctd,
    ]
