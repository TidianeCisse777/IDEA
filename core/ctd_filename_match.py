"""Verified UVP ↔ Amundsen CTD matching through the rosette filename.

EcoTaxa records the CTD-rosette filename associated with a UVP profile.  The
Amundsen ERDDAP table exposes the filename, station, position and acquisition
time for the same CTD profile.  A filename candidate alone is not enough:
short labels such as ``062`` recur between cruises.  This module therefore
requires filename, station, time and position agreement before declaring a
join eligible.
"""

from __future__ import annotations

import math
import re
import unicodedata

import pandas as pd

from core.environment_resolver.geo import haversine_km


CTD_FILENAME_MATCH_VERSION = "uvp-amundsen-ctd-filename-match-v1"

_OUTPUT_COLUMNS = [
    "uvp_sample_id",
    "uvp_ctd_filename",
    "amundsen_filename",
    "amundsen_station",
    "amundsen_cast_number",
    "filename_match",
    "station_match",
    "distance_km",
    "time_delta_min",
    "match_status",
    "join_eligible",
    "method_version",
]


def _ascii_tokens(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return re.findall(r"[a-z]+|\d+", text)


def ctd_filename_aliases(value: object) -> set[str]:
    """Return stable aliases for a CTD filename without inventing an ID.

    ``2309_062.int.nc`` and ``062`` share the terminal numeric alias.  That
    weaker alias is intentionally accepted only alongside station, time and
    coordinate validation in :func:`match_uvp_to_amundsen_ctd`.
    """
    if value is None:
        return set()
    try:
        if math.isnan(float(value)):
            return set()
    except (TypeError, ValueError):
        pass
    raw = str(value).strip()
    # Spreadsheet exports often serialise a numeric rosette id as ``1601002.0``.
    # It is the same identifier as ``1601002``; treating the decimal suffix as
    # a second token would make an otherwise exact CTD-file match impossible.
    raw = re.sub(r"^(\d+)\.0+$", r"\1", raw)
    tokens = _ascii_tokens(raw)
    while tokens and tokens[-1] in {"nc", "int", "cnv", "csv", "txt"}:
        tokens.pop()
    if not tokens:
        return set()
    aliases = {"".join(tokens)}
    terminal = tokens[-1]
    if terminal.isdigit():
        aliases.add(str(int(terminal)))
        aliases.add(terminal)
    return aliases


def _station_aliases(value: object) -> set[str]:
    tokens = _ascii_tokens(value)
    aliases = {"".join(tokens)} if tokens else set()
    aliases.update(token for token in tokens if len(token) >= 2)
    return aliases


def _same_station(left: object, right: object) -> bool:
    left_aliases = _station_aliases(left)
    right_aliases = _station_aliases(right)
    return bool(left_aliases and right_aliases and left_aliases & right_aliases)


def match_uvp_to_amundsen_ctd(
    uvp_df: pd.DataFrame,
    amundsen_df: pd.DataFrame,
    *,
    uvp_id_col: str = "sample_id",
    uvp_filename_col: str = "ctd_rosette_filename",
    uvp_station_col: str = "station_id",
    uvp_lat_col: str = "lat_avg",
    uvp_lon_col: str = "lon_avg",
    uvp_time_col: str = "datetime_min",
    amundsen_filename_col: str = "filename",
    amundsen_station_col: str = "station",
    amundsen_cast_col: str = "cast_number",
    amundsen_lat_col: str = "latitude",
    amundsen_lon_col: str = "longitude",
    amundsen_time_col: str = "time",
    max_distance_km: float = 2.0,
    max_time_delta_minutes: float = 90.0,
) -> pd.DataFrame:
    """Return only CTD-file candidates, with strict join eligibility.

    A row is ``matched`` only when the filename aliases overlap *and* station,
    time and position can each be verified within their tolerance.  Otherwise
    it is retained as ``filename_candidate`` for audit, never for a join.
    """
    required_uvp = {uvp_id_col, uvp_filename_col}
    required_ctd = {amundsen_filename_col}
    missing_uvp = sorted(required_uvp.difference(uvp_df.columns))
    missing_ctd = sorted(required_ctd.difference(amundsen_df.columns))
    if missing_uvp or missing_ctd:
        missing = [*(f"UVP:{name}" for name in missing_uvp), *(f"CTD:{name}" for name in missing_ctd)]
        raise ValueError("Colonnes de liaison CTD absentes : " + ", ".join(missing))

    ctd = amundsen_df.copy()
    ctd["_filename_aliases"] = ctd[amundsen_filename_col].map(ctd_filename_aliases)
    ctd = ctd[ctd["_filename_aliases"].map(bool)].copy()
    if ctd.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    ctd["_time"] = (
        pd.to_datetime(ctd[amundsen_time_col], errors="coerce", utc=True)
        if amundsen_time_col in ctd.columns else pd.NaT
    )
    ctd["_lat"] = pd.to_numeric(ctd.get(amundsen_lat_col), errors="coerce")
    ctd["_lon"] = pd.to_numeric(ctd.get(amundsen_lon_col), errors="coerce")
    ctd = ctd.drop_duplicates(
        subset=[column for column in (amundsen_filename_col, amundsen_station_col, amundsen_cast_col, amundsen_time_col) if column in ctd.columns]
    )

    rows: list[dict] = []
    for _, uvp in uvp_df.iterrows():
        aliases = ctd_filename_aliases(uvp[uvp_filename_col])
        if not aliases:
            continue
        candidates = ctd[ctd["_filename_aliases"].map(lambda values: bool(aliases & values))]
        if candidates.empty:
            continue
        uvp_time = pd.to_datetime(uvp.get(uvp_time_col), errors="coerce", utc=True)
        uvp_lat = pd.to_numeric(pd.Series([uvp.get(uvp_lat_col)]), errors="coerce").iloc[0]
        uvp_lon = pd.to_numeric(pd.Series([uvp.get(uvp_lon_col)]), errors="coerce").iloc[0]
        scored: list[dict] = []
        for _, ctd_row in candidates.iterrows():
            station_match = _same_station(uvp.get(uvp_station_col), ctd_row.get(amundsen_station_col))
            time_delta = None
            if pd.notna(uvp_time) and pd.notna(ctd_row["_time"]):
                time_delta = abs((ctd_row["_time"] - uvp_time).total_seconds()) / 60.0
            distance = None
            if pd.notna(uvp_lat) and pd.notna(uvp_lon) and pd.notna(ctd_row["_lat"]) and pd.notna(ctd_row["_lon"]):
                distance = haversine_km(float(uvp_lat), float(uvp_lon), float(ctd_row["_lat"]), float(ctd_row["_lon"]))
            eligible = (
                station_match
                and time_delta is not None and time_delta <= max_time_delta_minutes
                and distance is not None and distance <= max_distance_km
            )
            scored.append({
                "uvp_sample_id": uvp[uvp_id_col],
                "uvp_ctd_filename": uvp[uvp_filename_col],
                "amundsen_filename": ctd_row[amundsen_filename_col],
                "amundsen_station": ctd_row.get(amundsen_station_col),
                "amundsen_cast_number": ctd_row.get(amundsen_cast_col),
                "filename_match": True,
                "station_match": station_match,
                "distance_km": round(distance, 3) if distance is not None else None,
                "time_delta_min": round(time_delta, 1) if time_delta is not None else None,
                "match_status": "matched" if eligible else "filename_candidate",
                "join_eligible": eligible,
                "method_version": CTD_FILENAME_MATCH_VERSION,
                "_sort_eligible": eligible,
                "_sort_time": time_delta if time_delta is not None else float("inf"),
                "_sort_distance": distance if distance is not None else float("inf"),
            })
        if scored:
            selected = sorted(
                scored,
                key=lambda row: (-int(row["_sort_eligible"]), row["_sort_time"], row["_sort_distance"], str(row["amundsen_filename"])),
            )[0]
            for internal in ("_sort_eligible", "_sort_time", "_sort_distance"):
                selected.pop(internal)
            rows.append(selected)
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
