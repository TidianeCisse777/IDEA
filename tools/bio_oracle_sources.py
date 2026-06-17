"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.bio_oracle_client import (
    describe_bio_oracle_source,
    list_bio_oracle_datasets as _list_bio_oracle_datasets,
    preview_bio_oracle_point as _preview_bio_oracle_point,
    query_bio_oracle as _query_bio_oracle,
)
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.public_url import download_url
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


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
        variable: str,
        scenario: str,
        depth_layer: str,
        station_column: str | None = None,
        sample_column: str | None = None,
        top_n_stations: int | None = None,
        scenarios: list[str] | None = None,
        target_year: int | None = None,
    ) -> str:
        """Enrichit chaque ligne d'observations zooplancton avec UNE valeur Bio-ORACLE
        propre à son point géographique (lat/lon).

        Utilise CE tool — et pas `query_bio_oracle_zones` — dès que l'utilisateur
        veut une valeur Bio-ORACLE **par station** d'un fichier zooplancton chargé
        (fichier avec `latitude` / `longitude` par ligne). Le tool fait UN appel
        Bio-ORACLE par point unique et conserve toutes les colonnes du fichier.
        Capacités :
        - enrichir chaque ligne ou chaque station avec une valeur Bio-ORACLE
          extraite à ses propres coordonnées latitude/longitude ;
        - construire directement les "top N stations" avec `station_column`,
          `sample_column` et `top_n_stations` ;
        - comparer plusieurs scénarios en une fois via `scenarios` ;
        - appliquer un horizon futur explicite via `target_year`, par exemple
          2050, aux scénarios SSP. Les datasets `baseline` sont historiques :
          le client ignore automatiquement `target_year` pour baseline afin
          d'éviter une requête impossible comme baseline 2050.
        Le résultat inclut les colonnes de valeur, `time` / `time_<scenario>`,
        et `dataset_id` / `dataset_id_<scenario>` pour tracer la provenance.

        Passe uniquement les noms des colonnes latitude/longitude du fichier
        chargé ainsi que la variable, le scénario et la couche demandés. Le tool
        lit lui-même les lignes réelles de la session ; ne retranscris jamais les
        observations dans les arguments.

        Pour une demande du type "les mêmes stations", "top 10 stations" ou
        "par station", passe aussi `station_column`, `sample_column` et
        `top_n_stations`. Le tool construit alors lui-même la table stationnaire
        à partir de la source chargée avant de faire les appels Bio-ORACLE.
        Pour comparer plusieurs scénarios, passe `scenarios`; le résultat aura
        une colonne par scénario.
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

            scenario_values = list(scenarios or [scenario])
            if not scenario_values:
                return "Aucun scénario Bio-ORACLE fourni."

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
            for scenario_value in scenario_values:
                for latitude, longitude in dataframe[
                    [latitude_column, longitude_column]
                ].itertuples(index=False, name=None):
                    key = (
                        latitude,
                        longitude,
                        variable,
                        scenario_value,
                        depth_layer,
                        target_year,
                    )
                    if key not in cache:
                        preview = _preview_bio_oracle_point(
                            {
                                "latitude": latitude,
                                "longitude": longitude,
                                "variable": variable,
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
                        variable,
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
                value_col = f"{variable}_{scenario_clean}"
                dataframe[value_col] = values
                time_col = (
                    "time"
                    if len(scenario_values) == 1
                    else f"time_{scenario_clean}"
                )
                dataframe[time_col] = times
                dataset_col = (
                    "dataset_id"
                    if len(scenario_values) == 1
                    else f"dataset_id_{scenario_clean}"
                )
                dataframe[dataset_col] = dataset_ids

            output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
            dataframe.to_csv(output_path, sep="\t", index=False)
            query_fingerprint = dataframe[
                [latitude_column, longitude_column]
            ].to_json(orient="records")
            query_id = hashlib.sha256(
                (
                    f"{query_fingerprint}|{variable}|{scenario_values}|{depth_layer}|{target_year}"
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
        """Extract Bio-ORACLE projected values for one or more named geographic zones.

        Use this tool ONLY when the user asks for Bio-ORACLE data **aggregated
        by zone name** (e.g. "température Bio-ORACLE dans Hawke Channel et mer
        du Labrador", "compare les zones"). The tool returns ONE row per zone,
        sampled at the zone's geographic centre.

        DO NOT use this tool to enrich a loaded zooplankton / sampling file
        with per-station environmental values — even if all stations happen to
        fall in one zone. For that case, use `couple_zooplankton_bio_oracle`
        instead: it calls Bio-ORACLE once per row (lat/lon) so two stations at
        different coordinates receive different values.

        Parameters
        ----------
        zones : list of zone names — any name accepted by get_zone_info:
            "Hawke Channel", "Mer du Labrador", "Baie d'Hudson",
            "Détroit d'Hudson", "Baie d'Ungava", "Baie de Baffin",
            "Mer de Beaufort", "Arctique", "Nunavik", "Baie de James"
        variable : one of: "temperature", "salinity", "oxygen",
                   "chlorophyll", "nitrate"  — do NOT use ERDDAP internal names
        scenario : "SSP5-8.5", "SSP1-2.6", "SSP2-4.5", or "baseline"
        depth_layer : "surface" (default), "mean", "max", or "min"
        target_year : optional horizon such as 2050. If omitted, ERDDAP's
                      last available time slice is used.
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

    return [list_bio_oracle_datasets, preview_bio_oracle_point, query_bio_oracle,
            couple_zooplankton_bio_oracle, query_bio_oracle_zones]
