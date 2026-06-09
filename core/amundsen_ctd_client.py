"""Shared Amundsen CTD helpers."""
from __future__ import annotations

import io

import pandas as pd
import requests

from tools.public_url import download_url


def list_amundsen_datasets() -> list[dict]:
    """Return the Amundsen CTD datasets discovered from ERDDAP."""
    response = requests.get(
        "https://erddap.amundsenscience.com/erddap/search/index.json",
        params={"searchFor": "amundsen ctd", "itemsPerPage": 200},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json() or {}
    table = payload.get("table") or {}
    columns = table.get("columnNames") or []
    rows = table.get("rows") or []
    normalized = []
    for row in rows:
        record = dict(zip(columns, row))
        dataset_id = record.get("Dataset ID") or record.get("Dataset_ID")
        if not dataset_id:
            continue
        normalized.append(
            {
                "dataset_id": str(dataset_id),
                "title": str(record.get("Title") or record.get("title") or ""),
                "griddap": str(record.get("griddap") or ""),
            }
        )
    return normalized


def preview_amundsen_profile(parameters: dict) -> dict:
    """Return a small raw preview for one Amundsen CTD profile."""
    station = parameters.get("station")
    cast_number = parameters.get("cast_number")
    datasets = list_amundsen_datasets()
    chosen = datasets[0] if datasets else None
    if chosen is None:
        raise RuntimeError("No Amundsen CTD dataset matched the request")

    response = requests.get(f"{chosen['griddap']}.csv", timeout=30)
    response.raise_for_status()
    dataframe = pd.read_csv(io.StringIO(response.text))

    if "Pres" in dataframe.columns:
        dataframe["depth"] = dataframe["Pres"]
    if "station" in dataframe.columns:
        dataframe["station_id"] = dataframe["station"]
    elif station is not None:
        dataframe["station_id"] = station
    if "cast_number" in dataframe.columns:
        dataframe["cast_id"] = dataframe["cast_number"]
    elif cast_number is not None:
        dataframe["cast_id"] = cast_number
    if "station_id" in dataframe.columns and "cast_id" in dataframe.columns:
        dataframe["profile_id"] = dataframe["station_id"].astype(str) + "-" + dataframe["cast_id"].astype(str)

    aliases = {}
    if "profile_id" in dataframe.columns and len(dataframe.index):
        aliases["profile_id"] = dataframe.loc[0, "profile_id"]
    if "station_id" in dataframe.columns and len(dataframe.index):
        aliases["station_id"] = dataframe.loc[0, "station_id"]
    if "cast_id" in dataframe.columns and len(dataframe.index):
        aliases["cast_id"] = dataframe.loc[0, "cast_id"]

    return {
        "dataset_id": chosen["dataset_id"],
        "title": chosen["title"],
        "aliases": aliases,
        "rows": dataframe.to_dict(orient="records"),
    }


def query_amundsen_ctd(parameters: dict, output_path=None) -> dict:
    """Write a full Amundsen CTD profile to disk and return a download summary."""
    preview = preview_amundsen_profile(parameters)
    dataframe = pd.DataFrame(preview["rows"])

    from pathlib import Path

    path = Path(output_path) if output_path is not None else Path("/tmp/amundsen_ctd.tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, sep="\t", index=False)

    return {
        "dataset_id": preview["dataset_id"],
        "title": preview["title"],
        "file_path": str(path),
        "download_url": download_url(path.name),
        "row_count": int(len(dataframe.index)),
    }
