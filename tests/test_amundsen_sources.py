"""TDD — tools/amundsen_sources.py."""


def test_make_amundsen_tools_exposes_expected_tools():
    from tools.amundsen_sources import make_amundsen_tools

    tools = make_amundsen_tools("thread-1")
    tool_names = {tool.name for tool in tools}

    assert "list_amundsen_datasets" in tool_names
    assert "preview_amundsen_profile" in tool_names
    assert "query_amundsen_ctd" in tool_names


def test_query_amundsen_ctd_tool_stores_dataframe_and_returns_download_link():
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame(
            [
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.1,
                    "longitude": -80.2,
                    "station": "BRK-15",
                    "cast_number": 7,
                    "Pres": 12.0,
                    "Temp": -1.2,
                    "Sal": 31.4,
                    "profile_id": "BRK-15-7",
                    "station_id": "BRK-15",
                    "cast_id": 7,
                }
            ]
        )
        dataframe.to_csv(output_path, sep="\t", index=False)
        return {
            "dataset_id": "amundsen12713",
            "title": "CTD data collected by the CCGS Amundsen in the Canadian Arctic",
            "file_path": str(output_path),
            "download_url": f"http://localhost:8000/downloads/{output_path.name}",
            "row_count": 1,
        }

    with patch("tools.amundsen_sources._query_amundsen_ctd", side_effect=fake_query):
        tools = make_amundsen_tools("thread-2")
        query = next(tool for tool in tools if tool.name == "query_amundsen_ctd")
        result = query.invoke({"station": "BRK-15", "cast_number": 7})

    assert _store.has("thread-2")
    assert "Amundsen CTD chargé" in result
    assert "Télécharger :" in result


def test_query_amundsen_ctd_preserves_distinct_profiles():
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-multi-amundsen"

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame([{"station": parameters["station"], "cast_number": parameters["cast_number"]}])
        dataframe.to_csv(output_path, sep="\t", index=False)
        return {
            "dataset_id": "amundsen12713",
            "title": "Amundsen CTD",
            "file_path": str(output_path),
            "download_url": f"http://localhost:8000/downloads/{output_path.name}",
            "row_count": 1,
        }

    with patch("tools.amundsen_sources._query_amundsen_ctd", side_effect=fake_query):
        query = next(t for t in make_amundsen_tools(thread_id) if t.name == "query_amundsen_ctd")
        result_7 = query.invoke({"station": "BRK-15", "cast_number": 7})
        result_8 = query.invoke({"station": "BRK-15", "cast_number": 8})

    name_7 = "df_amundsen_amundsen12713_brk_15_cast_7"
    name_8 = "df_amundsen_amundsen12713_brk_15_cast_8"
    assert _store.get(f"{thread_id}:dataset:{name_7}")["df"]["cast_number"].iloc[0] == 7
    assert _store.get(f"{thread_id}:dataset:{name_8}")["df"]["cast_number"].iloc[0] == 8
    assert _store.get(f"{thread_id}:ctd")["df"]["cast_number"].iloc[0] == 8
    assert name_7 in result_7
    assert name_8 in result_8
