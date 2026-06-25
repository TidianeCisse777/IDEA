"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import hashlib
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from langchain_core.tools import tool

from core.bio_oracle_client import (
    _ERDDAP_BASE,
    _find_dataset_id,
    _resolve_depth,
    _resolve_scenario,
    _resolve_var,
    _time_selector,
    describe_bio_oracle_source,
    list_bio_oracle_datasets as _list_bio_oracle_datasets,
    preview_bio_oracle_point as _preview_bio_oracle_point,
    query_bio_oracle as _query_bio_oracle,
)
from core.canonical_grid import snap_bbox
from core.erddap_cache import cache_get, cache_set
from core.environment_resolver import (
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    detect_column,
    parse_source_coords,
    resolve_source_dataframe,
)
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.public_url import download_url
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _clean_label(value: str) -> str:
    return str(value).lower().replace(".", "_").replace("-", "_").replace(" ", "_")


def _snap_coordinate(value: float, bin_degrees: float) -> float:
    if bin_degrees <= 0:
        return float(value)
    return round(round(float(value) / float(bin_degrees)) * float(bin_degrees), 6)


def _canonical_tile_for(latitude: float, longitude: float, tile_degrees: float = 5.0) -> dict:
    """Return the 5° canonical tile containing the given lat/lon."""
    return snap_bbox(
        {
            "lat_min": float(latitude),
            "lat_max": float(latitude),
            "lon_min": float(longitude),
            "lon_max": float(longitude),
        },
        tile_degrees=tile_degrees,
    )


def _fetch_bio_oracle_bbox(
    *,
    variable: str,
    scenario: str,
    depth_layer: str,
    target_year: int | None,
    tile: dict,
) -> pd.DataFrame:
    """Fetch all Bio-ORACLE grid points within a canonical tile (one HTTP call).

    Returns a DataFrame with columns: time, latitude, longitude, value, plus
    `dataset_id` available via `df.attrs['dataset_id']`. Cached on disk under
    the canonical (tile × variable × scenario × depth × year) key so future
    enrichments touching the same tile cost ~milliseconds.
    """
    var = _resolve_var(variable)
    scen = _resolve_scenario(scenario)
    depth = _resolve_depth(depth_layer)
    cache_key = {
        "tile": tile,
        "variable": var,
        "scenario": scen,
        "depth_layer": depth,
        "target_year": target_year,
    }
    cached = cache_get("bio_oracle_bbox", cache_key)
    if cached is not None:
        return cached

    dataset_id = _find_dataset_id(var, scen, depth)
    griddap_url = f"{_ERDDAP_BASE}/griddap/{dataset_id}"
    query_var = f"{var}_mean"
    time_sel = _time_selector({"target_year": target_year}, scenario=scen)
    url = (
        f"{griddap_url}.csv?{query_var}"
        f"[({time_sel})]"
        f"[({tile['lat_min']:.4f}):1:({tile['lat_max']:.4f})]"
        f"[({tile['lon_min']:.4f}):1:({tile['lon_max']:.4f})]"
    )
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    lines = response.text.splitlines()
    body = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else response.text
    raw = pd.read_csv(io.StringIO(body))
    # Normalize: ERDDAP returns columns like time, latitude, longitude, thetao_mean
    value_col = query_var if query_var in raw.columns else raw.columns[-1]
    result = raw.rename(columns={value_col: "value"}).copy()
    result.attrs["dataset_id"] = dataset_id
    cache_set("bio_oracle_bbox", cache_key, result)
    return result


def _lookup_in_tile(
    tile_df: pd.DataFrame, *, latitude: float, longitude: float
) -> dict:
    """Find the nearest grid point in a cached tile DataFrame.

    Returns {"dataset_id", "time", "value"}. Returns NaN value if the tile is
    empty or all values are masked.
    """
    if tile_df.empty:
        return {
            "dataset_id": tile_df.attrs.get("dataset_id"),
            "time": None,
            "value": None,
        }
    valid = tile_df.dropna(subset=["value"])
    if valid.empty:
        return {
            "dataset_id": tile_df.attrs.get("dataset_id"),
            "time": (
                tile_df["time"].iloc[0] if "time" in tile_df.columns else None
            ),
            "value": None,
        }
    dlat = valid["latitude"].to_numpy() - float(latitude)
    dlon = valid["longitude"].to_numpy() - float(longitude)
    idx = (dlat * dlat + dlon * dlon).argmin()
    nearest = valid.iloc[int(idx)]
    raw_value = nearest["value"]
    try:
        value = round(float(raw_value), 4) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "dataset_id": tile_df.attrs.get("dataset_id"),
        "time": nearest.get("time"),
        "value": value,
    }


