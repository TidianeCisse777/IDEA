"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import json
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
        datasets = _list_bio_oracle_datasets()
        if not datasets:
            return "Aucun dataset Bio-ORACLE trouvé."
        return _format_table(datasets, ["dataset_id", "title", "griddap"])

    @tool
    def preview_bio_oracle_point(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Prévisualise un point Bio-ORACLE pour une variable, un scénario et une couche de profondeur."""
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

    @tool
    def query_bio_oracle(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Extrait Bio-ORACLE pour un point et écrit un TSV téléchargeable."""
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
        _store.set(thread_id, dataframe, {"source": f"bio_oracle:{scenario}", "n_rows": len(dataframe)})
        return (
            f"Bio-ORACLE chargé — {result['row_count']} lignes.\n"
            f"Télécharger : {result['download_url']}"
        )

    @tool
    def couple_zooplankton_bio_oracle(rows_json: str) -> str:
        """Couple des lignes zooplancton avec Bio-ORACLE à partir d'un JSON de lignes normalisées."""
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
        pd.DataFrame(coupled_rows).to_csv(output_path, sep="\t", index=False)
        _store.set(thread_id, pd.DataFrame(coupled_rows), {"source": "bio_oracle_coupling", "n_rows": len(coupled_rows)})
        return (
            f"Couplage Bio-ORACLE chargé — {len(coupled_rows)} lignes.\n"
            f"Télécharger : {download_url(output_path.name)}"
        )

    return [list_bio_oracle_datasets, preview_bio_oracle_point, query_bio_oracle, couple_zooplankton_bio_oracle]
