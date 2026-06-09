"""Shared Bio-ORACLE helpers."""
from __future__ import annotations

from pathlib import Path

import requests
import pandas as pd


def plan_bio_oracle_request(parameters: dict) -> dict:
    """Normalize a Bio-ORACLE request and report missing required fields."""
    missing_fields = []
    if not parameters.get("scenario"):
        missing_fields.append("scenario")
    if not parameters.get("depth_layer"):
        missing_fields.append("depth_layer")
    if parameters.get("latitude") is None or parameters.get("longitude") is None:
        missing_fields.append("zone")

    return {
        "source_id": "bio_oracle",
        "parameters": parameters,
        "missing_fields": missing_fields,
        "recommended_next_step": "ask_clarification" if missing_fields else "proceed",
        "clarification_question": "Which Bio-ORACLE scenario, depth layer, and coordinates do you want?",
    }


def describe_bio_oracle_source() -> dict:
    """Return the canonical Bio-ORACLE source description used by the agent."""
    return {
        "id": "bio_oracle",
        "label": "Bio-ORACLE — variables environnementales marines",
        "content_summary": (
            "Variables environnementales marines à l'échelle globale : température, salinité, "
            "oxygène, nitrate et chlorophylle. Disponible pour périodes historiques et pour "
            "chaque scénario futur (SSP) avec profondeur explicite."
        ),
        "join_keys": ["latitude", "longitude", "depth_layer"],
        "known_limitations": [
            "Résolution spatiale ~ 5 arc-minutes — insuffisante pour des analyses à l'échelle d'une station.",
            "Les scénarios futurs (SSP) requièrent de préciser la période et le scénario.",
        ],
        "requires_credentials": False,
        "found": True,
    }


def list_bio_oracle_datasets() -> list[dict]:
    """Return the Bio-ORACLE datasets discovered from the ERDDAP search API."""
    response = requests.get(
        "https://erddap.bio-oracle.org/erddap/search/index.json",
        params={"searchFor": "bio-oracle", "itemsPerPage": 200},
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


def preview_bio_oracle_point(parameters: dict) -> dict:
    """Return a small preview sample for one Bio-ORACLE point and scenario."""
    variable = str(parameters.get("variable") or "").strip()
    scenario = str(parameters.get("scenario") or "").strip()
    depth_layer = str(parameters.get("depth_layer") or "").strip()

    datasets = list_bio_oracle_datasets()
    chosen = None
    for dataset in datasets:
        haystack = " ".join(
            part for part in [dataset.get("dataset_id"), dataset.get("title")] if part
        ).lower()
        if variable.lower() in haystack and scenario.lower() in haystack and depth_layer.lower() in haystack:
            chosen = dataset
            break
    if chosen is None and datasets:
        chosen = datasets[0]
    if chosen is None:
        raise RuntimeError("No Bio-ORACLE dataset matched the request")

    response = requests.get(f"{chosen['griddap']}.csv", timeout=30)
    response.raise_for_status()
    dataframe = pd.read_csv(pd.io.common.StringIO(response.text))

    return {
        "dataset_id": chosen["dataset_id"],
        "title": chosen["title"],
        "rows": dataframe.to_dict(orient="records"),
    }


def query_bio_oracle(parameters: dict, output_path: Path | str | None = None) -> dict:
    """Write a Bio-ORACLE query result to disk and return a download summary."""
    preview = preview_bio_oracle_point(parameters)
    dataframe = pd.DataFrame(preview["rows"])

    path = Path(output_path) if output_path is not None else Path("/tmp/bio_oracle.tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, sep="\t", index=False)
    download_url = f"http://localhost:8000/downloads/{path.name}"

    return {
        "dataset_id": preview["dataset_id"],
        "title": preview["title"],
        "file_path": str(path),
        "download_url": download_url,
        "row_count": int(len(dataframe.index)),
    }
