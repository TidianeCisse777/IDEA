"""TDD — tools/amundsen_sources.py."""

import pytest


@pytest.fixture(autouse=True)
def _clear_amundsen_dataset_cache():
    from core.amundsen_ctd_client import clear_amundsen_dataset_cache

    clear_amundsen_dataset_cache()
    yield
    clear_amundsen_dataset_cache()


def test_make_amundsen_tools_exposes_expected_tools():
    from tools.amundsen_sources import make_amundsen_tools

    tools = make_amundsen_tools("thread-1")
    tool_names = {tool.name for tool in tools}

    assert "list_amundsen_datasets" in tool_names
    assert "preview_amundsen_profile" in tool_names
    assert "query_amundsen_ctd" in tool_names
    assert "enrich_loaded_table_with_amundsen_ctd" in tool_names


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


def test_enrich_loaded_table_with_amundsen_ctd_reports_missing_metadata_for_ecopart_file():
    import pandas as pd

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-enrich-missing-metadata"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "Profile": ["hc_02_030924", "hc_03_030924"],
            "yyyy-mm-dd hh:mm": ["2024-09-03 10:00", "2024-09-03 11:00"],
            "Depth [m]": [10.0, 25.0],
            "Sampled volume [L]": [100.0, 95.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:ecopart_hawkechannel_30jan.tsv"})

    enrich = next(
        tool for tool in make_amundsen_tools(thread_id)
        if tool.name == "enrich_loaded_table_with_amundsen_ctd"
    )
    result = enrich.invoke(
        {
            "time_column": "yyyy-mm-dd hh:mm",
            "depth_column": "Depth [m]",
            "profile_column": "Profile",
        }
    )

    assert "missing_sample_metadata" in result
    assert "station/cast ou latitude/longitude/temps manquants" in result
    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    assert len(keys) == 1
    enriched = _store.get(keys[0])["df"]
    assert len(enriched) == len(source)
    assert enriched["ctd_match_status"].tolist() == [
        "missing_sample_metadata",
        "missing_sample_metadata",
    ]
    assert "latitude" in enriched["ctd_missing_columns"].iloc[0]
    assert "longitude" in enriched["ctd_missing_columns"].iloc[0]
    assert "station" in enriched["ctd_missing_columns"].iloc[0]
    assert "cast_number" in enriched["ctd_missing_columns"].iloc[0]
    assert enriched["ctd_profile_key"].tolist() == ["hc_02_030924", "hc_03_030924"]


def test_enrich_loaded_table_with_amundsen_ctd_matches_by_station_cast_and_depth(tmp_path):
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-enrich-station-cast"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "station": ["HC-02", "HC-02"],
            "cast_number": [3, 3],
            "Depth [m]": [8.0, 21.0],
            "Profile": ["hc_02_surface", "hc_02_deep"],
        }
    )
    _store.set(thread_id, source, {"source": "file:ecopart_with_station_cast.tsv"})

    def fake_query(parameters, output_path=None):
        dataframe = pd.DataFrame(
            [
                {
                    "time": "2024-09-03T10:00:00Z",
                    "latitude": 54.2,
                    "longitude": -55.1,
                    "station": parameters["station"],
                    "cast_number": parameters["cast_number"],
                    "Pres": 10.0,
                    "TE90": 2.1,
                    "PSAL": 31.0,
                },
                {
                    "time": "2024-09-03T10:02:00Z",
                    "latitude": 54.2,
                    "longitude": -55.1,
                    "station": parameters["station"],
                    "cast_number": parameters["cast_number"],
                    "Pres": 20.0,
                    "TE90": 1.5,
                    "PSAL": 32.0,
                },
            ]
        )
        output = tmp_path / f"{parameters['station']}_{parameters['cast_number']}.tsv"
        dataframe.to_csv(output, sep="\t", index=False)
        return {
            "dataset_id": "amundsen12713",
            "title": "Amundsen CTD",
            "file_path": str(output),
            "download_url": str(output),
            "row_count": len(dataframe),
        }

    with patch("tools.amundsen_sources._query_amundsen_ctd", side_effect=fake_query):
        enrich = next(
            tool for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_loaded_table_with_amundsen_ctd"
        )
        result = enrich.invoke(
            {
                "station_column": "station",
                "cast_column": "cast_number",
                "depth_column": "Depth [m]",
            }
        )

    assert "2 matchées" in result
    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    assert len(keys) == 1
    enriched = _store.get(keys[0])["df"]
    assert enriched["ctd_match_status"].tolist() == ["matched", "matched"]
    assert enriched["amundsen_nearest_depth_m"].tolist() == [10.0, 20.0]
    assert enriched["amundsen_temperature_degC_nearest"].tolist() == [2.1, 1.5]
    assert enriched["amundsen_nearest_lat"].tolist() == [54.2, 54.2]
