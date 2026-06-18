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


def test_query_bio_oracle_accepts_list_of_points_for_multi_station(tmp_path):
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-bio-oracle-multipoint"
    for key in _store.keys(thread_id):
        _store.clear(key)

    calls = []

    def fake_query(parameters, output_path=None):
        calls.append((parameters["latitude"], parameters["longitude"]))
        dataframe = pd.DataFrame(
            [
                {
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": float(parameters["latitude"]),
                }
            ]
        )
        dataframe.to_csv(output_path, sep="\t", index=False)
        return {
            "dataset_id": "thetao_baseline_2000_2019_depthsurf",
            "title": "Bio-Oracle Temperature [depthSurf] baseline",
            "file_path": str(output_path),
            "download_url": str(output_path),
            "row_count": 1,
        }

    with patch("tools.bio_oracle_sources._query_bio_oracle", side_effect=fake_query):
        query = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "query_bio_oracle"
        )
        result = query.invoke(
            {
                "latitude": [59.8, 61.7],
                "longitude": [-64.9, -87.8],
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )

    assert set(calls) == {(59.8, -64.9), (61.7, -87.8)}
    assert "2 lignes" in result
    merged = _store.get(f"{thread_id}:bio_oracle")["df"]
    assert sorted(merged["latitude"].tolist()) == [59.8, 61.7]


def test_query_bio_oracle_rejects_mismatched_or_empty_point_lists():
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from unittest.mock import patch

    calls = []

    def fake_query(parameters, output_path=None):  # pragma: no cover - should not run
        calls.append(parameters)
        raise AssertionError("ERDDAP must not be called on invalid input")

    with patch("tools.bio_oracle_sources._query_bio_oracle", side_effect=fake_query):
        query = next(
            tool for tool in make_bio_oracle_tools("thread-bio-oracle-invalid")
            if tool.name == "query_bio_oracle"
        )
        mismatched = query.invoke(
            {
                "latitude": [59.8, 61.7],
                "longitude": [-64.9],
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )
        empty = query.invoke(
            {
                "latitude": [],
                "longitude": [],
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )
        mixed = query.invoke(
            {
                "latitude": [59.8, 61.7],
                "longitude": -64.9,
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )

    assert calls == []
    assert "même longueur" in mismatched
    assert "vide" in empty
    assert "tous deux des nombres" in mixed or "tous deux des listes" in mixed


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


def test_query_bio_oracle_zones_does_not_replace_active_source_dataframe():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-zones-preserve-source"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "STATION_NAME": ["A", "B"],
            "latitude": [74.0, 75.0],
            "longitude": [-70.0, -71.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:stations.tsv"})

    def fake_preview(parameters):
        return {
            "dataset_id": "thetao_baseline_2000_2019_depthsurf",
            "variable": "thetao",
            "rows": [{"thetao": -0.1276}],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        zones = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "query_bio_oracle_zones"
        )
        result = zones.invoke(
            {
                "zones": ["Baie de Baffin"],
                "variable": "temperature",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )

    current = _store.get(thread_id)["df"]
    pd.testing.assert_frame_equal(current.reset_index(drop=True), source)
    assert "df_bio_oracle_zones_temperature_baseline_surface" in result
    assert _store.get(
        f"{thread_id}:dataset:df_bio_oracle_zones_temperature_baseline_surface"
    )["df"]["zone"].iloc[0] == "Baie de Baffin"


def test_couple_bio_oracle_falls_back_to_named_file_when_current_df_lacks_coordinates():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.dataset_registry import store_dataset
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-couple-fallback-file"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "STATION_NAME": ["A", "B"],
            "latitude": [74.0, 75.0],
            "longitude": [-70.0, -71.0],
        }
    )
    store_dataset(
        _store,
        thread_id,
        source,
        variable_name="df_file_neolabs_taxonomy_2014_2020",
        meta={"source": "file:neolabs_taxonomy_2014_2020.tsv"},
    )
    _store.set(
        thread_id,
        pd.DataFrame({"zone": ["Baie de Baffin"], "lat_centre": [74.5], "lon_centre": [-70]}),
        {"source": "bio_oracle_zones"},
    )

    def fake_preview(parameters):
        return {
            "dataset_id": "thetao_baseline_2000_2019_depthsurf",
            "variable": "thetao",
            "rows": [
                {
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": parameters["latitude"],
                }
            ],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        couple = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        result = couple.invoke(
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
            }
        )

    assert "Couplage Bio-ORACLE chargé" in result
    assert "Source utilisée : `df_file_neolabs_taxonomy_2014_2020`" in result
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    coupled = _store.get(keys[0])["df"]
    assert coupled["thetao_baseline"].tolist() == [74.0, 75.0]


def test_couple_bio_oracle_supports_top_stations_and_multiple_scenarios():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-couple-top-stations-multi-scenario"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "STATION_NAME": ["24", "24", "24", "312", "312", "18"],
            "SAMPLE_ID": [1, 2, 3, 4, 5, 6],
            "latitude": [61.7, 61.7, 61.7, 69.1, 69.1, 63.7],
            "longitude": [-87.8, -87.8, -87.8, -100.7, -100.7, -88.4],
        }
    )
    _store.set(thread_id, source, {"source": "file:neolabs_taxonomy_2014_2020.tsv"})

    scenario_values = {
        "baseline": 1.0,
        "SSP1-2.6": 2.0,
        "SSP5-8.5": 5.0,
    }

    def fake_preview(parameters):
        return {
            "dataset_id": f"thetao_{parameters['scenario']}_depthsurf",
            "variable": "thetao",
            "rows": [
                {
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": scenario_values[parameters["scenario"]],
                }
            ],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        couple = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        result = couple.invoke(
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
                "station_column": "STATION_NAME",
                "sample_column": "SAMPLE_ID",
                "top_n_stations": 2,
                "scenarios": ["baseline", "SSP1-2.6", "SSP5-8.5"],
            }
        )

    assert "Couplage Bio-ORACLE chargé — 2 lignes." in result
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    coupled = _store.get(keys[0])["df"]
    assert coupled["STATION_NAME"].tolist() == ["24", "312"]
    assert coupled["n_samples"].tolist() == [3, 2]
    assert coupled["thetao_baseline"].tolist() == [1.0, 1.0]
    assert coupled["thetao_ssp1_2_6"].tolist() == [2.0, 2.0]
    assert coupled["thetao_ssp5_8_5"].tolist() == [5.0, 5.0]


def test_couple_bio_oracle_passes_target_year_and_persists_time_columns():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-couple-target-year"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "STATION_NAME": ["24", "312"],
            "SAMPLE_ID": [1, 2],
            "latitude": [61.7, 69.1],
            "longitude": [-87.8, -100.7],
        }
    )
    _store.set(thread_id, source, {"source": "file:neolabs_taxonomy_2014_2020.tsv"})
    calls = []

    def fake_preview(parameters):
        calls.append(parameters)
        return {
            "dataset_id": "thetao_ssp126_2020_2100_depthsurf",
            "variable": "thetao",
            "rows": [
                {
                    "time": "2050-01-01T00:00:00Z",
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": 2.5,
                }
            ],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        couple = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        result = couple.invoke(
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "thetao",
                "scenario": "SSP1-2.6",
                "depth_layer": "surface",
                "station_column": "STATION_NAME",
                "sample_column": "SAMPLE_ID",
                "top_n_stations": 2,
                "target_year": 2050,
            }
        )

    assert "time" in result
    assert {call["target_year"] for call in calls} == {2050}
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    coupled = _store.get(keys[0])["df"]
    assert coupled["thetao_ssp1_2_6"].tolist() == [2.5, 2.5]
    assert coupled["time"].tolist() == [
        "2050-01-01T00:00:00Z",
        "2050-01-01T00:00:00Z",
    ]


