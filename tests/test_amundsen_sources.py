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


def test_enrich_with_amundsen_ctd_matches_by_lat_lon_time():
    """Tracer bullet — fichier avec seulement lat/lon/time doit s'enrichir Amundsen.

    Cas EcoTaxa typique : pas de station, pas de cast_number, seulement les
    coordonnées et la date. Le nouveau tool doit interroger Amundsen par
    bbox+fenêtre temps puis matcher localement au plus proche voisin.
    """
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-latlon-tracer"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [74.10],
            "longitude": [-80.20],
            "object_date": ["2013-08-01"],
        }
    )
    _store.set(thread_id, source, {"source": "file:ecotaxa_sample.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.10,
                    "longitude": -80.20,
                    "station": "BRK-15",
                    "cast_number": 7,
                    "PRES": 2.0,
                    "TE90": -1.2,
                    "PSAL": 31.4,
                }
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        result = enrich.invoke({})

    assert "1 matchée" in result
    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    assert len(keys) == 1
    enriched = _store.get(keys[0])["df"]
    assert enriched["amundsen_match_status"].tolist() == ["matched"]
    assert enriched["amundsen_te90_degC"].tolist() == [-1.2]
    assert enriched["amundsen_psal_psu"].tolist() == [31.4]
    assert enriched["amundsen_station"].tolist() == ["BRK-15"]
    assert enriched["amundsen_dataset_id"].tolist() == ["amundsen12713"]


def test_enrich_with_amundsen_ctd_matches_each_row_to_its_nearest_profile():
    """Multi-lignes : chaque ligne source matche son profil CTD le plus proche."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-multi-nearest"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [74.10, 70.00],
            "longitude": [-80.20, -65.00],
            "object_date": ["2013-08-01", "2013-08-02"],
        }
    )
    _store.set(thread_id, source, {"source": "file:multi.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.11,
                    "longitude": -80.18,
                    "station": "NORTH",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.2,
                    "PSAL": 31.4,
                },
                {
                    "time": "2013-08-02T12:00:00Z",
                    "latitude": 70.02,
                    "longitude": -65.05,
                    "station": "SOUTH",
                    "cast_number": 2,
                    "PRES": 2.5,
                    "TE90": 3.1,
                    "PSAL": 32.5,
                },
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["amundsen_station"].tolist() == ["NORTH", "SOUTH"]
    assert enriched["amundsen_te90_degC"].tolist() == [-1.2, 3.1]


def test_enrich_with_amundsen_ctd_reports_no_match_when_point_is_far():
    """Point hors tolérance spatiale → status `no_match`, pas de valeur CTD."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-far"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [0.0],
            "longitude": [0.0],
            "object_date": ["2013-08-01"],
        }
    )
    _store.set(thread_id, source, {"source": "file:atlantic_equator.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.0,
                    "longitude": -80.0,
                    "station": "ARCTIC",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.5,
                    "PSAL": 32.0,
                }
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({"spatial_tolerance_km": 25})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["amundsen_match_status"].tolist() == ["no_match"]
    assert pd.isna(enriched["amundsen_te90_degC"].iloc[0])
    assert pd.isna(enriched["amundsen_station"].iloc[0])


def test_enrich_with_amundsen_ctd_diagnoses_missing_coordinates():
    """Table sans lat/lon/time : retour explicite, pas d'appel ERDDAP, pas d'exception."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-missing-coords"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame({"Profile": ["A", "B"], "Sampled volume [L]": [100, 95]})
    _store.set(thread_id, source, {"source": "file:no_coords.tsv"})

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox"
    ) as mock_fetch:
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        result = enrich.invoke({})

    mock_fetch.assert_not_called()
    assert "coordonnées" in result.lower() or "latitude" in result.lower()


def test_enrich_with_amundsen_ctd_emits_single_bbox_call_for_n_points():
    """Le tool calcule la bbox+fenêtre depuis la source et fait UN seul appel ERDDAP."""
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-bbox-single"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [74.0, 74.5, 73.8, 74.2],
            "longitude": [-80.0, -79.5, -80.4, -80.1],
            "object_date": [
                "2013-08-01",
                "2013-08-02",
                "2013-08-03",
                "2013-08-04",
            ],
        }
    )
    _store.set(thread_id, source, {"source": "file:bbox.tsv"})

    fetch_mock = MagicMock(
        return_value=pd.DataFrame(
            [
                {
                    "time": "2013-08-02T12:00:00Z",
                    "latitude": 74.1,
                    "longitude": -80.1,
                    "station": "S1",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.0,
                    "PSAL": 31.0,
                }
            ]
        )
    )
    with patch("tools.amundsen_sources._fetch_amundsen_bbox", fetch_mock):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({})

    assert fetch_mock.call_count == 1
    kwargs = fetch_mock.call_args.kwargs
    bbox = kwargs["bbox"]
    assert bbox["lat_min"] <= 73.8 and bbox["lat_max"] >= 74.5
    assert bbox["lon_min"] <= -80.4 and bbox["lon_max"] >= -79.5
    time_window = kwargs["time_window"]
    assert time_window["start"] <= "2013-08-01"
    assert time_window["end"] >= "2013-08-04"


def test_fetch_amundsen_bbox_queries_erddap_with_bbox_and_time_constraints():
    """_fetch_amundsen_bbox construit la requête ERDDAP tabledap correcte."""
    from unittest.mock import MagicMock, patch

    from tools.amundsen_sources import _fetch_amundsen_bbox

    csv_body = (
        "time,latitude,longitude,station,cast_number,PRES,TE90,PSAL\n"
        "UTC,degrees_north,degrees_east,,count,dbar,degree_C,1\n"
        "2013-08-01T12:00:00Z,74.10,-80.20,BRK-15,7,2.0,-1.2,31.4\n"
    )
    response = MagicMock(status_code=200, text=csv_body)
    response.raise_for_status = MagicMock()

    with patch("tools.amundsen_sources.requests.get", return_value=response) as mock_get:
        dataframe = _fetch_amundsen_bbox(
            bbox={
                "lat_min": 73.85,
                "lat_max": 74.35,
                "lon_min": -80.45,
                "lon_max": -79.95,
            },
            time_window={
                "start": "2013-07-31T12:00:00Z",
                "end": "2013-08-02T12:00:00Z",
            },
            variables=["TE90", "PSAL"],
        )

    assert mock_get.called
    url = mock_get.call_args.args[0]
    assert "amundsen12713.csv" in url
    assert "latitude%3E%3D73.85" in url or "latitude>=73.85" in url
    assert "TE90" in url and "PSAL" in url
    assert "2013-07-31" in url and "2013-08-02" in url
    assert dataframe.iloc[0]["station"] == "BRK-15"
    assert float(dataframe.iloc[0]["TE90"]) == -1.2


def test_enrich_with_amundsen_ctd_matches_depth_within_profile():
    """Quand la source a une profondeur, on choisit la mesure CTD à cette profondeur."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-depth-match"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [74.10, 74.10],
            "longitude": [-80.20, -80.20],
            "object_date": ["2013-08-01", "2013-08-01"],
            "object_depth_min": [5.0, 50.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:depth.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.10,
                    "longitude": -80.20,
                    "station": "BRK-15",
                    "cast_number": 7,
                    "PRES": 2.0,
                    "TE90": -1.0,
                    "PSAL": 30.0,
                },
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.10,
                    "longitude": -80.20,
                    "station": "BRK-15",
                    "cast_number": 7,
                    "PRES": 50.0,
                    "TE90": 1.5,
                    "PSAL": 33.5,
                },
                {
                    "time": "2013-08-01T12:00:00Z",
                    "latitude": 74.10,
                    "longitude": -80.20,
                    "station": "BRK-15",
                    "cast_number": 7,
                    "PRES": 200.0,
                    "TE90": 0.2,
                    "PSAL": 34.5,
                },
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["amundsen_match_status"].tolist() == ["matched", "matched"]
    assert enriched["amundsen_te90_degC"].tolist() == [-1.0, 1.5]
    assert enriched["amundsen_pres_dbar"].tolist() == [2.0, 50.0]


