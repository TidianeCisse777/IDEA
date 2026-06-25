"""Tests for core/enrich_scoping.py."""
from __future__ import annotations

import pandas as pd

from core.enrich_scoping import scope_dataframe


def _make_df():
    return pd.DataFrame(
        {
            "latitude": [73.0, 50.5, 75.0, 40.0],
            "longitude": [-65.0, -64.0, -70.0, -50.0],
            "deployment_datetime_start": [
                "2018-06-15T12:00:00Z",
                "2019-08-01T08:00:00Z",
                "2021-01-10T00:00:00Z",
                "2017-05-20T00:00:00Z",
            ],
        }
    )


def test_scope_dataframe_noop_when_no_filters():
    df = _make_df()
    result = scope_dataframe(df)
    assert len(result.df) == 4
    assert result.zone_canonical is None
    assert result.error is None


def test_scope_dataframe_filters_by_zone_baffin():
    df = _make_df()
    result = scope_dataframe(df, zone_name="Baie de Baffin")
    assert result.error is None
    assert result.zone_canonical == "Baie de Baffin"
    # 73.0/-65 and 75.0/-70 are in Baffin; the 50.5/40 ones aren't
    assert 1 <= len(result.df) <= 3


def test_scope_dataframe_filters_by_date_range():
    df = _make_df()
    result = scope_dataframe(
        df,
        date_range=["2018-01-01", "2020-12-31"],
        time_col="deployment_datetime_start",
    )
    assert result.error is None
    assert len(result.df) == 2  # 2018-06 and 2019-08


def test_scope_dataframe_filters_by_zone_and_date_combined():
    df = _make_df()
    result = scope_dataframe(
        df,
        zone_name="Baie de Baffin",
        date_range=["2018-01-01", "2020-12-31"],
        time_col="deployment_datetime_start",
    )
    assert result.error is None
    # Only the 2018-06-15 / (73.0, -65.0) row matches both filters
    assert len(result.df) == 1


def test_scope_dataframe_returns_error_on_unknown_zone():
    df = _make_df()
    result = scope_dataframe(df, zone_name="Mer Inexistante")
    assert result.error is not None
    assert "inconnue" in result.error.lower()


def test_scope_dataframe_returns_error_when_date_range_malformed():
    df = _make_df()
    result = scope_dataframe(
        df, date_range=["2018-01-01"], time_col="deployment_datetime_start"
    )
    assert result.error is not None


def test_scope_dataframe_returns_error_when_date_time_col_missing():
    df = _make_df()
    result = scope_dataframe(
        df, date_range=["2018-01-01", "2020-12-31"], time_col="missing_col"
    )
    assert result.error is not None
    assert "absente" in result.error.lower()


def test_scope_dataframe_description_lines_capture_both_filters():
    df = _make_df()
    result = scope_dataframe(
        df,
        zone_name="Baie de Baffin",
        date_range=["2018-01-01", "2020-12-31"],
        time_col="deployment_datetime_start",
    )
    joined = "\n".join(result.description_lines)
    assert "zone" in joined.lower()
    assert "date" in joined.lower()