def test_couple_bio_oracle_mixed_baseline_and_future_target_year_is_traceable():
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-couple-baseline-future-target-year"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "STATION_NAME": ["24", "24", "312"],
            "SAMPLE_ID": [1, 2, 3],
            "latitude": [61.7, 61.7, 69.1],
            "longitude": [-87.8, -87.8, -100.7],
        }
    )
    _store.set(thread_id, source, {"source": "file:neolabs_taxonomy_2014_2020.tsv"})
    calls = []

    def fake_preview(parameters):
        calls.append(parameters)
        scenario = parameters["scenario"]
        time_value = (
            "2010-01-01T00:00:00Z"
            if scenario == "baseline"
            else "2050-01-01T00:00:00Z"
        )
        value = {"baseline": 1.0, "SSP1-2.6": 2.0, "SSP5-8.5": 5.0}[scenario]
        return {
            "dataset_id": f"thetao_{scenario}_depthsurf",
            "variable": "thetao",
            "rows": [
                {
                    "time": time_value,
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    "thetao": value,
                }
            ],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        couple = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        result = couple.invoke(
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "thetao",
                "scenario": "baseline",
                "depth_layer": "surface",
                "station_column": "STATION_NAME",
                "sample_column": "SAMPLE_ID",
                "top_n_stations": 2,
                "scenarios": ["baseline", "SSP1-2.6", "SSP5-8.5"],
                "target_year": 2050,
            }
        )

    assert "time_baseline" in result
    assert "time_ssp1_2_6" in result
    assert {call["target_year"] for call in calls} == {2050}
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    coupled = _store.get(keys[0])["df"]
    assert coupled["time_baseline"].tolist() == [
        "2010-01-01T00:00:00Z",
        "2010-01-01T00:00:00Z",
    ]
    assert coupled["time_ssp1_2_6"].tolist() == [
        "2050-01-01T00:00:00Z",
        "2050-01-01T00:00:00Z",
    ]
    assert coupled["time_ssp5_8_5"].tolist() == [
        "2050-01-01T00:00:00Z",
        "2050-01-01T00:00:00Z",
    ]


