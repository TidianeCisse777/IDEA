"""Client for the OGSL ISMER CTD ERDDAP dataset."""
from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

OGSL_DATASET_ID = "ismerSgdeCtd"
OGSL_TABLEDAP_URL = (
    f"https://erddap.ogsl.ca/erddap/tabledap/{OGSL_DATASET_ID}.csvp"
)
OGSL_CORE_COLUMNS = [
    "longitude",
    "latitude",
    "time",
    "cruiseID",
    "stationID",
    "cast_number",
]
OGSL_VARIABLES = {
    "TE90",
    "PSAL",
    "ASAL",
    "PRES",
    "OXYM",
    "FLOR",
    "NTRA",
    "SIGT",
    "PHPH",
    "PSAR",
    "TRAN",
    "TRB",
}


def _query_url(
    *,
    station: str,
    variables: list[str],
    start: str | None,
    end: str | None,
) -> str:
    columns = list(dict.fromkeys([*OGSL_CORE_COLUMNS, *variables]))
    constraints = [f'stationID="{station}"']
    if start:
        constraints.append(f"time>={start}")
    if end:
        constraints.append(f"time<={end}")
    encoded_constraints = "&".join(
        quote(constraint, safe="><=") for constraint in constraints
    )
    return f"{OGSL_TABLEDAP_URL}?{','.join(columns)}&{encoded_constraints}"


def query_ogsl(parameters: dict, *, output_path: str | Path) -> dict:
    """Download OGSL profiles for one or more station IDs."""
    station_windows = list(parameters.get("station_windows") or [])
    stations = [
        str(station).strip()
        for station in parameters.get("stations") or []
        if str(station).strip()
    ]
    if not station_windows:
        station_windows = [
            {
                "station": station,
                "start": parameters.get("start"),
                "end": parameters.get("end"),
            }
            for station in dict.fromkeys(stations)
        ]
    if not station_windows:
        raise ValueError("At least one OGSL station is required.")
    for window in station_windows:
        if not str(window.get("station") or "").strip():
            raise ValueError("Every OGSL station window requires a station.")

    variables = list(parameters.get("variables") or ["PRES", "TE90", "PSAL"])
    invalid_variables = sorted(set(variables) - OGSL_VARIABLES)
    if invalid_variables:
        raise ValueError(
            "Unsupported OGSL variables: " + ", ".join(invalid_variables)
        )

    frames = []
    for window in station_windows:
        response = requests.get(
            _query_url(
                station=str(window["station"]).strip(),
                variables=variables,
                start=window.get("start"),
                end=window.get("end"),
            ),
            timeout=30,
        )
        if response.status_code == 404:
            continue
        response.raise_for_status()
        dataframe = pd.read_csv(io.StringIO(response.text))
        dataframe = dataframe.rename(
            columns={
                column: re.sub(r"\s+\([^)]*\)$", "", str(column))
                for column in dataframe.columns
            }
        )
        if not dataframe.empty:
            frames.append(dataframe)

    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=[*OGSL_CORE_COLUMNS, *variables])
    )
    output_path = Path(output_path)
    result.to_csv(output_path, index=False)
    return {
        "dataset_id": OGSL_DATASET_ID,
        "download_url": str(output_path),
        "row_count": len(result),
    }
