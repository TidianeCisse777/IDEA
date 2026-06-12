"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import json
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
    def preview_bio_oracle_point(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Prévisualise un point Bio-ORACLE pour une variable, un scénario et une couche de profondeur."""
        try:
            preview = _preview_bio_oracle_point(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                }
            )
            return _format_table(preview["rows"], ["time", "latitude", "longitude", variable])
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def query_bio_oracle(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Extrait Bio-ORACLE pour un point et écrit un TSV téléchargeable."""
        try:
            file_id = uuid.uuid4().hex
            output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
            result = _query_bio_oracle(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                },
                output_path=output_path,
            )
            dataframe = pd.read_csv(output_path, sep="\t")
            variable_name = dataset_variable_name(
                "bio_oracle",
                variable,
                scenario,
                depth_layer,
                latitude,
                longitude,
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
                    "latitude": latitude,
                    "longitude": longitude,
                    "n_rows": len(dataframe),
                },
                latest_alias="bio_oracle",
            )
            return (
                f"Bio-ORACLE chargé — {result['row_count']} lignes.\n"
                f"Données disponibles dans `{variable_name}` et `df_bio_oracle`.\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {result['download_url']}"
            )
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def couple_zooplankton_bio_oracle(rows_json: str) -> str:
        """Couple des lignes zooplancton avec Bio-ORACLE à partir d'un JSON de lignes normalisées."""
        try:
            rows = json.loads(rows_json)
            if not isinstance(rows, list) or not rows:
                return "Aucune ligne à coupler."

            coupled_rows = []
            for row in rows:
                result = _query_bio_oracle(
                    {
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "variable": row["variable"],
                        "scenario": row["scenario"],
                        "depth_layer": row["depth_layer"],
                    },
                    output_path=_DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv",
                )
                coupled_rows.append(
                    {
                        **row,
                        "dataset_id": result["dataset_id"],
                        "download_url": result["download_url"],
                    }
                )

            output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
            dataframe = pd.DataFrame(coupled_rows)
            dataframe.to_csv(output_path, sep="\t", index=False)
            query_id = hashlib.sha256(rows_json.encode("utf-8")).hexdigest()[:12]
            variable_name = dataset_variable_name("bio_oracle_coupling", query_id)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={"source": "bio_oracle_coupling", "query_id": query_id, "n_rows": len(coupled_rows)},
            )
            return (
                f"Couplage Bio-ORACLE chargé — {len(coupled_rows)} lignes.\n"
                f"Données disponibles dans `{variable_name}`.\n"
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
    ) -> str:
        """Extract Bio-ORACLE projected values for one or more named geographic zones.

        Use this tool whenever the user asks for Bio-ORACLE data by zone name
        (e.g. "température Bio-ORACLE dans Hawke Channel et mer du Labrador",
        "projection SSP5-8.5 par zone", "compare les zones").

        Each zone is sampled at its geographic centre. Results are returned as a
        markdown table — one row per zone — ready to compare with CTD observations.

        Parameters
        ----------
        zones : list of zone names — any name accepted by get_zone_filter:
            "Hawke Channel", "Mer du Labrador", "Baie d'Hudson",
            "Détroit d'Hudson", "Baie d'Ungava", "Baie de Baffin",
            "Mer de Beaufort", "Arctique", "Nunavik", "Baie de James"
        variable : one of: "temperature", "salinity", "oxygen",
                   "chlorophyll", "nitrate"  — do NOT use ERDDAP internal names
        scenario : "SSP5-8.5", "SSP1-2.6", "SSP2-4.5", or "baseline"
        depth_layer : "surface" (default), "mean", "max", or "min"
        """
        from tools.geo_tools import get_zone_filter

        rows_out = []
        errors = []
        for zone_name in zones:
            zf = get_zone_filter.invoke({"zone_name": zone_name})
            if "error" in zf:
                errors.append(f"{zone_name}: {zf['error']}")
                continue
            lat_c = (zf["lat_min"] + zf["lat_max"]) / 2
            lon_c = (zf["lon_min"] + zf["lon_max"]) / 2
            try:
                preview = _preview_bio_oracle_point({
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "latitude": lat_c,
                    "longitude": lon_c,
                })
                val_key = preview.get("variable", "")
                val = preview["rows"][0].get(val_key) if preview.get("rows") else None
                rows_out.append({
                    "zone": zf["zone"],
                    "lat_centre": round(lat_c, 2),
                    "lon_centre": round(lon_c, 2),
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
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
        store_dataset(
            _store, thread_id, df_out,
            variable_name=variable_name,
            meta={"source": "bio_oracle_zones", "variable": variable,
                  "scenario": scenario, "depth_layer": depth_layer},
            latest_alias="bio_oracle",
        )
        out = df_out.to_markdown(index=False)
        if errors:
            out += "\n\nAvertissements : " + "; ".join(errors)
        return out

    return [list_bio_oracle_datasets, preview_bio_oracle_point, query_bio_oracle,
            couple_zooplankton_bio_oracle, query_bio_oracle_zones]
