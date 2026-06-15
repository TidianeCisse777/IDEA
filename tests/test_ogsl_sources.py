"""Tests for the LangChain OGSL tools."""


def test_query_ogsl_stores_dataframe_under_ogsl_alias(tmp_path):
    import pandas as pd
    from unittest.mock import patch

    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as store

    thread_id = "thread-ogsl-query"
    for key in store.keys(thread_id):
        store.clear(key)
    store.set(
        thread_id,
        pd.DataFrame({
            "station": ["IML4", "RIMOUSKI", "IML4"],
            "sample_time": [
                "2024-06-01T00:00:00Z",
                "2024-06-02T00:00:00Z",
                "2024-06-01T00:05:00Z",
            ],
        }),
        {"source": "uploaded_file"},
    )

    def fake_query(parameters, output_path):
        assert [item["station"] for item in parameters["station_windows"]] == [
            "IML4",
            "RIMOUSKI",
        ]
        dataframe = pd.DataFrame(
            [
                {
                    "stationID": "IML4",
                    "time": "2024-06-01T00:00:00Z",
                    "latitude": 48.7,
                    "longitude": -68.5,
                    "PRES": 5.0,
                    "TE90": 4.2,
                },
                {
                    "stationID": "RIMOUSKI",
                    "time": "2024-06-02T00:00:00Z",
                    "latitude": 48.5,
                    "longitude": -68.3,
                    "PRES": 6.0,
                    "TE90": 4.4,
                },
            ]
        )
        dataframe.to_csv(output_path, index=False)
        return {
            "dataset_id": "ismerSgdeCtd",
            "download_url": str(output_path),
            "row_count": 1,
        }

    with patch("tools.ogsl_sources._query_ogsl", side_effect=fake_query):
        query = next(
            tool
            for tool in make_ogsl_tools(thread_id)
            if tool.name == "query_ogsl"
        )
        result = query.invoke({
            "station_column": "station",
            "time_column": "sample_time",
            "variables": ["PRES", "TE90"],
        })

    assert "OGSL loaded" in result
    entry = store.get(f"{thread_id}:ogsl")
    assert entry is not None
    assert entry["meta"]["dataset_id"] == "ismerSgdeCtd"
    assert entry["df"]["stationID"].tolist() == ["IML4", "RIMOUSKI"]
    assert entry["df"]["TE90"].tolist() == [4.2, 4.4]


def test_query_ogsl_enriches_large_file_with_one_window_per_station():
    import pandas as pd
    from unittest.mock import patch

    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as store

    thread_id = "thread-ogsl-large"
    for key in store.keys(thread_id):
        store.clear(key)
    source = pd.DataFrame({
        "station": ["02M"] * 5000 + ["05M"] * 5000,
        "sample_time": (
            ["2022-10-09T22:03:37Z"] * 5000
            + ["2023-01-05T12:00:00Z"] * 5000
        ),
        "abundance": range(10_000),
    })
    original = source.copy(deep=True)
    store.set(thread_id, source, {"source": "uploaded_file"})

    def fake_query(parameters, output_path):
        assert parameters["station_windows"] == [
            {
                "station": "02M",
                "start": "2022-10-08T22:03:37Z",
                "end": "2022-10-10T22:03:37Z",
            },
            {
                "station": "05M",
                "start": "2023-01-04T12:00:00Z",
                "end": "2023-01-06T12:00:00Z",
            },
        ]
        dataframe = pd.DataFrame([
            {
                "stationID": "02M",
                "time": "2022-10-09T22:03:37Z",
                "PRES": 1.0,
                "TE90": 4.2,
            },
            {
                "stationID": "05M",
                "time": "2023-01-05T12:00:00Z",
                "PRES": 1.0,
                "TE90": 3.8,
            },
        ])
        dataframe.to_csv(output_path, index=False)
        return {
            "dataset_id": "ismerSgdeCtd",
            "download_url": str(output_path),
            "row_count": 2,
        }

    with patch("tools.ogsl_sources._query_ogsl", side_effect=fake_query):
        query = next(
            tool
            for tool in make_ogsl_tools(thread_id)
            if tool.name == "query_ogsl"
        )
        result = query.invoke({
            "station_column": "station",
            "time_column": "sample_time",
            "variables": ["PRES", "TE90"],
        })

    pd.testing.assert_frame_equal(source, original)
    assert "2 station requests" in result
    assert store.get(f"{thread_id}:ogsl") is not None
    enriched_keys = store.keys(f"{thread_id}:dataset:df_ogsl_enriched_")
    assert len(enriched_keys) == 1
    enriched = store.get(enriched_keys[0])["df"]
    assert len(enriched) == 10_000
    assert set(original.columns) <= set(enriched.columns)
    assert set(enriched["ogsl_match_status"]) == {"matched"}


def test_query_ogsl_requires_confirmation_above_ten_unique_stations():
    import pandas as pd
    from unittest.mock import patch

    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as store

    thread_id = "thread-ogsl-confirmation"
    for key in store.keys(thread_id):
        store.clear(key)
    store.set(
        thread_id,
        pd.DataFrame({
            "station": [f"S{i:02d}" for i in range(11)],
            "sample_time": ["2024-06-01T00:00:00Z"] * 11,
        }),
        {"source": "uploaded_file"},
    )

    with patch("tools.ogsl_sources._query_ogsl") as remote_query:
        query = next(
            tool
            for tool in make_ogsl_tools(thread_id)
            if tool.name == "query_ogsl"
        )
        result = query.invoke({
            "station_column": "station",
            "time_column": "sample_time",
        })

    remote_query.assert_not_called()
    assert "Confirmation required" in result
    assert "11 unique stations" in result
    assert "confirmed=true" in result
