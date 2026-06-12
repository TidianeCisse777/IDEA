"""Shared Bio-ORACLE helpers."""
from __future__ import annotations

import io
from pathlib import Path

import requests
import pandas as pd

from tools.public_url import download_url

_ERDDAP_BASE = "https://erddap.bio-oracle.org/erddap"

# ── Friendly-name → ERDDAP canonical mappings ────────────────────────────────

_VAR_MAP: dict[str, str] = {
    # temperature
    "temperature": "thetao", "temp": "thetao", "température": "thetao",
    "thetao": "thetao",
    # salinity
    "salinity": "so", "salinité": "so", "salinite": "so", "sel": "so",
    "so": "so",
    # oxygen
    "oxygen": "o2", "oxygène": "o2", "oxygene": "o2", "o2": "o2",
    # chlorophyll
    "chlorophyll": "chl", "chlorophylle": "chl", "chl": "chl",
    # nitrate
    "nitrate": "no3", "no3": "no3",
    # pH
    "ph": "ph",
    # iron
    "iron": "dfe", "fer": "dfe", "dfe": "dfe",
}

_SCENARIO_MAP: dict[str, str] = {
    "ssp585": "ssp585", "ssp5-8.5": "ssp585", "ssp5_8_5": "ssp585",
    "ssp5": "ssp585", "rcp85": "ssp585",
    "ssp126": "ssp126", "ssp1-2.6": "ssp126", "ssp1_2_6": "ssp126",
    "ssp1": "ssp126",
    "ssp245": "ssp245", "ssp2-4.5": "ssp245", "ssp2_4_5": "ssp245",
    "ssp2": "ssp245",
    "ssp370": "ssp370", "ssp3-7.0": "ssp370",
    "baseline": "baseline", "present": "baseline", "actuel": "baseline",
    "historique": "baseline", "current": "baseline",
}

_DEPTH_MAP: dict[str, str] = {
    "surface": "depthsurf", "surf": "depthsurf", "depthsurf": "depthsurf",
    "mean": "depthmean", "depthmean": "depthmean", "moyenne": "depthmean",
    "max": "depthmax", "depthmax": "depthmax", "maximum": "depthmax",
    "min": "depthmin", "depthmin": "depthmin", "minimum": "depthmin",
}


def _normalise(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _resolve_var(value: str) -> str:
    return _VAR_MAP.get(_normalise(value), _normalise(value))


def _resolve_scenario(value: str) -> str:
    return _SCENARIO_MAP.get(_normalise(value), _normalise(value))


def _resolve_depth(value: str) -> str:
    return _DEPTH_MAP.get(_normalise(value), _normalise(value))


def _find_dataset_id(var: str, scenario: str, depth: str) -> str:
    """Build the Bio-ORACLE dataset ID and verify it exists on ERDDAP."""
    if scenario == "baseline":
        candidates = [
            f"{var}_baseline_2000_2018_{depth}",
            f"{var}_baseline_2000_2019_{depth}",
            f"{var}_baseline_2000_2020_{depth}",
        ]
    else:
        candidates = [
            f"{var}_{scenario}_2020_2100_{depth}",
            f"{var}_{scenario}_2015_2100_{depth}",
        ]

    for dataset_id in candidates:
        url = f"{_ERDDAP_BASE}/griddap/{dataset_id}.das"
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code < 400:
                return dataset_id
        except requests.RequestException:
            continue

    # Fallback: search ERDDAP for the dataset
    try:
        r = requests.get(
            f"{_ERDDAP_BASE}/search/index.json",
            params={"searchFor": f"{var} {scenario} {depth}", "itemsPerPage": 20},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        for row in payload.get("table", {}).get("rows", []):
            did = str(row[4] if len(row) > 4 else "")
            if var in did and depth in did:
                return did.split("/")[-1].split("?")[0]
    except Exception:
        pass

    raise RuntimeError(
        f"No Bio-ORACLE dataset found for variable='{var}', scenario='{scenario}', depth='{depth}'. "
        f"Tried: {candidates}"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def plan_bio_oracle_request(parameters: dict) -> dict:
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
    """Return available Bio-ORACLE datasets from ERDDAP griddap index."""
    r = requests.get(
        f"{_ERDDAP_BASE}/griddap/index.json",
        params={"itemsPerPage": 500},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json() or {}
    table = payload.get("table") or {}
    columns = table.get("columnNames") or []
    rows = table.get("rows") or []
    normalized = []
    for row in rows:
        record = dict(zip(columns, row))
        dataset_id = str(record.get("Dataset ID") or record.get("datasetID") or "")
        if not dataset_id or dataset_id.startswith("allDatasets"):
            continue
        griddap_url = f"{_ERDDAP_BASE}/griddap/{dataset_id}"
        normalized.append({
            "dataset_id": dataset_id,
            "title": str(record.get("Title") or record.get("title") or ""),
            "griddap": griddap_url,
        })
    return normalized


def preview_bio_oracle_point(parameters: dict) -> dict:
    """Return a small preview for one Bio-ORACLE point."""
    var = _resolve_var(str(parameters.get("variable") or "thetao"))
    scenario = _resolve_scenario(str(parameters.get("scenario") or "baseline"))
    depth = _resolve_depth(str(parameters.get("depth_layer") or "depthsurf"))
    latitude = float(parameters["latitude"])
    longitude = float(parameters["longitude"])

    dataset_id = _find_dataset_id(var, scenario, depth)
    griddap_url = f"{_ERDDAP_BASE}/griddap/{dataset_id}"

    # Bio-ORACLE variable names inside the dataset use a {var}_mean suffix
    query_var = f"{var}_mean"
    url = f"{griddap_url}.csv?{query_var}[(last)][({latitude:.4f})][({longitude:.4f})]"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    lines = response.text.splitlines()
    data_text = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else response.text
    dataframe = pd.read_csv(io.StringIO(data_text))

    return {
        "dataset_id": dataset_id,
        "title": dataset_id,
        "rows": dataframe.to_dict(orient="records"),
        "variable": query_var,
    }


def query_bio_oracle(parameters: dict, output_path: Path | str | None = None) -> dict:
    """Write a Bio-ORACLE query result to disk and return a download summary."""
    preview = preview_bio_oracle_point(parameters)
    dataframe = pd.DataFrame(preview["rows"])

    path = Path(output_path) if output_path is not None else Path("/tmp/bio_oracle.tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, sep="\t", index=False)
    return {
        "dataset_id": preview["dataset_id"],
        "title": preview["title"],
        "file_path": str(path),
        "download_url": download_url(path.name),
        "row_count": int(len(dataframe.index)),
    }
