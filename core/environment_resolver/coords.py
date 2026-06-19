"""Parse and validate latitude/longitude/time columns from a source dataframe."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CoordsValidation:
    """Result of parsing source coordinate/time columns.

    `empty_groups` lists labels ("latitude", "longitude", "time") whose
    parsed series contain only NaN/NaT values. When non-empty the caller
    should refuse to query the remote source.
    """

    latitude: pd.Series
    longitude: pd.Series
    time: pd.Series | None = None
    depth: pd.Series | None = None
    empty_groups: list[str] = field(default_factory=list)


def parse_source_coords(
    source: pd.DataFrame,
    *,
    lat_col: str,
    lon_col: str,
    time_col: str | None = None,
    depth_col: str | None = None,
) -> CoordsValidation:
    """Parse coord/time columns to numeric/datetime and report empty groups."""
    lat = pd.to_numeric(source[lat_col], errors="coerce")
    lon = pd.to_numeric(source[lon_col], errors="coerce")
    time = (
        pd.to_datetime(source[time_col], errors="coerce", utc=True)
        if time_col
        else None
    )
    depth = (
        pd.to_numeric(source[depth_col], errors="coerce") if depth_col else None
    )

    empty_groups: list[str] = []
    for label, series in (
        ("latitude", lat),
        ("longitude", lon),
        ("time", time),
    ):
        if series is None:
            continue
        if series.notna().sum() == 0:
            empty_groups.append(label)

    return CoordsValidation(
        latitude=lat,
        longitude=lon,
        time=time,
        depth=depth,
        empty_groups=empty_groups,
    )
