"""Shared helpers for lat/lon/time enrichment tools.

Extracted from tools/amundsen_sources.py, tools/bio_oracle_sources.py and
tools/ogsl_sources.py so the three enrichment slices share one
implementation of column detection, source-table resolution, coordinate
parsing, bbox/time-window computation and nearest-neighbour CTD matching.
"""
from core.environment_resolver.bbox import compute_bbox_time_window
from core.environment_resolver.column_detection import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    detect_column,
)
from core.environment_resolver.coords import (
    CoordsValidation,
    parse_source_coords,
)
from core.environment_resolver.geo import haversine_km
from core.environment_resolver.matcher import CtdMatch, match_ctd_rows
from core.environment_resolver.source import resolve_source_dataframe

__all__ = [
    "CoordsValidation",
    "CtdMatch",
    "DEFAULT_DEPTH_CANDIDATES",
    "DEFAULT_LAT_CANDIDATES",
    "DEFAULT_LON_CANDIDATES",
    "DEFAULT_TIME_CANDIDATES",
    "compute_bbox_time_window",
    "detect_column",
    "haversine_km",
    "match_ctd_rows",
    "parse_source_coords",
    "resolve_source_dataframe",
]
