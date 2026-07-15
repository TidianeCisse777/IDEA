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


def test_enrich_with_ogsl_matches_by_lat_lon_time():
    """Tracer bullet — table source avec lat/lon/time → 1 mesure CTD OGSL par ligne."""
    import pandas as pd
    from unittest.mock import patch

    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-ogsl-tracer"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [48.7],
            "longitude": [-68.5],
            "object_date": ["2024-06-01"],
        }
    )
    _store.set(thread_id, source, {"source": "file:ogsl_tracer.tsv"})

    def fake_fetch_bbox(*, bbox, time_window, variables):
        return pd.DataFrame(
            [
                {
                    "time": "2024-06-01T12:00:00Z",
                    "latitude": 48.7,
                    "longitude": -68.5,
                    "cruiseID": "IML-2024",
                    "stationID": "STN-4",
                    "cast_number": 1,
                    "PRES": 2.0,
                    "TE90": 4.1,
                    "PSAL": 30.5,
                    "OXYM": 280.0,
                }
            ]
        )

    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_fetch_bbox):
        enrich = next(
            tool
            for tool in make_ogsl_tools(thread_id)
            if tool.name == "enrich_with_ogsl"
        )
        enrich.invoke({})

    keys = _store.keys(f"{thread_id}:dataset:df_ogsl_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["ogsl_match_status"].tolist() == ["matched"]
    assert enriched["ogsl_te90_degC"].tolist() == [4.1]
    assert enriched["ogsl_psal_psu"].tolist() == [30.5]
    assert enriched["ogsl_oxym_umol_kg"].tolist() == [280.0]
    assert enriched["ogsl_station_id"].tolist() == ["STN-4"]
    assert enriched["ogsl_dataset_id"].tolist() == ["ismerSgdeCtd"]


def test_enrich_with_ogsl_diagnoses_missing_coordinates():
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-missing"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({"Profile": ["A"], "Sampled volume [L]": [100]})
    _store.set(tid, src, {"source": "smoke"})
    with patch("tools.ogsl_sources._fetch_ogsl_bbox") as fetch_mock:
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        result = enrich.invoke({})
    fetch_mock.assert_not_called()
    assert "manquantes" in result or "missing" in result.lower()


def test_enrich_with_ogsl_diagnoses_empty_coordinates():
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-empty"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({"latitude": [None, None], "longitude": [None, None], "object_date": ["2024-01-01", "2024-01-02"]})
    _store.set(tid, src, {"source": "smoke"})
    with patch("tools.ogsl_sources._fetch_ogsl_bbox") as fetch_mock:
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        result = enrich.invoke({})
    fetch_mock.assert_not_called()
    assert "vides" in result.lower() or "entièrement" in result.lower()


def test_enrich_with_ogsl_no_match_when_too_far_spatially():
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-far"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({"latitude": [0.0], "longitude": [0.0], "object_date": ["2024-06-01"]})
    _store.set(tid, src, {"source": "smoke"})

    def fake_bbox(*, bbox, time_window, variables):
        return pd.DataFrame([{
            "time": "2024-06-01T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
            "stationID": "X", "cruiseID": "C", "cast_number": 1,
            "PRES": 2.0, "TE90": 4.0, "PSAL": 30.0, "OXYM": 280.0,
        }])
    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_bbox):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        enrich.invoke({"spatial_tolerance_km": 25})
    keys = _store.keys(f"{tid}:dataset:df_ogsl_enriched_")
    df = _store.get(keys[-1])["df"]
    assert df["ogsl_match_status"].tolist() == ["no_match"]


