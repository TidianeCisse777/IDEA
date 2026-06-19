"""Tests for the shared environment_resolver helpers.

These tests pin the behaviour the helpers must preserve when extracted from
tools/amundsen_sources.py, tools/bio_oracle_sources.py and
tools/ogsl_sources.py.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from core.environment_resolver import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    CtdMatch,
    compute_bbox_time_window,
    detect_column,
    haversine_km,
    match_ctd_rows,
    parse_source_coords,
    resolve_source_dataframe,
)


# ---- column_detection ---------------------------------------------------


def test_detect_column_matches_case_insensitively():
    columns = ["Latitude", "Longitude", "Object_Date"]
    assert detect_column(columns, ("latitude", "lat")) == "Latitude"
    assert detect_column(columns, ("object_date",)) == "Object_Date"


def test_detect_column_returns_first_matching_candidate():
    columns = ["sample_lat", "object_lat"]
    assert detect_column(columns, ("object_lat", "sample_lat")) == "object_lat"


def test_detect_column_returns_none_when_no_match():
    assert detect_column(["foo", "bar"], ("latitude", "lat")) is None


def test_default_candidates_cover_known_aliases():
    assert "latitude" in DEFAULT_LAT_CANDIDATES
    assert "object_lat" in DEFAULT_LAT_CANDIDATES
    assert "longitude" in DEFAULT_LON_CANDIDATES
    assert "object_date" in DEFAULT_TIME_CANDIDATES
    assert "object_depth_min" in DEFAULT_DEPTH_CANDIDATES


# ---- geo ----------------------------------------------------------------


def test_haversine_returns_zero_for_same_point():
    assert haversine_km(48.0, -68.0, 48.0, -68.0) == pytest.approx(0.0, abs=1e-6)


def test_haversine_one_degree_latitude_is_about_111_km():
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.195, abs=0.5)


def test_haversine_symmetric():
    a = haversine_km(48.0, -68.0, 49.0, -67.0)
    b = haversine_km(49.0, -67.0, 48.0, -68.0)
    assert a == pytest.approx(b)


# ---- source resolution --------------------------------------------------


class _FakeStore:
    """Minimal in-memory store with the keys()/get() API."""

    def __init__(self):
        self._data: dict = {}

    def set(self, key, value):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def keys(self, prefix: str | None = None):
        if prefix is None:
            return list(self._data.keys())
        return [k for k in self._data if k.startswith(prefix)]


def test_resolve_source_dataframe_falls_back_to_active_df_when_no_variable():
    store = _FakeStore()
    df = pd.DataFrame({"a": [1, 2]})
    store.set("thread-1", {"df": df})
    assert resolve_source_dataframe(store, "thread-1", None) is df


def test_resolve_source_dataframe_returns_none_when_session_empty():
    store = _FakeStore()
    assert resolve_source_dataframe(store, "thread-1", None) is None


def test_resolve_source_dataframe_returns_none_when_active_df_is_empty():
    store = _FakeStore()
    store.set("thread-1", {"df": pd.DataFrame()})
    assert resolve_source_dataframe(store, "thread-1", None) is None


def test_resolve_source_dataframe_finds_named_dataset_by_meta_variable_name():
    store = _FakeStore()
    df_a = pd.DataFrame({"x": [1]})
    df_b = pd.DataFrame({"y": [2]})
    store.set(
        "thread-1:dataset:df_file_a",
        {"df": df_a, "meta": {"variable_name": "df_file_a"}},
    )
    store.set(
        "thread-1:dataset:df_file_b",
        {"df": df_b, "meta": {"variable_name": "df_file_b"}},
    )
    assert resolve_source_dataframe(store, "thread-1", "df_file_b") is df_b


def test_resolve_source_dataframe_returns_none_when_named_variable_missing():
    store = _FakeStore()
    df_a = pd.DataFrame({"x": [1]})
    store.set(
        "thread-1:dataset:df_file_a",
        {"df": df_a, "meta": {"variable_name": "df_file_a"}},
    )
    assert resolve_source_dataframe(store, "thread-1", "df_file_missing") is None


def test_resolve_source_dataframe_skips_empty_named_dataset():
    store = _FakeStore()
    store.set(
        "thread-1:dataset:df_file_a",
        {"df": pd.DataFrame(), "meta": {"variable_name": "df_file_a"}},
    )
    assert resolve_source_dataframe(store, "thread-1", "df_file_a") is None


# ---- coords parsing -----------------------------------------------------


def test_parse_source_coords_parses_lat_lon_time_and_depth():
    df = pd.DataFrame(
        {
            "lat": ["48.5", "49.0"],
            "lon": ["-68.0", "-67.5"],
            "time": ["2018-08-01T12:00:00Z", "2018-08-02T00:00:00Z"],
            "depth": ["10", "20"],
        }
    )
    result = parse_source_coords(
        df, lat_col="lat", lon_col="lon", time_col="time", depth_col="depth"
    )
    assert result.latitude.tolist() == [48.5, 49.0]
    assert result.longitude.tolist() == [-68.0, -67.5]
    assert result.depth.tolist() == [10.0, 20.0]
    assert result.time.notna().all()
    assert result.empty_groups == []


def test_parse_source_coords_reports_all_empty_groups():
    df = pd.DataFrame(
        {
            "lat": [None, None],
            "lon": [None, None],
            "time": [None, None],
        }
    )
    result = parse_source_coords(
        df, lat_col="lat", lon_col="lon", time_col="time"
    )
    assert result.empty_groups == ["latitude", "longitude", "time"]


def test_parse_source_coords_skips_time_when_no_time_column():
    df = pd.DataFrame({"lat": [48.0], "lon": [-68.0]})
    result = parse_source_coords(df, lat_col="lat", lon_col="lon")
    assert result.time is None
    assert result.empty_groups == []


# ---- bbox + time window -------------------------------------------------


def test_compute_bbox_time_window_applies_default_padding():
    src_lat = pd.Series([48.0, 49.0])
    src_lon = pd.Series([-68.0, -67.0])
    src_time = pd.to_datetime(
        pd.Series(["2018-08-01T00:00:00Z", "2018-08-03T00:00:00Z"]), utc=True
    )
    bbox, window = compute_bbox_time_window(
        src_lat=src_lat, src_lon=src_lon, src_time=src_time
    )
    assert bbox == {
        "lat_min": pytest.approx(47.75),
        "lat_max": pytest.approx(49.25),
        "lon_min": pytest.approx(-68.25),
        "lon_max": pytest.approx(-66.75),
    }
    assert window["start"] == "2018-07-31T00:00:00Z"
    assert window["end"] == "2018-08-04T00:00:00Z"


def test_compute_bbox_time_window_respects_custom_padding():
    src_lat = pd.Series([10.0])
    src_lon = pd.Series([20.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    bbox, window = compute_bbox_time_window(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        lat_padding=1.0,
        lon_padding=2.0,
        time_padding_hours=48.0,
    )
    assert bbox["lat_min"] == pytest.approx(9.0)
    assert bbox["lat_max"] == pytest.approx(11.0)
    assert bbox["lon_min"] == pytest.approx(18.0)
    assert bbox["lon_max"] == pytest.approx(22.0)
    assert window["start"] == "2019-12-30T00:00:00Z"
    assert window["end"] == "2020-01-03T00:00:00Z"


# ---- CTD matcher --------------------------------------------------------


def _build_ctd(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_match_ctd_rows_returns_no_match_when_ctd_empty():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=pd.DataFrame(),
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches == [CtdMatch(status="no_match")]


def test_match_ctd_rows_marks_no_match_when_distance_above_tolerance():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T12:00:00Z"]), utc=True)
    ctd = _build_ctd(
        [
            {
                "latitude": 60.0,
                "longitude": -68.0,
                "time": "2020-01-01T12:00:00Z",
                "PRES": 5.0,
                "TE90": 1.0,
            }
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=ctd,
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].status == "no_match"


def test_match_ctd_rows_marks_no_match_when_outside_time_tolerance():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    ctd = _build_ctd(
        [
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-02-01T00:00:00Z",
                "PRES": 5.0,
                "TE90": 1.0,
            }
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=ctd,
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].status == "no_match"


def test_match_ctd_rows_returns_matched_with_distance_and_time_delta():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    ctd = _build_ctd(
        [
            {
                "latitude": 48.01,
                "longitude": -68.01,
                "time": "2020-01-01T01:00:00Z",
                "PRES": 5.0,
                "TE90": 1.5,
            }
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=ctd,
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].status == "matched"
    assert matches[0].chosen_idx == 0
    assert matches[0].distance_km is not None and matches[0].distance_km < 2.0
    assert matches[0].time_delta_min == pytest.approx(60.0)


def test_match_ctd_rows_picks_depth_closest_within_same_profile():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    src_depth = pd.Series([20.0])
    ctd = _build_ctd(
        [
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-01-01T00:00:00Z",
                "PRES": 5.0,
                "TE90": 1.0,
            },
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-01-01T00:00:00Z",
                "PRES": 25.0,
                "TE90": 2.0,
            },
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-01-01T00:00:00Z",
                "PRES": 50.0,
                "TE90": 3.0,
            },
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=src_depth,
        ctd=ctd,
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].chosen_idx == 1  # PRES=25 is closest to depth=20


def test_match_ctd_rows_downgrades_to_matched_no_value_when_all_variables_nan():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.to_datetime(pd.Series(["2020-01-01T00:00:00Z"]), utc=True)
    ctd = _build_ctd(
        [
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-01-01T00:00:00Z",
                "PRES": 5.0,
                "TE90": float("nan"),
                "PSAL": float("nan"),
            }
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=ctd,
        variables_for_value_check=["TE90", "PSAL"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].status == "matched_no_value"


def test_match_ctd_rows_handles_nat_source_time_by_accepting_any_ctd_time():
    src_lat = pd.Series([48.0])
    src_lon = pd.Series([-68.0])
    src_time = pd.Series([pd.NaT])
    ctd = _build_ctd(
        [
            {
                "latitude": 48.0,
                "longitude": -68.0,
                "time": "2020-01-01T00:00:00Z",
                "PRES": 5.0,
                "TE90": 1.0,
            }
        ]
    )
    matches = match_ctd_rows(
        src_lat=src_lat,
        src_lon=src_lon,
        src_time=src_time,
        src_depth=None,
        ctd=ctd,
        variables_for_value_check=["TE90"],
        spatial_tolerance_km=25.0,
        time_tolerance_hours=24.0,
    )
    assert matches[0].status == "matched"
    assert matches[0].time_delta_min is None