def test_enrich_with_bio_oracle_attaches_value_to_each_source_row():
    """Tracer bullet — table source avec lat/lon → 1 valeur Bio-ORACLE par ligne.

    Cas EcoTaxa typique : on appelle un seul tool avec variables + scenarios,
    le tool auto-détecte lat/lon, interroge Bio-ORACLE et recolle une valeur
    par ligne dans une colonne préfixée.
    """
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-tracer"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [60.0],
            "longitude": [-65.0],
            "object_date": ["2018-06-01"],
        }
    )
    _store.set(thread_id, source, {"source": "file:bio.tsv"})

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        return {
            "dataset_id": "thetao_ssp585_2020_2100_depthsurf",
            "time": "2050-01-01T00:00:00Z",
            "value": 8.42,
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        enrich.invoke(
            {
                "variables": ["temperature"],
                "scenarios": ["SSP5-8.5"],
                "target_year": 2050,
            }
        )

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_temperature_ssp5_8_5"].tolist() == [8.42]
    assert enriched["bio_oracle_match_status"].tolist() == ["matched"]


def test_enrich_with_bio_oracle_deduplicates_points_to_minimize_http_calls():
    """3 lignes mais 2 points uniques → 2 appels Bio-ORACLE (pas 3)."""
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-dedup"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [60.0, 60.0, 61.0],
            "longitude": [-65.0, -65.0, -66.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:dedup.tsv"})

    counter = {"calls": 0}

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        counter["calls"] += 1
        return {
            "dataset_id": "thetao_ssp585_2020_2100_depthsurf",
            "time": "2050-01-01T00:00:00Z",
            "value": float(latitude),
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        enrich.invoke(
            {
                "variables": ["temperature"],
                "scenarios": ["SSP5-8.5"],
                "target_year": 2050,
            }
        )

    assert counter["calls"] == 2
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_temperature_ssp5_8_5"].tolist() == [60.0, 60.0, 61.0]


def test_enrich_with_bio_oracle_combines_multiple_variables_and_scenarios():
    """2 variables × 2 scénarios → 4 colonnes distinctes."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-multi"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame({"latitude": [60.0], "longitude": [-65.0]})
    _store.set(thread_id, source, {"source": "file:multi.tsv"})

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        return {
            "dataset_id": f"{variable}_{scenario}",
            "time": "2050-01-01T00:00:00Z",
            "value": hash((variable, scenario)) % 100 / 10.0,
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        enrich.invoke(
            {
                "variables": ["temperature", "salinity"],
                "scenarios": ["baseline", "SSP5-8.5"],
            }
        )

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    expected_cols = {
        "bio_oracle_temperature_baseline",
        "bio_oracle_temperature_ssp5_8_5",
        "bio_oracle_salinity_baseline",
        "bio_oracle_salinity_ssp5_8_5",
    }
    assert expected_cols.issubset(set(enriched.columns))


def test_enrich_with_bio_oracle_marks_no_value_when_grid_returns_none():
    """Point hors grille / pas de valeur → statut `no_value`, valeur NaN propagée."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-novalue"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame({"latitude": [60.0, 0.0], "longitude": [-65.0, 0.0]})
    _store.set(thread_id, source, {"source": "file:nv.tsv"})

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        if latitude == 0.0:
            return {"dataset_id": "x", "time": None, "value": None}
        return {"dataset_id": "x", "time": "2050-01-01", "value": 8.0}

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        enrich.invoke({"variables": ["temperature"], "scenarios": ["SSP5-8.5"]})

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_match_status"].tolist() == ["matched", "no_value"]


def test_enrich_with_bio_oracle_diagnoses_empty_coordinates_without_http():
    """Colonnes lat/lon présentes mais 100% vides : diagnostic, pas d'appel HTTP."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-empty"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame({"object_lat": [None, None], "object_lon": [None, None]})
    _store.set(thread_id, source, {"source": "file:empty.tsv"})

    with patch("tools.bio_oracle_sources._fetch_bio_oracle_point") as mock_fetch:
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        result = enrich.invoke({"variables": ["temperature"], "scenarios": ["baseline"]})

    mock_fetch.assert_not_called()
    assert (
        "vides" in result.lower()
        or "aucune coordonnée" in result.lower()
        or "empty" in result.lower()
    )


def test_enrich_with_bio_oracle_returns_method_block_and_traceability_columns():
    """Transparence : bloc Méthode + colonnes dataset_id/time par (var, scénario)."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-method"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {"latitude": [60.0, 0.0], "longitude": [-65.0, 0.0]}
    )
    _store.set(thread_id, source, {"source": "file:m.tsv"})

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        if latitude == 0.0:
            return {"dataset_id": None, "time": None, "value": None}
        return {
            "dataset_id": f"{variable}_{scenario}_2020_2100_depthsurf",
            "time": "2050-01-01T00:00:00Z",
            "value": 8.42,
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            tool
            for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "enrich_with_bio_oracle"
        )
        text = enrich.invoke(
            {
                "variables": ["temperature"],
                "scenarios": ["SSP5-8.5"],
                "depth_layer": "surface",
                "target_year": 2050,
            }
        )

    # Bloc Méthode
    lowered = text.lower()
    assert "méthode" in lowered or "method" in lowered
    assert "latitude" in text and "longitude" in text
    assert "surface" in text
    assert "2050" in text
    assert "ssp5-8.5" in lowered or "ssp5_8_5" in lowered
    assert "matched=1" in text and "no_value=1" in text

    # Traçabilité
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    dataset_col = "bio_oracle_temperature_ssp5_8_5_dataset_id"
    time_col = "bio_oracle_temperature_ssp5_8_5_time"
    assert dataset_col in enriched.columns
    assert time_col in enriched.columns
    assert enriched[dataset_col].iloc[0] == "temperature_SSP5-8.5_2020_2100_depthsurf"
    assert enriched[time_col].iloc[0] == "2050-01-01T00:00:00Z"


def test_system_prompt_prefers_enrich_with_bio_oracle_for_csv_enrichment():
    """Le prompt doit mentionner enrich_with_bio_oracle avant couple_zooplankton_bio_oracle."""
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT
    assert "enrich_with_bio_oracle" in prompt
    new_idx = prompt.find("enrich_with_bio_oracle")
    old_idx = prompt.find("couple_zooplankton_bio_oracle")
    assert new_idx != -1
    assert new_idx < old_idx or old_idx == -1


def test_enrich_with_bio_oracle_marks_no_value_when_grid_returns_nan_float():
    """Bio-ORACLE renvoie nan (point sur terre / hors océan) → statut no_value."""
    import math
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-nan-float"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame({"latitude": [49.5], "longitude": [-63.0]})
    _store.set(thread_id, source, {"source": "file:anticosti.tsv"})

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        return {
            "dataset_id": "thetao_baseline_2000_2019_depthsurf",
            "time": "2010-01-01T00:00:00Z",
            "value": math.nan,
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            t for t in make_bio_oracle_tools(thread_id)
            if t.name == "enrich_with_bio_oracle"
        )
        enrich.invoke({"variables": ["temperature"], "scenarios": ["baseline"]})

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_match_status"].tolist() == ["no_value"]


def test_enrich_with_bio_oracle_skips_out_of_range_coords_without_http():
    """Coordonnées hors plage valide (lat>90, lon>180) → no_value sans crash."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-bad-coords"
    for key in _store.keys(thread_id):
        _store.clear(key)

    source = pd.DataFrame(
        {
            "latitude": [60.0, 999.0, 200.0, -91.0],
            "longitude": [-65.0, 999.0, -90.0, 0.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:bad.tsv"})

    fetch_calls = []

    def fake_fetch_point(*, latitude, longitude, variable, scenario, depth_layer, target_year):
        fetch_calls.append((latitude, longitude))
        return {
            "dataset_id": "thetao_baseline_2000_2019_depthsurf",
            "time": "2010-01-01",
            "value": 8.0,
        }

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_point", side_effect=fake_fetch_point
    ):
        enrich = next(
            t for t in make_bio_oracle_tools(thread_id)
            if t.name == "enrich_with_bio_oracle"
        )
        enrich.invoke({"variables": ["temperature"], "scenarios": ["baseline"]})

    # Seul le 1er point (60, -65) doit être appelé
    assert fetch_calls == [(60.0, -65.0)]
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_match_status"].tolist() == [
        "matched",
        "no_value",
        "no_value",
        "no_value",
    ]
