"""LangChain tools for Amundsen CTD."""
from __future__ import annotations

import io
import json
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from langchain_core.tools import tool
from tools.tool_result import blocked, empty, error, success

from core.canonical_grid import canonicalize_amundsen_query
from core.erddap_cache import cache_get, cache_set

_AMUNDSEN_DATASET_ID = "amundsen12713"
# Friendly-name → ERDDAP-native mapping so the agent can call this tool
# with the same Bio-ORACLE-friendly vocabulary (temperature, salinity, …)
# without crashing the ERDDAP query.
_AMUNDSEN_FRIENDLY_VARS: dict[str, str] = {
    "temperature": "TE90", "temp": "TE90", "température": "TE90",
    "te90": "TE90",
    "salinity": "PSAL", "salinité": "PSAL", "salinite": "PSAL", "sal": "PSAL",
    "psal": "PSAL",
    "oxygen": "OXYM", "oxygène": "OXYM", "oxygene": "OXYM", "o2": "OXYM",
    "oxym": "OXYM",
    "ph": "pH",
    "nitrate": "NTRA", "no3": "NTRA", "ntra": "NTRA",
    "chlorophyll": "FLOR", "chlorophylle": "FLOR", "chl": "FLOR",
    "fluorescence": "FLOR", "flor": "FLOR",
    "density": "SIGT", "densité": "SIGT", "sigma": "SIGT", "sigt": "SIGT",
    "iron": "FLOR",  # Amundsen has no iron — fall back to chlorophyll proxy
    "dfe": "FLOR",
}


def _normalize_amundsen_var(value: str) -> str:
    """Translate a user-facing variable name to the Amundsen ERDDAP column."""
    if not isinstance(value, str):
        return str(value)
    return _AMUNDSEN_FRIENDLY_VARS.get(value.strip().lower(), value)
_AMUNDSEN_TABLEDAP_URL = (
    f"https://erddap.amundsenscience.com/erddap/tabledap/{_AMUNDSEN_DATASET_ID}.csv"
)
_AMUNDSEN_DATASET_URL = (
    f"https://erddap.amundsenscience.com/erddap/tabledap/{_AMUNDSEN_DATASET_ID}.html"
)


def _am_result(factory, summary: str, **fields):
    provenance = {"source": "amundsen", **dict(fields.pop("provenance", {}))}
    return factory(summary, provenance=provenance, **fields)


def _am_success(summary: str, **fields): return _am_result(success, summary, **fields)
def _am_empty(summary: str, **fields): return _am_result(empty, summary, **fields)
def _am_blocked(summary: str, **fields): return _am_result(blocked, summary, **fields)
def _am_error(summary: str, **fields): return _am_result(error, summary, **fields)
_AMUNDSEN_CORE_COLUMNS = ("time", "latitude", "longitude", "station", "cast_number", "PRES")
_AMUNDSEN_TIME_MIN = pd.Timestamp("2014-07-15T08:20:04Z")
_AMUNDSEN_TIME_MAX = pd.Timestamp("2024-10-01T02:03:25Z")


from core.environment_resolver import (
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    compute_bbox_time_window,
    detect_column,
    parse_source_coords,
    resolve_source_dataframe,
    build_enrichment_provenance,
)
from core.amundsen_ctd_client import (
    list_amundsen_datasets as _list_amundsen_datasets,
    preview_amundsen_profile as _preview_amundsen_profile,
    query_amundsen_ctd as _query_amundsen_ctd,
)
from tools.dataset_registry import (
    CTD,
    CTD_ENRICHED,
    dataset_variable_name,
    store_dataset,
)
from tools.public_url import download_url
from tools.ctd_matcher import CtdProfileMatcher
from tools.point_enrichment import format_method_block, run_point_enrichment
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _filter_to_request(
    df: pd.DataFrame, *, bbox: dict, time_window: dict
) -> pd.DataFrame:
    """Narrow a cached canonical tile down to the consumer's actual bbox/window.

    The cache holds full 5° tiles for reuse across files; consumers want
    only the rows inside their own (smaller) bbox + time window so the
    `max_ctd_rows_per_batch` guard and downstream matching see a proportional
    slice instead of the whole tile.
    """
    if df.empty:
        return df
    lat = pd.to_numeric(df.get("latitude"), errors="coerce")
    lon = pd.to_numeric(df.get("longitude"), errors="coerce")
    t = pd.to_datetime(df.get("time"), errors="coerce", utc=True)
    start = pd.Timestamp(time_window["start"])
    end = pd.Timestamp(time_window["end"])
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tz is None else end.tz_convert("UTC")
    mask = (
        lat.ge(float(bbox["lat_min"]))
        & lat.le(float(bbox["lat_max"]))
        & lon.ge(float(bbox["lon_min"]))
        & lon.le(float(bbox["lon_max"]))
        & t.ge(start)
        & t.le(end)
    )
    return df.loc[mask].reset_index(drop=True)


