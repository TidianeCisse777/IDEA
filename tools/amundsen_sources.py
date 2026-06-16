"""LangChain tools for Amundsen CTD."""
from __future__ import annotations

import uuid
import hashlib
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

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

    def _source_dataframe() -> pd.DataFrame | None:
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

    return [
        list_amundsen_datasets,
        preview_amundsen_profile,
        query_amundsen_ctd,
        enrich_loaded_table_with_amundsen_ctd,
    ]
