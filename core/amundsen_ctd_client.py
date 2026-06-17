"""Shared Amundsen CTD helpers."""
from __future__ import annotations

import io
import os
import time

import pandas as pd
import requests

from tools.public_url import download_url


_DATASETS_CACHE: dict[str, object] = {"datasets": None, "expires_at": 0.0}


def _dataset_cache_ttl() -> float:
    try:
        return float(os.getenv("AMUNDSEN_DATASET_CACHE_TTL", "3600"))
    except ValueError:
        return 3600.0


def clear_amundsen_dataset_cache() -> None:
    """Drop the in-process cache of the ERDDAP dataset catalogue."""
    _DATASETS_CACHE["datasets"] = None
    _DATASETS_CACHE["expires_at"] = 0.0


def list_amundsen_datasets() -> list[dict]:
    """Return the Amundsen CTD datasets discovered from ERDDAP.

    The ERDDAP search catalogue is cached in-process for
    ``AMUNDSEN_DATASET_CACHE_TTL`` seconds (default 3600). Within a turn the
    agent can chain `preview_amundsen_profile` / `query_amundsen_ctd` calls
    without re-fetching the catalogue each time.
    """
    cached = _DATASETS_CACHE.get("datasets")
    expires_at = float(_DATASETS_CACHE.get("expires_at") or 0.0)
    if cached is not None and time.monotonic() < expires_at:
        return list(cached)  # defensive copy

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
                "tabledap": str(record.get("tabledap") or ""),
            }
        )
    _DATASETS_CACHE["datasets"] = list(normalized)
    _DATASETS_CACHE["expires_at"] = time.monotonic() + _dataset_cache_ttl()
    return normalized


def preview_amundsen_profile(parameters: dict) -> dict:
    """Return a small raw preview for one Amundsen CTD profile."""
    station = parameters.get("station")
    cast_number = parameters.get("cast_number")
    datasets = list_amundsen_datasets()
    # Prefer the 2018 Amundsen cruise dataset used in this project
    chosen = next((d for d in datasets if d["dataset_id"] == "amundsen12713"), datasets[0] if datasets else None)
    if chosen is None:
        raise RuntimeError("No Amundsen CTD dataset matched the request")

    tabledap_url = chosen["tabledap"]
    if not tabledap_url:
        raise RuntimeError(f"Dataset {chosen['dataset_id']} has no tabledap endpoint")

    variables = "time,latitude,longitude,station,cast_number,PRES,depth,TE90,PSAL"
    constraints = ""
    if station is not None:
        constraints += f'&station="{station}"'
    if cast_number is not None:
        constraints += f"&cast_number={cast_number}"

    url = f"{tabledap_url}.csv?{variables}{constraints}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    # ERDDAP CSV: row 0 = column names, row 1 = units — skip units row when present
    lines = response.text.splitlines()
    data_text = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else response.text
    dataframe = pd.read_csv(io.StringIO(data_text))

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