def _fetch_amundsen_bbox(
    *,
    bbox: dict,
    time_window: dict,
    variables: list[str],
    pres_range: dict | None = None,
) -> pd.DataFrame:
    """Fetch Amundsen CTD rows for a bbox + time window from ERDDAP tabledap.

    The source bbox/time_window/variables are snapped to a canonical
    (5° tile × calendar month × sorted variables) key so cache hits compose
    across different source files in the same zone. The `pres_range` is
    dropped from the canonical key — local matching applies depth tolerance
    on the cached profile. The returned DataFrame is then narrowed back to
    the caller's actual bbox/window so the consumer never sees more than it
    asked for.
    """
    canon_bbox, canon_time, canon_variables = canonicalize_amundsen_query(
        bbox=bbox, time_window=time_window, variables=variables
    )
    cache_key = {
        "bbox": canon_bbox,
        "time_window": canon_time,
        "variables": canon_variables,
    }
    cached = cache_get("amundsen_bbox", cache_key)
    if cached is not None:
        return _filter_to_request(cached, bbox=bbox, time_window=time_window)
    columns = list(dict.fromkeys([*_AMUNDSEN_CORE_COLUMNS, *canon_variables]))
    constraints = [
        f"latitude>={float(canon_bbox['lat_min']):.4f}",
        f"latitude<={float(canon_bbox['lat_max']):.4f}",
        f"longitude>={float(canon_bbox['lon_min']):.4f}",
        f"longitude<={float(canon_bbox['lon_max']):.4f}",
        f"time>={canon_time['start']}",
        f"time<={canon_time['end']}",
    ]
    query = ",".join(columns) + "&" + "&".join(
        quote(constraint, safe="><=:-T.Z") for constraint in constraints
    )
    url = f"{_AMUNDSEN_TABLEDAP_URL}?{query}"
    response = requests.get(url, timeout=120)
    if response.status_code == 404:
        result = pd.DataFrame(columns=columns)
        cache_set("amundsen_bbox", cache_key, result)
        return _filter_to_request(result, bbox=bbox, time_window=time_window)
    response.raise_for_status()
    lines = response.text.splitlines()
    if len(lines) <= 1:
        result = pd.DataFrame(columns=columns)
        cache_set("amundsen_bbox", cache_key, result)
        return _filter_to_request(result, bbox=bbox, time_window=time_window)
    body = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else lines[0]
    result = pd.read_csv(io.StringIO(body))
    cache_set("amundsen_bbox", cache_key, result)
    return _filter_to_request(result, bbox=bbox, time_window=time_window)


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "Aucun résultat Amundsen."
    dataframe = pd.DataFrame(rows)
    available_columns = [column for column in columns if column in dataframe.columns]
    if available_columns:
        dataframe = dataframe.loc[:, available_columns]
    return dataframe.to_markdown(index=False)


