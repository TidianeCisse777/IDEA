"""Tests for core/canonical_grid.py."""
from __future__ import annotations

from core.canonical_grid import (
    canonicalize_amundsen_query,
    iter_arctic_tiles,
    iter_months,
    snap_bbox,
    snap_time_window,
)


def test_snap_bbox_aligns_to_5deg_grid():
    snapped = snap_bbox({"lat_min": 62.3, "lat_max": 67.1, "lon_min": -68.9, "lon_max": -65.1})
    assert snapped == {"lat_min": 60.0, "lat_max": 70.0, "lon_min": -70.0, "lon_max": -65.0}


def test_snap_bbox_already_aligned_is_idempotent():
    bbox = {"lat_min": 60.0, "lat_max": 65.0, "lon_min": -75.0, "lon_max": -70.0}
    assert snap_bbox(bbox) == bbox


def test_snap_time_window_to_month_start_and_next_month_start():
    snapped = snap_time_window({
        "start": "2018-08-15T12:00:00Z",
        "end": "2018-08-22T18:00:00Z",
    })
    assert snapped["start"] == "2018-08-01T00:00:00Z"
    assert snapped["end"] == "2018-09-01T00:00:00Z"


def test_snap_time_window_handles_december_rollover():
    snapped = snap_time_window({
        "start": "2018-12-05T00:00:00Z",
        "end": "2018-12-20T00:00:00Z",
    })
    assert snapped == {
        "start": "2018-12-01T00:00:00Z",
        "end": "2019-01-01T00:00:00Z",
    }


def test_snap_time_window_spanning_multiple_months_widens_to_full_range():
    snapped = snap_time_window({
        "start": "2020-03-15T00:00:00Z",
        "end": "2020-05-10T00:00:00Z",
    })
    assert snapped == {
        "start": "2020-03-01T00:00:00Z",
        "end": "2020-06-01T00:00:00Z",
    }


def test_two_nearby_source_bboxes_in_same_tile_produce_same_canonical_key():
    """Same arctic tile, different source coords → same cache key."""
    bbox_a = {"lat_min": 62.3, "lat_max": 62.8, "lon_min": -68.7, "lon_max": -68.2}
    bbox_b = {"lat_min": 63.1, "lat_max": 63.9, "lon_min": -69.5, "lon_max": -69.0}
    time_window = {"start": "2018-08-10T00:00:00Z", "end": "2018-08-15T00:00:00Z"}
    variables = ["PSAL", "TE90"]
    a = canonicalize_amundsen_query(bbox=bbox_a, time_window=time_window, variables=variables)
    b = canonicalize_amundsen_query(bbox=bbox_b, time_window=time_window, variables=variables)
    assert a == b


def test_canonical_variables_are_sorted():
    _, _, variables = canonicalize_amundsen_query(
        bbox={"lat_min": 60, "lat_max": 65, "lon_min": -70, "lon_max": -65},
        time_window={"start": "2018-08-01T00:00:00Z", "end": "2018-09-01T00:00:00Z"},
        variables=["TE90", "PSAL", "FLOR"],
    )
    assert variables == ["FLOR", "PSAL", "TE90"]


def test_iter_arctic_tiles_covers_default_zone():
    tiles = iter_arctic_tiles()
    assert len(tiles) == 7 * 25
    assert tiles[0] == {"lat_min": 50.0, "lat_max": 55.0, "lon_min": -170.0, "lon_max": -165.0}


def test_iter_months_inclusive_range():
    months = iter_months(2014, 7, 2014, 9)
    assert [(m["start"][:7]) for m in months] == ["2014-07", "2014-08", "2014-09"]
    assert months[-1]["end"] == "2014-10-01T00:00:00Z"
