"""Tests for the OGSL ERDDAP client."""


def test_query_ogsl_fetches_each_unique_station_and_combines_rows(tmp_path):
    from unittest.mock import Mock, patch

    import pandas as pd

    from core.ogsl_client import query_ogsl

    responses = [
        Mock(
            status_code=200,
            text="stationID (unitless),TE90 (degree_C)\nIML4,4.2\n",
            raise_for_status=Mock(),
        ),
        Mock(
            status_code=200,
            text="stationID (unitless),TE90 (degree_C)\nRIMOUSKI,4.4\n",
            raise_for_status=Mock(),
        ),
    ]
    output_path = tmp_path / "ogsl.csv"

    with patch("core.ogsl_client.requests.get", side_effect=responses) as get:
        result = query_ogsl(
            {
                "stations": ["IML4", "RIMOUSKI", "IML4"],
                "variables": ["TE90"],
                "start": "2024-06-01",
                "end": "2024-06-30",
            },
            output_path=output_path,
        )

    assert get.call_count == 2
    assert "stationID=%22IML4%22" in get.call_args_list[0].args[0]
    assert "time>=2024-06-01" in get.call_args_list[0].args[0]
    assert result["row_count"] == 2
    dataframe = pd.read_csv(output_path)
    assert dataframe.columns.tolist() == ["stationID", "TE90"]
    assert dataframe["stationID"].tolist() == ["IML4", "RIMOUSKI"]


def test_query_ogsl_uses_station_specific_windows(tmp_path):
    from unittest.mock import Mock, patch

    from core.ogsl_client import query_ogsl

    response = Mock(
        status_code=200,
        text="stationID (unitless),TE90 (degree_C)\n02M,4.2\n",
        raise_for_status=Mock(),
    )
    windows = [
        {
            "station": "02M",
            "start": "2022-10-08T22:00:00Z",
            "end": "2022-10-10T22:00:00Z",
        },
        {
            "station": "05M",
            "start": "2023-01-04T12:00:00Z",
            "end": "2023-01-06T12:00:00Z",
        },
    ]

    with patch(
        "core.ogsl_client.requests.get",
        side_effect=[response, response],
    ) as get:
        query_ogsl(
            {"station_windows": windows, "variables": ["TE90"]},
            output_path=tmp_path / "ogsl.csv",
        )

    first_url = get.call_args_list[0].args[0]
    second_url = get.call_args_list[1].args[0]
    assert "stationID=%2202M%22" in first_url
    assert "time>=2022-10-08T22%3A00%3A00Z" in first_url
    assert "stationID=%2205M%22" in second_url
    assert "time>=2023-01-04T12%3A00%3A00Z" in second_url
