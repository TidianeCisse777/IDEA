"""Case-insensitive column name detection for source dataframes."""
from __future__ import annotations

from typing import Iterable
import unicodedata

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
    "sample_date",
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


def normalize_column_name(value: object) -> str:
    """Normalize a header without guessing its scientific meaning.

    Case, accents and separators are presentation details: ``Sample ID``,
    ``sample-id`` and ``SAMPLE.ID`` therefore represent the same header.
    The result is only used to compare known aliases, never to infer a role
    from a column's values.
    """
    decomposed = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(char for char in decomposed if char.isalnum())


def detect_column(columns: Iterable, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate match, ignoring case, accents and separators."""
    normalized_to_real = {normalize_column_name(column): column for column in columns}
    for candidate in candidates:
        match = normalized_to_real.get(normalize_column_name(candidate))
        if match is not None:
            return match
    return None