def test_enrich_with_amundsen_ctd_filters_candidates_outside_time_tolerance():
    """Un profil très proche en espace mais hors fenêtre temps ne doit pas matcher."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-time-tol"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [74.10],
            "longitude": [-80.20],
            "object_date": ["2013-08-01T12:00:00Z"],
        }
    )
    _store.set(thread_id, source, {"source": "file:tt.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        # Le client a renvoyé large : un profil dans la fenêtre + un profil
        # 10 jours plus tard, plus proche spatialement.
        return pd.DataFrame(
            [
                {
                    "time": "2013-08-01T11:30:00Z",
                    "latitude": 74.11,
                    "longitude": -80.21,
                    "station": "ON_TIME",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.0,
                    "PSAL": 31.0,
                },
                {
                    "time": "2013-08-11T11:30:00Z",
                    "latitude": 74.10,
                    "longitude": -80.20,
                    "station": "LATE",
                    "cast_number": 2,
                    "PRES": 2.0,
                    "TE90": 5.0,
                    "PSAL": 33.0,
                },
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({"time_tolerance_hours": 24})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["amundsen_station"].tolist() == ["ON_TIME"]
    assert enriched["amundsen_te90_degC"].tolist() == [-1.0]


def test_system_prompt_prefers_enrich_with_amundsen_ctd_for_latlon_files():
    """Le routage doit guider le LLM vers le nouveau tool lat/lon/time."""
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT
    assert "enrich_with_amundsen_ctd" in prompt
    lowered = prompt.lower()
    assert "latitude" in lowered and "longitude" in lowered
    new_idx = prompt.find("enrich_with_amundsen_ctd")
    old_idx = prompt.find("enrich_loaded_table_with_amundsen_ctd")
    assert new_idx != -1
    assert new_idx < old_idx or old_idx == -1


def test_enrich_with_amundsen_ctd_exposes_distance_and_time_delta_columns():
    """Audit : chaque ligne matchée expose la distance et le delta temps réels."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-metrics"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [60.0],
            "longitude": [-65.0],
            "object_date": ["2018-05-31T12:00:00Z"],
        }
    )
    _store.set(thread_id, source, {"source": "file:m.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        # CTD à ~110 km au nord du point source, 6 h plus tard
        return pd.DataFrame(
            [
                {
                    "time": "2018-05-31T18:00:00Z",
                    "latitude": 61.0,
                    "longitude": -65.0,
                    "station": "S",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.0,
                    "PSAL": 32.0,
                }
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({"spatial_tolerance_km": 200})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert "amundsen_distance_km" in enriched.columns
    assert "amundsen_time_delta_min" in enriched.columns
    assert 100 <= float(enriched["amundsen_distance_km"].iloc[0]) <= 115
    assert 355 <= float(enriched["amundsen_time_delta_min"].iloc[0]) <= 365


def test_enrich_with_amundsen_ctd_reports_matched_no_value_when_variables_are_nan():
    """Profil trouvé mais variables NaN → statut `matched_no_value`, pas `matched`."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-no-value"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [70.5],
            "longitude": [-64.0],
            "object_date": ["2016-07-03"],
        }
    )
    _store.set(thread_id, source, {"source": "file:no_value.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2016-07-03T12:00:00Z",
                    "latitude": 70.5,
                    "longitude": -64.0,
                    "station": "G600",
                    "cast_number": 1,
                    "PRES": 1.0,
                    "TE90": float("nan"),
                    "PSAL": float("nan"),
                }
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({})

    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["amundsen_match_status"].tolist() == ["matched_no_value"]
    assert enriched["amundsen_station"].tolist() == ["G600"]


def test_enrich_with_amundsen_ctd_returns_method_transparency_block():
    """La réponse doit expliciter les colonnes détectées, les tolérances et le mix de statuts."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-method"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [60.0, 61.0, 0.0],
            "longitude": [-65.0, -65.0, 0.0],
            "object_date": ["2018-05-31", "2018-05-31", "2018-05-31"],
            "object_depth_min": [5.0, 5.0, 5.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:method.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2018-05-31T12:00:00Z",
                    "latitude": 60.0,
                    "longitude": -65.0,
                    "station": "S1",
                    "cast_number": 1,
                    "PRES": 5.0,
                    "TE90": -1.0,
                    "PSAL": 32.0,
                },
                {
                    "time": "2018-05-31T12:00:00Z",
                    "latitude": 61.0,
                    "longitude": -65.0,
                    "station": "S2",
                    "cast_number": 2,
                    "PRES": 5.0,
                    "TE90": -0.5,
                    "PSAL": 31.5,
                },
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        text = enrich.invoke({})

    lowered = text.lower()
    # Bloc "Méthode" présent
    assert "méthode" in lowered or "method" in lowered
    # Colonnes détectées explicitement annoncées
    assert "latitude" in text and "longitude" in text and "object_date" in text
    assert "object_depth_min" in text
    # Dataset annoncé
    assert "amundsen12713" in text
    # Tolérances annoncées
    assert "25" in text and "24" in text  # km et h défauts
    # Décompte par statut
    assert "matched" in lowered
    assert "no_match" in lowered or "1 sans match" in lowered or "1 non matchée" in lowered


def test_enrich_with_amundsen_ctd_diagnoses_all_empty_coordinates_without_erddap_call():
    """Colonnes lat/lon présentes mais 100 % vides : diagnostic, pas d'appel ERDDAP."""
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-empty-coords"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "object_lat": [None, None, None],
            "object_lon": [None, None, None],
            "object_date": ["2013-08-15", "2013-08-15", "2013-08-15"],
        }
    )
    _store.set(thread_id, source, {"source": "file:ecotaxa_no_coords.tsv"})

    with patch("tools.amundsen_sources._fetch_amundsen_bbox") as mock_fetch:
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        result = enrich.invoke({})

    mock_fetch.assert_not_called()
    assert (
        "vides" in result.lower()
        or "empty" in result.lower()
        or "aucune coordonnée" in result.lower()
    )


def test_enrich_with_amundsen_ctd_can_target_specific_dataset_via_source_variable():
    """Quand plusieurs fichiers sont en session, `source_variable` cible le bon."""
    import pandas as pd
    from unittest.mock import patch

    from tools.amundsen_sources import make_amundsen_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-amundsen-source-var"
    for key in _store.keys(thread_id):
        _store.clear(key)

    # Fichier A (filet) — persisté sous df_file_filet
    filet = pd.DataFrame(
        {
            "station_id": ["FILET-1"],
            "latitude": [60.0],
            "longitude": [-65.0],
            "object_date": ["2018-06-01"],
        }
    )
    _store.set(
        f"{thread_id}:dataset:df_file_filet",
        filet,
        {"source": "file:filet.tsv", "variable_name": "df_file_filet"},
    )

    # Fichier B (UVP) — devient le df actif (dernier chargé)
    uvp = pd.DataFrame(
        {
            "Profile": ["UVP-A"],
            "latitude": [74.0],
            "longitude": [-80.0],
            "object_date": ["2018-08-15"],
        }
    )
    _store.set(thread_id, uvp, {"source": "file:uvp.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2018-06-01T12:00:00Z",
                    "latitude": 60.0,
                    "longitude": -65.0,
                    "station": "N01",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": -1.0,
                    "PSAL": 32.0,
                }
            ]
        )

    with patch(
        "tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            tool
            for tool in make_amundsen_tools(thread_id)
            if tool.name == "enrich_with_amundsen_ctd"
        )
        enrich.invoke({"source_variable": "df_file_filet"})

    # L'enrichissement doit avoir ciblé le FILET, pas l'UVP
    keys = _store.keys(f"{thread_id}:dataset:df_amundsen_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert "station_id" in enriched.columns  # propre au filet
    assert "Profile" not in enriched.columns  # serait l'UVP
    assert enriched["station_id"].tolist() == ["FILET-1"]
    assert enriched["amundsen_match_status"].tolist() == ["matched"]


def test_system_prompt_documents_source_variable_for_multi_file_sessions():
    """Le routage doit dire à l'agent de passer source_variable quand plusieurs fichiers."""
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "source_variable" in COPEPOD_SYSTEM_PROMPT
