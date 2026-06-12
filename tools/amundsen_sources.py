"""LangChain tools for Amundsen CTD."""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.amundsen_ctd_client import (
    list_amundsen_datasets as _list_amundsen_datasets,
    preview_amundsen_profile as _preview_amundsen_profile,
    query_amundsen_ctd as _query_amundsen_ctd,
)
from tools.dataset_registry import dataset_variable_name, store_dataset
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

    return [list_amundsen_datasets, preview_amundsen_profile, query_amundsen_ctd]
