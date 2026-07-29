import pandas as pd

from core.ctd_filename_match import (
    CTD_FILENAME_MATCH_VERSION,
    ctd_filename_aliases,
    match_uvp_to_amundsen_ctd,
)


def _uvp():
    return pd.DataFrame({
        "sample_id": [101],
        "ctd_rosette_filename": ["062"],
        "station_id": ["324"],
        "lat_avg": [67.5],
        "lon_avg": [-63.8],
        "datetime_min": ["2023-09-02T08:28:25Z"],
    })


def _ctd(**overrides):
    values = {
        "filename": ["2309_062.int.nc"],
        "station": ["Station 324"],
        "cast_number": [62],
        "latitude": [67.501],
        "longitude": [-63.801],
        "time": ["2023-09-02T08:21:00Z"],
    }
    values.update(overrides)
    return pd.DataFrame(values)


def test_ctd_filename_aliases_preserve_terminal_rosette_number():
    assert "62" in ctd_filename_aliases("2309_062.int.nc")
    assert ctd_filename_aliases("062") & ctd_filename_aliases("2309_062.int.nc")


def test_filename_match_requires_station_time_and_position_validation():
    out = match_uvp_to_amundsen_ctd(_uvp(), _ctd())
    assert out.iloc[0]["uvp_sample_id"] == 101
    assert out.iloc[0]["amundsen_filename"] == "2309_062.int.nc"
    assert out.iloc[0]["match_status"] == "matched"
    assert out.iloc[0]["join_eligible"]
    assert out.iloc[0]["method_version"] == CTD_FILENAME_MATCH_VERSION


def test_filename_candidate_is_never_join_eligible_without_station_validation():
    out = match_uvp_to_amundsen_ctd(_uvp(), _ctd(station=["Station 999"]))
    assert out.iloc[0]["filename_match"]
    assert not out.iloc[0]["station_match"]
    assert out.iloc[0]["match_status"] == "filename_candidate"
    assert not out.iloc[0]["join_eligible"]
