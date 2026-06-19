"""Compute ERDDAP bbox + time window with padding from source extents."""
from __future__ import annotations

import pandas as pd

DEFAULT_LAT_PADDING = 0.25
DEFAULT_LON_PADDING = 0.25
DEFAULT_TIME_PADDING_HOURS = 24.0


def compute_bbox_time_window(
    *,
    src_lat: pd.Series,
    src_lon: pd.Series,
    src_time: pd.Series,
    lat_padding: float = DEFAULT_LAT_PADDING,
    lon_padding: float = DEFAULT_LON_PADDING,
    time_padding_hours: float = DEFAULT_TIME_PADDING_HOURS,
) -> tuple[dict, dict]:
    """Return `(bbox, time_window)` ready for ERDDAP tabledap constraints.

    bbox keys: `lat_min`, `lat_max`, `lon_min`, `lon_max`.
    time_window keys: `start`, `end` formatted as `%Y-%m-%dT%H:%M:%SZ`.
    """
    bbox = {
        "lat_min": float(src_lat.min()) - lat_padding,
        "lat_max": float(src_lat.max()) + lat_padding,
        "lon_min": float(src_lon.min()) - lon_padding,
        "lon_max": float(src_lon.max()) + lon_padding,
    }
    time_window = {
        "start": (
            src_time.min() - pd.Timedelta(hours=time_padding_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": (
            src_time.max() + pd.Timedelta(hours=time_padding_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return bbox, time_window
