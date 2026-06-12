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

    _store._store.clear()

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame(
            [
                {
                    "time": "2041-01-01T00:00:00Z",
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
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

    rows_json = (
        '[{"latitude":50.2,"longitude":-65.8,"variable":"thetao",'
        '"scenario":"SSP245","depth_layer":"depthsurf"}]'
    )

    with patch("tools.bio_oracle_sources._query_bio_oracle", side_effect=fake_query):
        tools = make_bio_oracle_tools("thread-3")
        couple = next(tool for tool in tools if tool.name == "couple_zooplankton_bio_oracle")
        result = couple.invoke({"rows_json": rows_json})

    assert _store.has("thread-3")
    assert "Couplage Bio-ORACLE chargé" in result
    keys = _store.keys("thread-3:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    assert _store.get(keys[0])["df"].shape == (1, 7)