def test_enrich_with_ogsl_picks_depth_within_profile():
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-depth"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({
        "latitude": [48.7, 48.7], "longitude": [-68.5, -68.5],
        "object_date": ["2024-06-01", "2024-06-01"],
        "object_depth_min": [5.0, 50.0],
    })
    _store.set(tid, src, {"source": "smoke"})

    def fake_bbox(*, bbox, time_window, variables):
        return pd.DataFrame([
            {"time": "2024-06-01T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
             "stationID": "S", "cruiseID": "C", "cast_number": 1,
             "PRES": 5.0, "TE90": 4.5, "PSAL": 30.0, "OXYM": 280.0},
            {"time": "2024-06-01T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
             "stationID": "S", "cruiseID": "C", "cast_number": 1,
             "PRES": 50.0, "TE90": 2.0, "PSAL": 33.5, "OXYM": 240.0},
        ])
    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_bbox):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        enrich.invoke({})
    keys = _store.keys(f"{tid}:dataset:df_ogsl_enriched_")
    df = _store.get(keys[-1])["df"]
    assert df["ogsl_pres_dbar"].tolist() == [5.0, 50.0]
    assert df["ogsl_te90_degC"].tolist() == [4.5, 2.0]


def test_enrich_with_ogsl_emits_single_bbox_call_with_proper_window():
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-bbox"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({
        "latitude": [48.7, 49.0, 48.5, 49.5],
        "longitude": [-68.5, -68.0, -69.0, -67.5],
        "object_date": ["2024-06-01", "2024-06-02", "2024-06-03", "2024-06-04"],
    })
    _store.set(tid, src, {"source": "smoke"})
    fetch_mock = MagicMock(return_value=pd.DataFrame([{
        "time": "2024-06-02T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
        "stationID": "S", "cruiseID": "C", "cast_number": 1,
        "PRES": 2.0, "TE90": 4.0, "PSAL": 30.0, "OXYM": 280.0,
    }]))
    with patch("tools.ogsl_sources._fetch_ogsl_bbox", fetch_mock):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        enrich.invoke({})
    assert fetch_mock.call_count == 1
    bbox = fetch_mock.call_args.kwargs["bbox"]
    assert bbox["lat_min"] <= 48.5 and bbox["lat_max"] >= 49.5
    assert bbox["lon_min"] <= -69.0 and bbox["lon_max"] >= -67.5


def test_enrich_with_ogsl_batches_large_latlon_sources():
    """Les gros fichiers lat/lon/time ne doivent pas partir en une bbox globale."""
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-large-latlon-batches"
    for k in _store.keys(tid):
        _store.clear(k)
    src = pd.DataFrame(
        {
            "latitude": [48.7, 49.0, 74.0, 74.2],
            "longitude": [-68.5, -68.0, -80.0, -80.2],
            "object_date": [
                "2024-06-01",
                "2024-06-02",
                "2024-08-01",
                "2024-08-02",
            ],
            "object_depth_min": [5.0, 10.0, 50.0, 55.0],
        }
    )
    _store.set(tid, src, {"source": "smoke"})
    calls = []

    def fake_bbox(*, bbox, time_window, variables, pres_range=None):
        calls.append({"bbox": bbox, "time_window": time_window, "pres_range": pres_range})
        return pd.DataFrame(columns=[
            "time", "latitude", "longitude", "cruiseID", "stationID",
            "cast_number", "PRES", "TE90", "PSAL", "OXYM",
        ])

    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_bbox):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        text = enrich.invoke({"initial_batch_spatial_degrees": 5})

    assert len(calls) == 2
    assert all(call["pres_range"] is not None for call in calls)
    assert "Requêtes ERDDAP : 2" in text
    assert "Points source uniques interrogés : 4" in text


def test_enrich_with_ogsl_returns_method_block_and_metrics():
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-method"
    for k in _store.keys(tid): _store.clear(k)
    src = pd.DataFrame({
        "latitude": [48.7, 0.0], "longitude": [-68.5, 0.0],
        "object_date": ["2024-06-01", "2024-06-01"],
    })
    _store.set(tid, src, {"source": "smoke"})

    def fake_bbox(*, bbox, time_window, variables):
        return pd.DataFrame([{
            "time": "2024-06-01T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
            "stationID": "S", "cruiseID": "C", "cast_number": 1,
            "PRES": 2.0, "TE90": 4.0, "PSAL": 30.0, "OXYM": 280.0,
        }])
    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_bbox):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        text = enrich.invoke({})
    lowered = text.lower()
    assert "méthode" in lowered
    assert "latitude" in text and "longitude" in text and "object_date" in text
    assert "ismerSgdeCtd" in text
    assert "matched=1" in text and "no_match=1" in text
    keys = _store.keys(f"{tid}:dataset:df_ogsl_enriched_")
    df = _store.get(keys[-1])["df"]
    assert "ogsl_distance_km" in df.columns
    assert "ogsl_time_delta_min" in df.columns