class AmundsenMatcher(CtdProfileMatcher):
    """CTD nearest-profile matcher for Amundsen ERDDAP.

    Adds the Amundsen-only fixed time-range gate (points outside the dataset's
    coverage are flagged `outside_amundsen_ctd_range` and never queried) on top
    of the shared CtdProfileMatcher machinery.
    """

    prefix = "amundsen"
    label = "Amundsen CTD"
    dataset_id = _AMUNDSEN_DATASET_ID

    def _fetch(self, **kwargs):
        return _fetch_amundsen_bbox(**kwargs)

    def _init_queryable(self, points):
        unique_time = points.time
        n_unique = len(points)
        statuses: list = ["no_match"] * n_unique
        time_in_range = (
            unique_time.ge(_AMUNDSEN_TIME_MIN) & unique_time.le(_AMUNDSEN_TIME_MAX)
        )
        outside = unique_time.notna() & ~time_in_range
        for position, is_outside in enumerate(outside.tolist()):
            if is_outside:
                statuses[position] = "outside_amundsen_ctd_range"
        candidate_positions = [
            position
            for position, can_query in enumerate(
                (
                    points.latitude.notna()
                    & points.longitude.notna()
                    & unique_time.notna()
                    & time_in_range
                ).tolist()
            )
            if can_query
        ]
        return statuses, candidate_positions

    def _extra_columns(self, matched, n_unique):
        station: list = [pd.NA] * n_unique
        cast: list = [pd.NA] * n_unique
        for position, item in enumerate(matched):
            if item is None:
                continue
            best, _ = item
            station[position] = best.get("station")
            cast[position] = best.get("cast_number")
        return {"amundsen_station": station, "amundsen_cast_number": cast}

    def _extra_diagnostics(self, points, candidate_positions):
        return {"query_unique_count": len(candidate_positions or [])}



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

    @tool(response_format="content_and_artifact")
    def list_amundsen_datasets() -> str:
        """Liste les datasets CTD Amundsen disponibles dans ERDDAP."""
        try:
            datasets = _list_amundsen_datasets()
        except Exception as exc:
            return _am_error(f"Erreur lors de l'accès à Amundsen : {exc}", retryable=True)
        if not datasets:
            return _am_empty("Aucun dataset Amundsen trouvé.")
        return _am_success(
            _format_table(datasets, ["dataset_id", "title", "griddap"]),
            metrics={"datasets": len(datasets)},
        )

    @tool(response_format="content_and_artifact")
    def preview_amundsen_profile(station: str | None = None, cast_number: int | None = None) -> str:
        """Prévisualise un profil CTD Amundsen avec des alias de jointure."""
        try:
            preview = _preview_amundsen_profile({"station": station, "cast_number": cast_number})
            rows = preview["rows"]
            if not rows:
                return _am_empty("Aucun profil Amundsen trouvé.")
            return _am_success(
                _format_table(rows[:10], ["time", "station", "cast_number", "Pres", "Temp", "Sal", "profile_id", "station_id", "cast_id"]),
                metrics={"rows": len(rows)},
            )
        except Exception as exc:
            return _am_error(f"Erreur lors de l'accès à Amundsen : {exc}", retryable=True)

    @tool(response_format="content_and_artifact")
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
                latest_alias=CTD,
            )
            summary = (
                f"Amundsen CTD chargé — {result['row_count']} lignes.\n"
                f"Données disponibles dans `{variable_name}` et `df_ctd`.\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {result['download_url']}"
            )
            return _am_success(
                summary,
                data_ref=variable_name,
                artifact_refs=(result["download_url"],),
                provenance={"dataset_id": result["dataset_id"]},
                persisted=True,
                method="Amundsen ERDDAP query",
                metrics={"rows": int(result["row_count"])},
            )
        except Exception as exc:
            return _am_error(f"Erreur lors de l'accès à Amundsen : {exc}", retryable=True)

    @tool(response_format="content_and_artifact")
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
                return _am_blocked("Aucune table chargée à enrichir.")

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
                return _am_blocked(
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
                    latest_alias=CTD_ENRICHED,
                )
                preview = dataframe.head(20).to_markdown(index=False)
                summary = (
                    "Enrichissement Amundsen impossible avec les métadonnées actuelles : "
                    "station/cast ou latitude/longitude/temps manquants.\n"
                    f"Données diagnostiques disponibles dans `{variable_name}`.\n"
                    f"Aperçu :\n\n{preview}\n\n"
                    f"Télécharger : {download_url(output_path.name)}"
                )
                return _am_blocked(
                    summary,
                    data_ref=variable_name,
                    artifact_refs=(download_url(output_path.name),),
                    persisted=True,
                    metrics={"rows": len(dataframe), "matched": 0},
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
                latest_alias=CTD_ENRICHED,
            )
            preview = dataframe.head(20).to_markdown(index=False)
            summary = (
                f"Enrichissement Amundsen terminé — {len(dataframe)} lignes, "
                f"{int((dataframe['ctd_match_status'] == 'matched').sum())} matchées.\n"
                f"Données disponibles dans `{variable_name}` et `df_ctd_enriched`.\n"
                f"Aperçu :\n\n{preview}\n\n"
                f"Télécharger : {download_url(output_path.name)}"
            )
            return _am_success(
                summary,
                data_ref=variable_name,
                artifact_refs=(download_url(output_path.name),),
                persisted=True,
                method="Amundsen station-cast enrichment",
                metrics={
                    "rows": len(dataframe),
                    "matched": int((dataframe["ctd_match_status"] == "matched").sum()),
                },
            )
        except Exception as exc:
            return _am_error(
                f"Erreur lors de l'enrichissement Amundsen : {exc}", retryable=True
            )

    @tool(response_format="content_and_artifact")
    def find_amundsen_data_for_table(
        source_variable: str | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        time_column: str | None = None,
    ) -> str:
        """Vérifie si des données CTD Amundsen existent pour la table chargée, SANS enrichir.

        À utiliser sur une question de DISPONIBILITÉ, avant tout enrichissement —
        « est-ce qu'il existe des données Amundsen pour ce fichier ? », « est-ce
        possible d'enrichir avec Amundsen (CTD) ? », « y a-t-il de la CTD Amundsen
        dans ma zone / ma période ? », « avant d'enrichir, dis-moi si ça existe ».
        Lecture seule : calcule l'emprise (bbox + période) de la table chargée et
        compte les profils CTD Amundsen dans cette emprise via ERDDAP. Ne
        télécharge ni ne stocke aucune donnée enrichie. Si des profils existent,
        proposer d'enrichir avec `enrich_with_amundsen_ctd` ; sinon dire clairement
        qu'il n'y a rien à enrichir.
        """
        source = resolve_source_dataframe(_store, thread_id, source_variable)
        if source is None:
            if source_variable:
                return _am_blocked(f"Variable source introuvable en session : `{source_variable}`.")
            return _am_blocked(
                "Aucune table chargée. Charge d'abord un fichier avec des colonnes "
                "latitude/longitude/date (`load_file`)."
            )

        lat_col = latitude_column or detect_column(source.columns, DEFAULT_LAT_CANDIDATES)
        lon_col = longitude_column or detect_column(source.columns, DEFAULT_LON_CANDIDATES)
        time_col = time_column or detect_column(source.columns, DEFAULT_TIME_CANDIDATES)
        missing = [
            name
            for name, value in (("latitude", lat_col), ("longitude", lon_col), ("time", time_col))
            if value is None
        ]
        if missing:
            return _am_blocked(
                "Vérification Amundsen impossible : colonnes manquantes dans la table "
                f"chargée — {', '.join(missing)}. Préciser via `latitude_column`, "
                "`longitude_column`, `time_column`."
            )

        coords = parse_source_coords(source, lat_col=lat_col, lon_col=lon_col, time_col=time_col)
        if coords.empty_groups:
            return _am_blocked(
                "Vérification Amundsen impossible : colonnes "
                f"{', '.join(coords.empty_groups)} entièrement vides — aucune coordonnée "
                "exploitable dans la table."
            )

        bbox, time_window = compute_bbox_time_window(
            src_lat=coords.latitude, src_lon=coords.longitude, src_time=coords.time
        )
        try:
            ctd = _fetch_amundsen_bbox(bbox=bbox, time_window=time_window, variables=["TE90"])
        except Exception as exc:
            return _am_error(f"Erreur lors de l'accès à Amundsen : {exc}", retryable=True)

        env = (
            f"lat {bbox['lat_min']:.2f}→{bbox['lat_max']:.2f}, "
            f"lon {bbox['lon_min']:.2f}→{bbox['lon_max']:.2f}, "
            f"{time_window['start'][:10]} → {time_window['end'][:10]}"
        )
        if len(ctd) == 0:
            return _am_empty(
                f"Aucune donnée CTD Amundsen dans l'emprise de la table ({env}). "
                "Rien à enrichir depuis Amundsen pour ce fichier."
            )
        station_col = next((c for c in ("station", "cast_number") if c in ctd.columns), None)
        n_profiles = int(ctd[station_col].nunique()) if station_col else 0
        profiles_txt = f"{n_profiles} profil(s)/station(s), " if n_profiles else ""
        return _am_success(
            f"Données Amundsen disponibles : {profiles_txt}{len(ctd)} ligne(s) CTD dans "
            f"l'emprise de la table ({env}). Enrichissement possible — lancer "
            "`enrich_with_amundsen_ctd` pour matcher chaque ligne à son profil CTD le "
            "plus proche (lat/lon/temps).",
            metrics={"rows": len(ctd), "profiles": n_profiles},
        )

    @tool(response_format="content_and_artifact")
    def enrich_with_amundsen_ctd(
        source_variable: str | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        time_column: str | None = None,
        depth_column: str | None = None,
        variables: list[str] | None = None,
        spatial_tolerance_km: float = 25.0,
        time_tolerance_hours: float = 24.0,
        initial_batch_spatial_degrees: float = 5.0,
        batch_spatial_degrees: float = 1.0,
        max_source_points_per_batch: int = 50,
        max_ctd_rows_per_batch: int = 200000,
        depth_padding_dbar: float = 25.0,
        max_workers: int = 6,
        zone_name: str | None = None,
        date_range: list | None = None,
    ) -> str:
        """Enrichit la table chargée avec la CTD Amundsen par lat/lon/time.

        Auto-détecte les colonnes `latitude`, `longitude` et `time` si elles ne
        sont pas fournies. Interroge Amundsen ERDDAP par lots bbox + fenêtre
        temps en parallèle, puis matche localement au plus proche voisin.

        Si `zone_name` est fourni, le df est filtré au polygone IHO/MEOW de
        cette zone avant l'enrichissement (équivalent à appeler
        `filter_dataframe_by_zone` puis enrich avec source_variable=filtré).
        Si `date_range=[start_iso, end_iso]` est fourni, un filtre date est
        appliqué sur la colonne time détectée. Les deux peuvent être combinés.
        """
        raw_variables = list(
            variables or ["TE90", "PSAL", "SIGT", "OXYM", "pH", "NTRA", "FLOR"]
        )
        selected_variables: list[str] = []
        for v in raw_variables:
            translated = _normalize_amundsen_var(v)
            if translated not in selected_variables:
                selected_variables.append(translated)

        matcher = AmundsenMatcher(
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
            return _am_blocked(outcome.error)

        enriched = outcome.enriched
        n = outcome.n_rows
        n_unique = outcome.n_unique
        diag = outcome.diagnostics

        status_counts = enriched["amundsen_match_status"].value_counts().to_dict()
        n_matched = int(status_counts.get("matched", 0))
        n_no_value = int(status_counts.get("matched_no_value", 0))
        n_no_match = int(status_counts.get("no_match", 0))
        n_outside_range = int(status_counts.get("outside_amundsen_ctd_range", 0))
        plural = "matchées" if n_matched > 1 else "matchée"

        provenance = build_enrichment_provenance(
            source="Amundsen Science CTD",
            dataset_id=_AMUNDSEN_DATASET_ID,
            dataset_url=_AMUNDSEN_DATASET_URL,
            completed_at=datetime.now(timezone.utc),
            parameters={
                "spatial_tolerance_km": spatial_tolerance_km,
                "time_tolerance_hours": time_tolerance_hours,
                "initial_batch_spatial_degrees": initial_batch_spatial_degrees,
                "batch_spatial_degrees": batch_spatial_degrees,
                "max_source_points_per_batch": max_source_points_per_batch,
                "max_ctd_rows_per_batch": max_ctd_rows_per_batch,
                "depth_padding_dbar": depth_padding_dbar,
                "max_workers": max_workers,
                "zone_name": zone_name,
                "date_range": date_range,
            },
            resolved_schema=outcome.resolved_schema,
            variables=selected_variables,
            coverage={
                "total_rows": n,
                "matched_rows": n_matched,
                "match_rate": n_matched / n if n else 0.0,
                "status_counts": status_counts,
            },
        )

        # Epilogue (source-specific): the exact provenance object rendered
        # below is persisted with the enriched dataset.
        variable_name = dataset_variable_name("amundsen_enriched", uuid.uuid4().hex[:12])
        output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
        enriched.to_csv(output_path, sep="\t", index=False)
        store_dataset(
            _store,
            thread_id,
            enriched,
            variable_name=variable_name,
            meta={
                "source": "amundsen_enrichment",
                "n_rows": n,
                "unique_source_points": n_unique,
                "matched_rows": n_matched,
                "provenance": provenance,
            },
            latest_alias=CTD_ENRICHED,
        )

        method_lines = format_method_block(outcome) + [
            (
                f"- Colonnes source détectées : latitude={outcome.lat_col!r}, "
                f"longitude={outcome.lon_col!r}, time={outcome.time_col!r}"
                + (f", depth={outcome.depth_col!r}" if outcome.depth_col else "")
            ),
            f"- Dataset interrogé : Amundsen ERDDAP `{_AMUNDSEN_DATASET_ID}`",
            (
                f"- Tolérances : spatial={spatial_tolerance_km:g} km, "
                f"temps={time_tolerance_hours:g} h"
            ),
            f"- Variables récupérées : {', '.join(selected_variables)}",
            (
                f"- Couverture temporelle Amundsen CTD : "
                f"{_AMUNDSEN_TIME_MIN.isoformat()} à "
                f"{_AMUNDSEN_TIME_MAX.isoformat()}"
            ),
            (
                f"- Points source uniques interrogés : "
                f"{diag['query_unique_count']} sur {n_unique} point(s) unique(s), "
                f"{n_unique} point(s) unique(s) sur {n} ligne(s)"
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
                f"{diag['fallback_months']} mois splitté(s) en "
                f"{diag['fallback_subbatches']} sous-lot(s) grille "
                f"{float(batch_spatial_degrees):g}°)"
            ),
            (
                f"- Statuts : matched={n_matched}, "
                f"matched_no_value={n_no_value}, no_match={n_no_match}, "
                f"outside_amundsen_ctd_range={n_outside_range}"
            ),
        ]
        matched_mask = enriched["amundsen_match_status"].isin(
            ["matched", "matched_no_value"]
        )
        if matched_mask.any():
            dist_series = pd.to_numeric(
                enriched.loc[matched_mask, "amundsen_distance_km"], errors="coerce"
            ).dropna()
            time_series = pd.to_numeric(
                enriched.loc[matched_mask, "amundsen_time_delta_min"], errors="coerce"
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
            sample_errors = []
            seen: set[str] = set()
            for raw in fetch_failures:
                short = (raw or "").strip().replace("\n", " ")[:200]
                if short and short not in seen:
                    seen.add(short)
                    sample_errors.append(short)
                if len(sample_errors) >= 3:
                    break
            for sample in sample_errors:
                method_lines.append(f"  · {sample}")
        if n_no_match:
            method_lines.append(
                f"- Note : {n_no_match} ligne(s) sans match — la zone-date "
                "est dans la plage temporelle Amundsen mais aucun profil CTD "
                "n'a été trouvé dans les tolérances."
            )
        if n_outside_range:
            method_lines.append(
                f"- Note : {n_outside_range} ligne(s) hors plage temporelle "
                "Amundsen CTD — aucune requête ERDDAP envoyée pour ces points."
            )
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) avec profil trouvé mais "
                "valeurs CTD manquantes à l'origine."
            )

        summary = (
            f"Enrichissement Amundsen — {n} ligne(s), {n_matched} {plural}.\n"
            f"{outcome.source_note}\n"
            f"Données disponibles dans `{variable_name}`.\n"
            f"Télécharger : {download_url(output_path.name)}\n\n"
            + "\n".join(method_lines)
            + f"\n\nSource : {_AMUNDSEN_DATASET_URL}\n"
            + "Provenance : "
            + json.dumps(provenance, ensure_ascii=False, sort_keys=True)
        )
        return _am_success(
            summary,
            data_ref=variable_name,
            artifact_refs=(download_url(output_path.name),),
            persisted=True,
            method="Amundsen spatiotemporal nearest-neighbor enrichment",
            metrics={"rows": n, "matched": n_matched, "unique_points": n_unique},
        )


    return [
        list_amundsen_datasets,
        preview_amundsen_profile,
        query_amundsen_ctd,
        find_amundsen_data_for_table,
        enrich_loaded_table_with_amundsen_ctd,
        enrich_with_amundsen_ctd,
    ]