def _fetch_bio_oracle_point(
    *,
    latitude: float,
    longitude: float,
    variable: str,
    scenario: str,
    depth_layer: str,
    target_year: int | None,
) -> dict:
    """Fetch a single Bio-ORACLE value at one point.

    Returns {"dataset_id", "time", "value"}.
    """
    preview = _preview_bio_oracle_point(
        {
            "latitude": latitude,
            "longitude": longitude,
            "variable": variable,
            "scenario": scenario,
            "depth_layer": depth_layer,
            "target_year": target_year,
        }
    )
    value_key = preview.get("variable", "")
    rows = preview.get("rows") or []
    first = rows[0] if rows else {}
    raw_value = first.get(value_key)
    try:
        value = round(float(raw_value), 4) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "dataset_id": preview.get("dataset_id"),
        "time": first.get("time"),
        "value": value,
    }


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "Aucun résultat Bio-ORACLE."
    dataframe = pd.DataFrame(rows)
    available_columns = [column for column in columns if column in dataframe.columns]
    if available_columns:
        dataframe = dataframe.loc[:, available_columns]
    return dataframe.to_markdown(index=False)


def make_bio_oracle_tools(thread_id: str) -> list:
    """Create LangChain Bio-ORACLE tools for one thread."""

    def _source_dataframe_with_columns(
        latitude_column: str,
        longitude_column: str,
    ) -> tuple[pd.DataFrame | None, str | None]:
        """Find the current or named source table that has the requested coords."""
        session = _store.get(thread_id)
        current = session.get("df") if session else None
        if (
            isinstance(current, pd.DataFrame)
            and not current.empty
            and latitude_column in current.columns
            and longitude_column in current.columns
        ):
            return current, None

        candidates: list[tuple[str, pd.DataFrame]] = []
        for key in _store.keys(f"{thread_id}:dataset:"):
            named = _store.get(key)
            dataframe = named.get("df") if named else None
            if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
                continue
            if latitude_column in dataframe.columns and longitude_column in dataframe.columns:
                variable_name = (named.get("meta") or {}).get("variable_name") or key.rsplit(":", 1)[-1]
                candidates.append((variable_name, dataframe))

        if not candidates:
            return current if isinstance(current, pd.DataFrame) else None, None

        file_candidates = [
            candidate
            for candidate in candidates
            if str(candidate[0]).startswith("df_file_")
        ]
        variable_name, dataframe = (file_candidates or candidates)[0]
        return dataframe, variable_name

    @tool
    def list_bio_oracle_datasets() -> str:
        """Liste les datasets Bio-ORACLE disponibles dans ERDDAP."""
        try:
            datasets = _list_bio_oracle_datasets()
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"
        if not datasets:
            return "Aucun dataset Bio-ORACLE trouvé."
        return _format_table(datasets, ["dataset_id", "title", "griddap"])

    @tool
    def preview_bio_oracle_point(
        latitude: float,
        longitude: float,
        variable: str,
        scenario: str,
        depth_layer: str,
        target_year: int | None = None,
    ) -> str:
        """Prévisualise un point Bio-ORACLE pour une variable, un scénario et une couche de profondeur."""
        try:
            preview = _preview_bio_oracle_point(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "target_year": target_year,
                }
            )
            return _format_table(preview["rows"], ["time", "latitude", "longitude", variable])
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def query_bio_oracle(
        latitude: float | list[float],
        longitude: float | list[float],
        variable: str,
        scenario: str,
        depth_layer: str,
        target_year: int | None = None,
    ) -> str:
        """Extrait Bio-ORACLE pour un ou plusieurs points et écrit un TSV téléchargeable.

        Pour UN point, passe `latitude` et `longitude` en `float`.
        Pour PLUSIEURS stations, passe `latitude` et `longitude` en
        `list[float]` de même longueur — le tool fait un appel ERDDAP par
        point unique et concatène les résultats dans `df_bio_oracle`.

        Pour enrichir directement un fichier zooplancton chargé avec une valeur
        par station, préfère `couple_zooplankton_bio_oracle` qui lit les
        coordonnées depuis la table en session.
        """
        try:
            lat_is_list = isinstance(latitude, list)
            lon_is_list = isinstance(longitude, list)
            if lat_is_list != lon_is_list:
                return (
                    "latitude et longitude doivent être tous deux des nombres "
                    "ou tous deux des listes."
                )
            if lat_is_list:
                if len(latitude) != len(longitude):
                    return (
                        f"latitude ({len(latitude)}) et longitude "
                        f"({len(longitude)}) doivent avoir la même longueur."
                    )
                if not latitude:
                    return "Liste de points vide."
                lat_list = [float(value) for value in latitude]
                lon_list = [float(value) for value in longitude]
            else:
                lat_list = [float(latitude)]
                lon_list = [float(longitude)]
            multi = len(lat_list) > 1

            per_point_frames: list[pd.DataFrame] = []
            per_point_names: list[str] = []
            per_point_dataset_ids: list[str] = []
            last_result: dict | None = None
            for lat, lon in zip(lat_list, lon_list):
                file_id = uuid.uuid4().hex
                output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
                result = _query_bio_oracle(
                    {
                        "latitude": lat,
                        "longitude": lon,
                        "variable": variable,
                        "scenario": scenario,
                        "depth_layer": depth_layer,
                        "target_year": target_year,
                    },
                    output_path=output_path,
                )
                last_result = result
                dataframe = pd.read_csv(output_path, sep="\t")
                variable_name = dataset_variable_name(
                    "bio_oracle",
                    variable,
                    scenario,
                    depth_layer,
                    lat,
                    lon,
                )
                store_dataset(
                    _store,
                    thread_id,
                    dataframe,
                    variable_name=variable_name,
                    meta={
                        "source": f"bio_oracle:{result['dataset_id']}",
                        "dataset_id": result["dataset_id"],
                        "variable": variable,
                        "scenario": scenario,
                        "depth_layer": depth_layer,
                        "target_year": target_year,
                        "latitude": lat,
                        "longitude": lon,
                        "n_rows": len(dataframe),
                    },
                    latest_alias=None if multi else "bio_oracle",
                )
                per_point_frames.append(dataframe)
                per_point_names.append(variable_name)
                per_point_dataset_ids.append(result["dataset_id"])

            if not multi:
                return (
                    f"Bio-ORACLE chargé — {last_result['row_count']} lignes.\n"
                    f"Données disponibles dans `{per_point_names[0]}` et `df_bio_oracle`.\n"
                    f"Appelle run_pandas directement pour analyser.\n"
                    f"Télécharger : {last_result['download_url']}"
                )

            merged = pd.concat(per_point_frames, ignore_index=True)
            merged_id = uuid.uuid4().hex
            merged_path = _DOWNLOADS_DIR / f"{merged_id}.tsv"
            merged.to_csv(merged_path, sep="\t", index=False)
            merged_name = dataset_variable_name(
                "bio_oracle_multi",
                variable,
                scenario,
                depth_layer,
                len(lat_list),
            )
            store_dataset(
                _store,
                thread_id,
                merged,
                variable_name=merged_name,
                meta={
                    "source": f"bio_oracle:multipoint:{variable}:{scenario}:{depth_layer}",
                    "dataset_ids": per_point_dataset_ids,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "target_year": target_year,
                    "n_points": len(lat_list),
                    "n_rows": len(merged),
                },
                latest_alias="bio_oracle",
            )
            return (
                f"Bio-ORACLE chargé — {len(merged)} lignes pour {len(lat_list)} points.\n"
                f"Données disponibles dans `{merged_name}` et `df_bio_oracle`.\n"
                f"Datasets par point : {', '.join(per_point_names)}.\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {download_url(merged_path.name)}"
            )
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def couple_zooplankton_bio_oracle(
        latitude_column: str,
        longitude_column: str,
        scenario: str,
        depth_layer: str,
        variable: str | None = None,
        variables: list[str] | None = None,
        station_column: str | None = None,
        sample_column: str | None = None,
        top_n_stations: int | None = None,
        scenarios: list[str] | None = None,
        target_year: int | None = None,
    ) -> str:
        """Add Bio-ORACLE values per row/station of the loaded lat/lon table.

        Per-station enrichment, not zone aggregates. Pass column names, not row
        values. Supports top-N station reduction, multiple `scenarios`, SSP
        `target_year` (baseline stays historical). Pass `variables=[...]` to
        fetch several variables in one call (one column per variable × scenario,
        named `<variable>_<scenario>`); `variable` is the legacy single-variable
        path. Output preserves source rows + adds value, time, dataset columns.
        """
        try:
            source, fallback_name = _source_dataframe_with_columns(
                latitude_column,
                longitude_column,
            )
            if not isinstance(source, pd.DataFrame) or source.empty:
                return "Aucune table chargée à coupler."
            missing_columns = [
                column
                for column in (latitude_column, longitude_column)
                if column not in source.columns
            ]
            if missing_columns:
                return (
                    "Colonnes absentes de la table chargée : "
                    + ", ".join(missing_columns)
                )

            variable_values = list(variables) if variables else (
                [variable] if variable else []
            )
            if not variable_values:
                return "Aucune variable Bio-ORACLE fournie (`variable` ou `variables`)."

            scenario_values = list(scenarios or [scenario])
            if not scenario_values:
                return "Aucun scénario Bio-ORACLE fourni."

            # Garde-fou : un scénario SSP* est décennal (2020, 2030, ..., 2090).
            # Sans target_year explicite, ERDDAP renvoie la dernière décennie
            # (2090) — rarement ce que l'utilisateur veut, et trompeur quand la
            # table contient des dates terrain (UVP/zooplankton). On refuse et
            # on demande l'année. baseline reste OK (single climatology).
            if target_year is None:
                ssp_scenarios = [
                    s for s in scenario_values
                    if str(s).lower().replace("-", "").replace(".", "").startswith("ssp")
                ]
                if ssp_scenarios:
                    return (
                        "TARGET_YEAR_REQUIRED: les datasets Bio-ORACLE SSP "
                        f"({', '.join(ssp_scenarios)}) sont décennaux. "
                        "Choisis une décennie cible parmi : "
                        "2020, 2030, 2040, 2050, 2060, 2070, 2080, 2090 "
                        "(8 tranches de 10 ans, valeur = moyenne climatique sur "
                        "la décennie). Horizons standards : 2050 (mid-century), "
                        "2070 (late-century), 2090 (end-of-century). "
                        "Rappelle le tool avec `target_year=<année>`."
                    )

            if station_column or top_n_stations is not None:
                if not station_column:
                    return "`station_column` est requis avec `top_n_stations`."
                missing_station_columns = [
                    column
                    for column in (station_column, latitude_column, longitude_column)
                    if column not in source.columns
                ]
                if sample_column and sample_column not in source.columns:
                    missing_station_columns.append(sample_column)
                if missing_station_columns:
                    return (
                        "Colonnes absentes de la table source : "
                        + ", ".join(missing_station_columns)
                    )

                count_column = sample_column or station_column
                station_source_columns = list(
                    dict.fromkeys(
                        [
                            station_column,
                            count_column,
                            latitude_column,
                            longitude_column,
                        ]
                    )
                )
                grouped = (
                    source[station_source_columns]
                    .dropna(subset=[station_column, latitude_column, longitude_column])
                    .drop_duplicates()
                    .groupby(station_column, as_index=False)
                    .agg(
                        n_samples=(count_column, "count"),
                        **{
                            latitude_column: (latitude_column, "first"),
                            longitude_column: (longitude_column, "first"),
                        },
                    )
                    .sort_values(["n_samples", station_column], ascending=[False, True])
                    .reset_index(drop=True)
                )
                if top_n_stations is not None:
                    grouped = grouped.head(int(top_n_stations)).reset_index(drop=True)
                dataframe = grouped
            else:
                dataframe = source.copy(deep=True)

            # Dédup : un appel ERDDAP par (lat, lon, variable, scenario, depth_layer).
            # Deux lignes au même point recevront la même valeur via lookup.
            cache: dict[tuple, dict] = {}
            single_scenario = len(scenario_values) == 1
            single_variable = len(variable_values) == 1
            for scenario_value in scenario_values:
                for variable_value in variable_values:
                    for latitude, longitude in dataframe[
                        [latitude_column, longitude_column]
                    ].itertuples(index=False, name=None):
                        key = (
                            latitude,
                            longitude,
                            variable_value,
                            scenario_value,
                            depth_layer,
                            target_year,
                        )
                        if key not in cache:
                            preview = _preview_bio_oracle_point(
                                {
                                    "latitude": latitude,
                                    "longitude": longitude,
                                    "variable": variable_value,
                                    "scenario": scenario_value,
                                    "depth_layer": depth_layer,
                                    "target_year": target_year,
                                }
                            )
                            val_key = preview.get("variable", "")
                            preview_rows = preview.get("rows") or []
                            first_row = preview_rows[0] if preview_rows else {}
                            raw_value = first_row.get(val_key) if preview_rows else None
                            try:
                                value = round(float(raw_value), 4) if raw_value is not None else None
                            except (TypeError, ValueError):
                                value = None
                            cache[key] = {
                                "value": value,
                                "dataset_id": preview.get("dataset_id"),
                                "time": first_row.get("time"),
                            }

                    values = []
                    dataset_ids = []
                    times = []
                    for latitude, longitude in dataframe[
                        [latitude_column, longitude_column]
                    ].itertuples(index=False, name=None):
                        key = (
                            latitude,
                            longitude,
                            variable_value,
                            scenario_value,
                            depth_layer,
                            target_year,
                        )
                        cached = cache[key]
                        values.append(cached["value"])
                        dataset_ids.append(cached["dataset_id"])
                        times.append(cached["time"])

                    scenario_clean = (
                        str(scenario_value).lower().replace(".", "_").replace("-", "_")
                    )
                    # Include target year in the column name for future scenarios so
                    # the reader cannot misinterpret a decadal projection as
                    # contemporaneous with another date column in the table.
                    year_suffix = (
                        f"_{int(target_year):04d}"
                        if target_year is not None
                        and scenario_clean != "baseline"
                        else ""
                    )
                    value_col = f"{variable_value}_{scenario_clean}{year_suffix}"
                    dataframe[value_col] = values
                    # Traceability columns: shared when there's only one slot,
                    # otherwise per-(variable,scenario) so columns don't collide.
                    suffix_parts = []
                    if not single_variable:
                        suffix_parts.append(variable_value)
                    if not single_scenario:
                        suffix_parts.append(scenario_clean)
                    suffix = ("_" + "_".join(suffix_parts)) if suffix_parts else ""
                    dataframe[f"time{suffix}"] = times
                    dataframe[f"dataset_id{suffix}"] = dataset_ids

            output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
            dataframe.to_csv(output_path, sep="\t", index=False)
            query_fingerprint = dataframe[
                [latitude_column, longitude_column]
            ].to_json(orient="records")
            query_id = hashlib.sha256(
                (
                    f"{query_fingerprint}|{variable_values}|{scenario_values}|{depth_layer}|{target_year}"
                ).encode("utf-8")
            ).hexdigest()[:12]
            variable_name = dataset_variable_name("bio_oracle_coupling", query_id)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={
                    "source": "bio_oracle_coupling",
                    "query_id": query_id,
                    "variables": variable_values,
                    "scenarios": scenario_values,
                    "target_year": target_year,
                    "n_rows": len(dataframe),
                },
            )
            preview_md = dataframe.head(20).to_markdown(index=False)
            source_note = (
                f"Source utilisée : `{fallback_name}`.\n"
                if fallback_name
                else ""
            )
            return (
                f"Couplage Bio-ORACLE chargé — {len(dataframe)} lignes.\n"
                f"{source_note}"
                f"Données disponibles dans `{variable_name}`.\n"
                f"Aperçu (20 premières lignes) :\n\n{preview_md}\n\n"
                f"Télécharger : {download_url(output_path.name)}"
            )
        except Exception as exc:
            return f"Erreur lors du couplage Bio-ORACLE : {exc}"

    @tool
    def query_bio_oracle_zones(
        zones: list[str],
        variable: str,
        scenario: str,
        depth_layer: str = "surface",
        target_year: int | None = None,
    ) -> str:
        """Return one Bio-ORACLE value per named zone.

        Use only for zone-level questions ("compare les zones", temperature in
        Hawke Channel, etc.). Do not use for per-station enrichment of a loaded
        lat/lon table; use `couple_zooplankton_bio_oracle` for that. Variables
        are friendly names: temperature, salinity, oxygen, chlorophyll, nitrate.
        Scenarios: SSP5-8.5, SSP1-2.6, SSP2-4.5, baseline. Optional
        `target_year` applies to SSP datasets.
        """
        from tools.geo_tools import get_zone_info

        # Garde-fou : si une session contient déjà un DataFrame multi-lignes
        # avec lat/lon, signaler que le couple_zooplankton_bio_oracle est plus
        # approprié pour un enrichissement par station.
        per_station_warning = ""
        try:
            session = _store.get(thread_id)
            df_session = session.get("df") if session else None
            if isinstance(df_session, pd.DataFrame) and len(df_session) > 1:
                cols_lower = {str(c).lower(): c for c in df_session.columns}
                has_lat = any(c in cols_lower for c in ("latitude", "lat"))
                has_lon = any(c in cols_lower for c in ("longitude", "lon"))
                if has_lat and has_lon:
                    per_station_warning = (
                        f"⚠ Une table de {len(df_session)} lignes avec latitude/longitude "
                        "est active en session. `query_bio_oracle_zones` renvoie UNE valeur "
                        "agrégée par zone — ne pas réutiliser cette valeur unique pour chaque "
                        "station. Pour des valeurs par station, appelle "
                        "`couple_zooplankton_bio_oracle` avec les noms des colonnes "
                        "latitude/longitude de la table chargée.\n\n"
                    )
        except Exception:
            pass

        rows_out = []
        errors = []
        for zone_name in zones:
            zf = get_zone_info.invoke({"zone_name": zone_name})
            if "error" in zf:
                errors.append(f"{zone_name}: {zf['error']}")
                continue
            bbox = zf["bbox"]
            lat_c = (bbox["south"] + bbox["north"]) / 2
            lon_c = (bbox["west"] + bbox["east"]) / 2
            try:
                preview = _preview_bio_oracle_point({
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "latitude": lat_c,
                    "longitude": lon_c,
                    "target_year": target_year,
                })
                val_key = preview.get("variable", "")
                first_row = preview["rows"][0] if preview.get("rows") else {}
                val = first_row.get(val_key) if first_row else None
                rows_out.append({
                    "zone": zf["canonical"],
                    "lat_centre": round(lat_c, 2),
                    "lon_centre": round(lon_c, 2),
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "time": first_row.get("time"),
                    "dataset": preview["dataset_id"],
                    f"{variable}_projected": round(float(val), 4) if val is not None else None,
                })
            except Exception as exc:
                errors.append(f"{zone_name}: {exc}")

        if not rows_out:
            return "Aucune valeur extraite. Erreurs : " + "; ".join(errors)

        df_out = pd.DataFrame(rows_out)
        variable_name = dataset_variable_name(
            "bio_oracle_zones", variable, scenario, depth_layer
        )
        dataset_meta = {
            "source": "bio_oracle_zones",
            "variable": variable,
            "scenario": scenario,
            "depth_layer": depth_layer,
            "target_year": target_year,
            "variable_name": variable_name,
        }
        _store.set(f"{thread_id}:dataset:{variable_name}", df_out, dataset_meta)
        out = (
            f"Données disponibles dans `{variable_name}`.\n\n"
            + df_out.to_markdown(index=False)
        )
        if errors:
            out += "\n\nAvertissements : " + "; ".join(errors)
        return per_station_warning + out

    @tool
    def enrich_with_bio_oracle(
        variables: list[str],
        scenarios: list[str],
        depth_layer: str = "surface",
        target_year: int | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        source_variable: str | None = None,
        coordinate_bin_degrees: float = 1 / 12,
        max_unique_queries: int = 1000,
        confirmed: bool = False,
        max_workers: int = 8,
    ) -> str:
        """Enrichit la table chargée avec Bio-ORACLE par lat/lon.

        Auto-détecte les colonnes latitude/longitude. Pour chaque (variable,
        scenario), interroge Bio-ORACLE au point exact en parallèle, puis
        recolle une valeur par ligne. Si plusieurs fichiers sont en session,
        passe `source_variable` (par exemple `df_file_filet_arctic_2018`) pour
        cibler un dataset précis au lieu du df actif.
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
        if lat_col is None or lon_col is None:
            missing = [name for name, value in (("latitude", lat_col), ("longitude", lon_col)) if value is None]
            return (
                "Enrichissement Bio-ORACLE impossible : colonnes manquantes — "
                f"{', '.join(missing)}. Préciser via `latitude_column`, `longitude_column`."
            )

        coords = parse_source_coords(source, lat_col=lat_col, lon_col=lon_col)
        if coords.empty_groups:
            return (
                "Enrichissement Bio-ORACLE impossible : colonnes "
                f"{', '.join(coords.empty_groups)} entièrement vides dans la table "
                "chargée. Aucune coordonnée exploitable."
            )

        enriched = source.copy(deep=True)
        n_rows = len(enriched)
        row_query_coords: list[tuple[float, float] | None] = []
        for lat, lon in enriched[[lat_col, lon_col]].itertuples(index=False, name=None):
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                row_query_coords.append(None)
                continue
            coords_valid = (
                not pd.isna(lat_f)
                and not pd.isna(lon_f)
                and -90.0 <= lat_f <= 90.0
                and -180.0 <= lon_f <= 180.0
            )
            if not coords_valid:
                row_query_coords.append(None)
                continue
            row_query_coords.append(
                (
                    _snap_coordinate(lat_f, float(coordinate_bin_degrees)),
                    _snap_coordinate(lon_f, float(coordinate_bin_degrees)),
                )
            )
        unique_query_keys = {
            (coords[0], coords[1], variable, scenario, depth_layer, target_year)
            for coords in row_query_coords
            if coords is not None
            for variable in variables
            for scenario in scenarios
        }
        unique_query_count = len(unique_query_keys)
        if unique_query_count > int(max_unique_queries) and not confirmed:
            return (
                f"Confirmation required: {unique_query_count} unique Bio-ORACLE "
                "queries would be sent "
                f"({len(variables)} variable(s) × {len(scenarios)} scenario(s), "
                f"coordinate_bin_degrees={float(coordinate_bin_degrees):g}). "
                "Ask the user for confirmation, then call again with "
                "`confirmed=true`, or reduce variables/scenarios/source rows."
            )

        # Build canonical tile fetch jobs: one HTTP per (tile × var × scenario)
        tile_jobs: dict[tuple, dict] = {}
        point_to_tile_key: dict[tuple, tuple] = {}
        for key in unique_query_keys:
            lat_f, lon_f, variable, scenario, layer, year = key
            tile = _canonical_tile_for(lat_f, lon_f)
            tile_key = (
                tile["lat_min"], tile["lat_max"],
                tile["lon_min"], tile["lon_max"],
                variable, scenario, layer, year,
            )
            point_to_tile_key[key] = tile_key
            tile_jobs.setdefault(tile_key, {
                "tile": tile,
                "variable": variable,
                "scenario": scenario,
                "depth_layer": layer,
                "target_year": year,
            })

        def _fetch_tile(args: tuple) -> tuple[tuple, pd.DataFrame | None]:
            tile_key, payload = args
            try:
                df = _fetch_bio_oracle_bbox(**payload)
                return tile_key, df
            except Exception:
                return tile_key, None

        tile_dfs: dict[tuple, pd.DataFrame | None] = {}
        job_items = list(tile_jobs.items())
        effective_workers = max(1, min(int(max_workers), len(job_items) or 1))
        if effective_workers == 1 or len(job_items) <= 1:
            for item in job_items:
                tk, df = _fetch_tile(item)
                tile_dfs[tk] = df
        else:
            with ThreadPoolExecutor(max_workers=effective_workers) as pool:
                for tk, df in pool.map(_fetch_tile, job_items):
                    tile_dfs[tk] = df

        cache: dict[tuple, dict] = {}
        for key in unique_query_keys:
            lat_f, lon_f, *_ = key
            tile_key = point_to_tile_key[key]
            tile_df = tile_dfs.get(tile_key)
            if tile_df is None:
                cache[key] = {"value": None, "dataset_id": None, "time": None}
            else:
                cache[key] = _lookup_in_tile(
                    tile_df, latitude=lat_f, longitude=lon_f
                )

        row_has_value = [False] * n_rows
        for variable in variables:
            for scenario in scenarios:
                values: list[object] = []
                dataset_ids: list[object] = []
                times: list[object] = []
                for position, query_coords in enumerate(row_query_coords):
                    if query_coords is None:
                        values.append(pd.NA)
                        dataset_ids.append(pd.NA)
                        times.append(pd.NA)
                        continue
                    lat_f, lon_f = query_coords
                    key = (
                        lat_f,
                        lon_f,
                        variable,
                        scenario,
                        depth_layer,
                        target_year,
                    )
                    fetched = cache[key]
                    value = fetched["value"]
                    is_real_value = value is not None and not pd.isna(value)
                    values.append(value if is_real_value else pd.NA)
                    dataset_ids.append(fetched.get("dataset_id") or pd.NA)
                    times.append(fetched.get("time") or pd.NA)
                    if is_real_value:
                        row_has_value[position] = True
                stub = f"bio_oracle_{_clean_label(variable)}_{_clean_label(scenario)}"
                enriched[stub] = values
                enriched[f"{stub}_dataset_id"] = dataset_ids
                enriched[f"{stub}_time"] = times

        statuses = [
            "matched" if has_value else "no_value" for has_value in row_has_value
        ]

        enriched["bio_oracle_match_status"] = statuses
        variable_name = dataset_variable_name(
            "bio_oracle_enriched", uuid.uuid4().hex[:12]
        )
        store_dataset(
            _store,
            thread_id,
            enriched,
            variable_name=variable_name,
            meta={"source": "bio_oracle_enrichment", "n_rows": len(enriched)},
        )
        n_matched = statuses.count("matched")
        n_no_value = statuses.count("no_value")
        method_lines = [
            "Méthode :",
            (
                f"- Colonnes source détectées : latitude={lat_col!r}, "
                f"longitude={lon_col!r}"
            ),
            (
                "- Datasets Bio-ORACLE : un par (variable × scénario), "
                f"depth_layer={depth_layer!r}, target_year={target_year!r}"
            ),
            f"- Variables : {', '.join(variables)}",
            f"- Scénarios : {', '.join(scenarios)}",
            (
                f"- Dédup par point unique sur grille "
                f"{float(coordinate_bin_degrees):g}° pour économiser les appels ERDDAP"
            ),
            (
                f"- Requêtes Bio-ORACLE uniques : {unique_query_count} "
                f"(max_unique_queries={int(max_unique_queries)}, "
                f"confirmed={bool(confirmed)})"
            ),
            f"- Statuts : matched={n_matched}, no_value={n_no_value}",
        ]
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) sans valeur — point hors "
                "couverture de la grille Bio-ORACLE (souvent terre ou bord)."
            )
        return (
            f"Enrichissement Bio-ORACLE — {len(enriched)} ligne(s), "
            f"{n_matched} matchée(s).\n"
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines)
        )

    return [list_bio_oracle_datasets, preview_bio_oracle_point, query_bio_oracle,
            couple_zooplankton_bio_oracle, query_bio_oracle_zones,
            enrich_with_bio_oracle]
