"""Case-insensitive column name detection for source dataframes."""
from __future__ import annotations

from typing import Iterable

DEFAULT_LAT_CANDIDATES: tuple[str, ...] = (
    "latitude",
    "lat",
    "object_lat",
    "sample_lat",
    "latitude (degrees_north)",
)
DEFAULT_LON_CANDIDATES: tuple[str, ...] = (
    "longitude",
    "lon",
    "object_lon",
    "sample_long",
    "sample_lon",
    "longitude (degrees_east)",
)
DEFAULT_TIME_CANDIDATES: tuple[str, ...] = (
    "object_date",
    "sampledatetime",
    "time",
    "date",
    "sampling_date",
    "deployment_datetime_start",
    "yyyy-mm-dd hh:mm",
    "datetime",
)
DEFAULT_TIME_END_CANDIDATES: tuple[str, ...] = (
    "deployment_datetime_end",
    "time_end",
    "datetime_end",
    "end_time",
    "sampling_date_end",
)
DEFAULT_DEPTH_CANDIDATES: tuple[str, ...] = (
    "object_depth_min",
    "max_sample_depth",
    "depth",
    "pressure",
    "pres",
    "Depth [m]",
    "depth_m",
)


def detect_column(columns: Iterable, candidates: tuple[str, ...]) -> str | None:
    """Return the first column from `columns` whose lowercased name matches a candidate."""
    lower_to_real = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        match = lower_to_real.get(candidate.lower())
        if match is not None:
            return match
    return None
