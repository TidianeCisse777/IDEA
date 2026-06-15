"""TDD — tools/bio_oracle_sources.py."""


def test_make_bio_oracle_tools_exposes_expected_tools():
    from tools.bio_oracle_sources import make_bio_oracle_tools

    tools = make_bio_oracle_tools("thread-1")
    tool_names = {tool.name for tool in tools}

    assert "list_bio_oracle_datasets" in tool_names
    assert "preview_bio_oracle_point" in tool_names
    assert "query_bio_oracle" in tool_names
    assert "couple_zooplankton_bio_oracle" in tool_names


def test_query_bio_oracle_tool_stores_dataframe_and_returns_download_link(tmp_path):
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    _store._store.clear()

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame(
            [
                {
                    "time": "2041-01-01T00:00:00Z",
                    "latitude": 50.2,
                    "longitude": -65.8,
                    "thetao": 12.3,
                }
            ]
        )
        dataframe.to_csv(output_path, sep="\t", index=False)
        return {
            "dataset_id": "thetao_ssp245_2020_2100_depthsurf",
            "title": "Bio-Oracle Temperature [depthSurf] SSP245 2020-2100",
            "file_path": str(output_path),
            "download_url": str(output_path),
            "row_count": 1,
        }

    with patch("tools.bio_oracle_sources._query_bio_oracle", side_effect=fake_query):
        tools = make_bio_oracle_tools("thread-2")
        query = next(tool for tool in tools if tool.name == "query_bio_oracle")
        result = query.invoke(
            {
                "latitude": 50.2,
                "longitude": -65.8,
                "variable": "thetao",
                "scenario": "SSP245",
                "depth_layer": "depthsurf",
            }
        )

    assert _store.has("thread-2")
    assert "Télécharger :" in result


def test_query_bio_oracle_preserves_distinct_queries():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-multi-bio-oracle"

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame([{"latitude": parameters["latitude"], "thetao": 12.3}])
        dataframe.to_csv(output_path, sep="\t", index=False)
        return {
            "dataset_id": "thetao_ssp245_2020_2100_depthsurf",
            "title": "Bio-ORACLE",
            "file_path": str(output_path),
            "download_url": str(output_path),
            "row_count": 1,
        }

    with patch("tools.bio_oracle_sources._query_bio_oracle", side_effect=fake_query):
        query = next(t for t in make_bio_oracle_tools(thread_id) if t.name == "query_bio_oracle")
        result_50 = query.invoke({
            "latitude": 50.2,
            "longitude": -65.8,
            "variable": "thetao",
            "scenario": "SSP245",
            "depth_layer": "depthsurf",
        })
        result_51 = query.invoke({
            "latitude": 51.2,
            "longitude": -65.8,
            "variable": "thetao",
            "scenario": "SSP245",
            "depth_layer": "depthsurf",
        })

    name_50 = "df_bio_oracle_thetao_ssp245_depthsurf_50_2_m65_8"
    name_51 = "df_bio_oracle_thetao_ssp245_depthsurf_51_2_m65_8"
    assert _store.get(f"{thread_id}:dataset:{name_50}")["df"]["latitude"].iloc[0] == 50.2
    assert _store.get(f"{thread_id}:dataset:{name_51}")["df"]["latitude"].iloc[0] == 51.2
    assert _store.get(f"{thread_id}:bio_oracle")["df"]["latitude"].iloc[0] == 51.2
    assert name_50 in result_50
    assert name_51 in result_51


def test_couple_zooplankton_bio_oracle_tool_persists_coupled_rows():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-3"
    source = pd.DataFrame(
        [
            {
                "station": "IML4",
                "latitude": 48.7,
                "longitude": -68.5,
                "sample_date": "2024-06-01",
                "abundance": 120,
            },
            {
                "station": "RIMOUSKI",
                "latitude": 48.5,
                "longitude": -68.3,
                "sample_date": "2024-06-02",
                "abundance": 95,
            },
            {
                "station": "IML4-repeat",
                "latitude": 48.7,
                "longitude": -68.5,
                "sample_date": "2024-06-03",
                "abundance": 80,
            },
        ]
    )
    for key in _store.keys(thread_id):
        _store.clear(key)
    _store.set(thread_id, source, {"source": "uploaded_file"})
    preview_calls = []

    def fake_preview(parameters):
        preview_calls.append(parameters)
        return {
            "dataset_id": "thetao_ssp245_2020_2100_depthsurf",
            "title": "Bio-Oracle Temperature [depthSurf] SSP245 2020-2100",
            "variable": "thetao",
            "rows": [
                {
                    "time": "2041-01-01T00:00:00Z",
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": parameters["latitude"],
                }
            ],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        tools = make_bio_oracle_tools(thread_id)
        couple = next(tool for tool in tools if tool.name == "couple_zooplankton_bio_oracle")
        result = couple.invoke(
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "thetao",
                "scenario": "SSP245",
                "depth_layer": "depthsurf",
            }
        )

    assert "Couplage Bio-ORACLE chargé" in result
    assert {
        (call["latitude"], call["longitude"]) for call in preview_calls
    } == {(48.7, -68.5), (48.5, -68.3)}
    assert len(preview_calls) == 2
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    df_coupled = _store.get(keys[0])["df"]
    assert len(df_coupled) == len(source)
    assert set(source.columns) <= set(df_coupled.columns)
    pd.testing.assert_frame_equal(
        df_coupled.loc[:, source.columns].reset_index(drop=True),
        source.reset_index(drop=True),
    )
    assert "thetao_ssp245" in df_coupled.columns
    assert df_coupled["thetao_ssp245"].tolist() == [48.7, 48.5, 48.7]
