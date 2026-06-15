"""Planning and matching helpers for large OGSL enrichments."""
from __future__ import annotations

import pandas as pd


def _iso_utc(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_station_windows(
    source: pd.DataFrame,
    *,
    station_column: str,
    time_column: str,
    tolerance_hours: float,
) -> tuple[list[dict[str, str]], pd.Series]:
    """Build one padded OGSL query window per unique valid station."""
    parsed_time = pd.to_datetime(source[time_column], errors="coerce", utc=True)
    planning = pd.DataFrame({
        "station": source[station_column].astype("string").str.strip(),
        "time": parsed_time,
    })
    planning = planning[
        planning["station"].notna()
        & planning["station"].ne("")
        & planning["time"].notna()
    ]
    padding = pd.Timedelta(hours=tolerance_hours)
    windows = []
    for station, rows in planning.groupby("station", sort=False):
        windows.append({
            "station": str(station),
            "start": _iso_utc(rows["time"].min() - padding),
            "end": _iso_utc(rows["time"].max() + padding),
        })
    return windows, parsed_time


def enrich_with_ogsl(
    source: pd.DataFrame,
    ogsl: pd.DataFrame,
    *,
    station_column: str,
    time_column: str,
    depth_column: str | None,
    variables: list[str],
    time_tolerance_hours: float,
    depth_tolerance_m: float,
) -> pd.DataFrame:
    """Match each source row to the nearest valid OGSL measurement."""
    enriched = source.copy(deep=True)
    source_station = source[station_column].astype("string").str.strip()
    source_time = pd.to_datetime(source[time_column], errors="coerce", utc=True)
    source_depth = (
        pd.to_numeric(source[depth_column], errors="coerce")
        if depth_column
        else None
    )

    ogsl_work = ogsl.copy(deep=True)
    if not ogsl_work.empty:
        ogsl_work["_ogsl_station"] = (
            ogsl_work["stationID"].astype("string").str.strip()
        )
        ogsl_work["_ogsl_time"] = pd.to_datetime(
            ogsl_work["time"], errors="coerce", utc=True
        )
        if "PRES" in ogsl_work.columns:
            ogsl_work["_ogsl_pres"] = pd.to_numeric(
                ogsl_work["PRES"], errors="coerce"
            )
    ogsl_by_station = {
        str(station): rows.copy()
        for station, rows in ogsl_work.groupby("_ogsl_station", sort=False)
    } if "_ogsl_station" in ogsl_work.columns else {}
    match_cache: dict[tuple, tuple[str, pd.Series | None, float | None, float | None]] = {}

    output_columns = {
        "ogsl_station_id": [],
        "ogsl_time": [],
        "ogsl_pres": [],
        "ogsl_cruise_id": [],
        "ogsl_cast_number": [],
        "ogsl_time_delta_min": [],
        "ogsl_depth_delta_m": [],
        "ogsl_match_status": [],
    }
    variable_columns = {
        f"ogsl_{variable.lower()}": []
        for variable in variables
        if variable != "PRES"
    }

    time_tolerance = pd.Timedelta(hours=time_tolerance_hours)
    for position in range(len(source)):
        station = source_station.iloc[position]
        raw_time = source[time_column].iloc[position]
        timestamp = source_time.iloc[position]
        raw_depth = (
            source[depth_column].iloc[position] if depth_column else None
        )
        depth = source_depth.iloc[position] if source_depth is not None else None

        status = "matched"
        candidate = None
        time_delta = None
        depth_delta = None
        if pd.isna(station) or not str(station):
            status = "missing_station"
        elif pd.isna(raw_time):
            status = "missing_time"
        elif pd.isna(timestamp):
            status = "invalid_time"
        elif depth_column and pd.isna(raw_depth):
            status = "missing_depth"
        elif depth_column and pd.isna(depth):
            status = "invalid_depth"
        else:
            cache_key = (
                str(station),
                timestamp.value,
                float(depth) if depth_column else None,
            )
            cached = match_cache.get(cache_key)
            if cached is not None:
                status, candidate, time_delta, depth_delta = cached
            else:
                candidates = ogsl_by_station.get(str(station))
                if candidates is None or candidates.empty:
                    status = "no_match"
                else:
                    candidates = candidates[
                        candidates["_ogsl_time"].notna()
                    ].copy()
                    candidates["_time_delta"] = (
                        candidates["_ogsl_time"] - timestamp
                    ).abs()
                    nearest_time_delta = candidates["_time_delta"].min()
                    if (
                        pd.isna(nearest_time_delta)
                        or nearest_time_delta > time_tolerance
                    ):
                        status = "no_match"
                    else:
                        nearest_cast = candidates[
                            candidates["_time_delta"].eq(nearest_time_delta)
                        ].copy()
                        time_delta = nearest_time_delta.total_seconds() / 60
                        if depth_column:
                            nearest_cast = nearest_cast[
                                nearest_cast["_ogsl_pres"].notna()
                            ].copy()
                            if nearest_cast.empty:
                                status = "no_match"
                            else:
                                nearest_cast["_depth_delta"] = (
                                    nearest_cast["_ogsl_pres"] - float(depth)
                                ).abs()
                                depth_delta = float(
                                    nearest_cast["_depth_delta"].min()
                                )
                                if depth_delta > depth_tolerance_m:
                                    status = "no_match"
                                else:
                                    candidate = nearest_cast.loc[
                                        nearest_cast["_depth_delta"].idxmin()
                                    ]
                        else:
                            nearest_cast = nearest_cast[
                                nearest_cast["_ogsl_pres"].notna()
                            ]
                            if nearest_cast.empty:
                                status = "no_match"
                            else:
                                candidate = nearest_cast.loc[
                                    nearest_cast["_ogsl_pres"].idxmin()
                                ]
                match_cache[cache_key] = (
                    status,
                    candidate,
                    time_delta,
                    depth_delta,
                )

        matched = status == "matched" and candidate is not None
        output_columns["ogsl_station_id"].append(
            candidate.get("stationID") if matched else pd.NA
        )
        output_columns["ogsl_time"].append(
            candidate.get("time") if matched else pd.NA
        )
        output_columns["ogsl_pres"].append(
            candidate.get("PRES") if matched else pd.NA
        )
        output_columns["ogsl_cruise_id"].append(
            candidate.get("cruiseID") if matched else pd.NA
        )
        output_columns["ogsl_cast_number"].append(
            candidate.get("cast_number") if matched else pd.NA
        )
        output_columns["ogsl_time_delta_min"].append(
            time_delta if matched else pd.NA
        )
        output_columns["ogsl_depth_delta_m"].append(
            depth_delta if matched and depth_column else pd.NA
        )
        output_columns["ogsl_match_status"].append(status)
        for variable in variables:
            if variable == "PRES":
                continue
            variable_columns[f"ogsl_{variable.lower()}"].append(
                candidate.get(variable) if matched else pd.NA
            )

    for column, values in {**variable_columns, **output_columns}.items():
        enriched[column] = values
    return enriched