def test_fetch_ogsl_bbox_queries_erddap_with_bbox_and_time_constraints():
    from unittest.mock import MagicMock, patch
    from tools.ogsl_sources import _fetch_ogsl_bbox

    csv_body = (
        "time,latitude,longitude,cruiseID,stationID,cast_number,PRES (decibars),TE90 (degC),PSAL (PSU),OXYM (umol kg-1)\n"
        "2024-06-01T12:00:00Z,48.7,-68.5,IML,STN-4,1,2.0,4.1,30.5,280.0\n"
    )
    response = MagicMock(status_code=200, text=csv_body)
    response.raise_for_status = MagicMock()
    with patch("tools.ogsl_sources.requests.get", return_value=response) as mock_get:
        df = _fetch_ogsl_bbox(
            bbox={"lat_min": 48.0, "lat_max": 49.5, "lon_min": -69.5, "lon_max": -67.5},
            time_window={"start": "2024-05-31T00:00:00Z", "end": "2024-06-03T00:00:00Z"},
            variables=["TE90", "PSAL", "OXYM"],
        )
    assert mock_get.called
    url = mock_get.call_args.args[0]
    assert "ismerSgdeCtd.csvp" in url
    assert "TE90" in url and "PSAL" in url and "OXYM" in url
    assert df.iloc[0]["stationID"] == "STN-4"
    assert float(df.iloc[0]["TE90"]) == 4.1


def test_system_prompt_prefers_enrich_with_ogsl_for_latlon_files():
    from pathlib import Path

    skills = "\n".join(
        Path(path).read_text()
        for path in (
            "agents/skills/neolabs_abundance_analysis.md",
            "agents/skills/copepod_hydrodynamic_micro_zoom.md",
        )
    )
    assert "enrich_with_ogsl" in skills


def test_enrich_with_ogsl_can_target_specific_dataset_via_source_variable():
    """source_variable cible un dataset persistant au lieu du df actif."""
    import pandas as pd
    from unittest.mock import patch
    from tools.ogsl_sources import make_ogsl_tools
    from tools.session_store import default_store as _store

    tid = "thread-ogsl-source-var"
    for k in _store.keys(tid):
        _store.clear(k)

    filet = pd.DataFrame({
        "station_id": ["FILET-1"],
        "latitude": [48.7],
        "longitude": [-68.5],
        "object_date": ["2024-06-01"],
    })
    _store.set(
        f"{tid}:dataset:df_file_filet",
        filet,
        {"source": "file:filet.tsv", "variable_name": "df_file_filet"},
    )
    uvp = pd.DataFrame({
        "Profile": ["UVP-A"], "latitude": [74.0], "longitude": [-80.0],
        "object_date": ["2018-08-15"],
    })
    _store.set(tid, uvp, {"source": "file:uvp.tsv"})

    def fake_bbox(*, bbox, time_window, variables):
        return pd.DataFrame([{
            "time": "2024-06-01T12:00:00Z", "latitude": 48.7, "longitude": -68.5,
            "stationID": "STN", "cruiseID": "C", "cast_number": 1,
            "PRES": 2.0, "TE90": 4.0, "PSAL": 30.0, "OXYM": 280.0,
        }])

    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_bbox):
        enrich = next(t for t in make_ogsl_tools(tid) if t.name == "enrich_with_ogsl")
        enrich.invoke({"source_variable": "df_file_filet"})

    keys = _store.keys(f"{tid}:dataset:df_ogsl_enriched_")
    df = _store.get(keys[-1])["df"]
    assert "station_id" in df.columns
    assert "Profile" not in df.columns
    assert df["ogsl_match_status"].tolist() == ["matched"]
