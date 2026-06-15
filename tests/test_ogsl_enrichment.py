"""Tests for large-file OGSL planning and matching."""


def test_build_station_windows_scales_with_unique_stations():
    import pandas as pd

    from core.ogsl_enrichment import build_station_windows

    source = pd.DataFrame({
        "station": ["02M"] * 5000 + ["05M"] * 5000,
        "sample_time": (
            ["2022-10-09T22:03:37Z"] * 2500
            + ["2022-10-10T02:03:37Z"] * 2500
            + ["2023-01-05T12:00:00Z"] * 5000
        ),
    })

    windows, parsed_time = build_station_windows(
        source,
        station_column="station",
        time_column="sample_time",
        tolerance_hours=24,
    )

    assert len(windows) == 2
    assert windows[0] == {
        "station": "02M",
        "start": "2022-10-08T22:03:37Z",
        "end": "2022-10-11T02:03:37Z",
    }
    assert windows[1] == {
        "station": "05M",
        "start": "2023-01-04T12:00:00Z",
        "end": "2023-01-06T12:00:00Z",
    }
    assert parsed_time.notna().all()


def test_enrich_ogsl_uses_nearest_time_and_pressure():
    import pandas as pd
    import pytest

    from core.ogsl_enrichment import enrich_with_ogsl

    source = pd.DataFrame([{
        "station": "02M",
        "sample_time": "2022-10-09T22:04:00Z",
        "depth": 8.0,
        "abundance": 120,
    }])
    ogsl = pd.DataFrame([
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 1.0,
            "TE90": 4.75,
            "cruiseID": "cruise-a",
            "cast_number": 4,
        },
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 8.0,
            "TE90": 4.20,
            "cruiseID": "cruise-a",
            "cast_number": 4,
        },
    ])

    result = enrich_with_ogsl(
        source,
        ogsl,
        station_column="station",
        time_column="sample_time",
        depth_column="depth",
        variables=["PRES", "TE90"],
        time_tolerance_hours=24,
        depth_tolerance_m=10,
    )

    assert result["ogsl_te90"].tolist() == [4.20]
    assert result["ogsl_time_delta_min"].iloc[0] == pytest.approx(23 / 60)
    assert result["ogsl_depth_delta_m"].tolist() == [0.0]
    assert result["ogsl_match_status"].tolist() == ["matched"]


def test_enrich_ogsl_uses_surface_when_depth_is_absent():
    import pandas as pd

    from core.ogsl_enrichment import enrich_with_ogsl

    source = pd.DataFrame([{
        "station": "02M",
        "sample_time": "2022-10-09T22:04:00Z",
    }])
    ogsl = pd.DataFrame([
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 8.0,
            "TE90": 4.20,
        },
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 1.0,
            "TE90": 4.75,
        },
    ])

    result = enrich_with_ogsl(
        source,
        ogsl,
        station_column="station",
        time_column="sample_time",
        depth_column=None,
        variables=["PRES", "TE90"],
        time_tolerance_hours=24,
        depth_tolerance_m=10,
    )

    assert result["ogsl_pres"].tolist() == [1.0]
    assert result["ogsl_te90"].tolist() == [4.75]
    assert result["ogsl_match_status"].tolist() == ["matched"]


def test_enrich_ogsl_preserves_invalid_and_unmatched_rows():
    import pandas as pd

    from core.ogsl_enrichment import enrich_with_ogsl

    source = pd.DataFrame([
        {"station": None, "sample_time": "2022-10-09T22:04:00Z", "depth": 8},
        {"station": "02M", "sample_time": "not-a-date", "depth": 8},
        {"station": "02M", "sample_time": "2022-10-20T22:04:00Z", "depth": 8},
        {"station": "02M", "sample_time": "2022-10-09T22:04:00Z", "depth": None},
    ], index=[10, 20, 30, 40])
    ogsl = pd.DataFrame([{
        "stationID": "02M",
        "time": "2022-10-09T22:03:37Z",
        "PRES": 8.0,
        "TE90": 4.20,
    }])

    result = enrich_with_ogsl(
        source,
        ogsl,
        station_column="station",
        time_column="sample_time",
        depth_column="depth",
        variables=["PRES", "TE90"],
        time_tolerance_hours=24,
        depth_tolerance_m=10,
    )

    assert result["ogsl_match_status"].tolist() == [
        "missing_station",
        "invalid_time",
        "no_match",
        "missing_depth",
    ]
    assert len(result) == len(source)
    assert result.index.tolist() == source.index.tolist()
    assert set(source.columns) <= set(result.columns)
