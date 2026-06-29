"""TDD — tools/bio_oracle_sources.py."""

import pytest

from tools.session_store import SessionStore


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Fresh in-memory store so tests run under SESSION_STORE_DATABASE_URL/SessionStorePG."""
    store = SessionStore()
    monkeypatch.setattr("tools.session_store.default_store", store)
    monkeypatch.setattr("tools.bio_oracle_sources._store", store)
    return store


def _bbox_tile_df(value, *, dataset_id="ds_test", time="2010-01-01T00:00:00Z", latitude=60.0, longitude=-65.0):
    """Build a one-row tile DataFrame for mocking _fetch_bio_oracle_bbox."""
    import pandas as pd
    df = pd.DataFrame([
        {"time": time, "latitude": latitude, "longitude": longitude, "value": value}
    ])
    df.attrs["dataset_id"] = dataset_id
    return df


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
                "target_year": 2050,
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
    assert "thetao_ssp245_2050" in df_coupled.columns
    assert df_coupled["thetao_ssp245_2050"].tolist() == [48.7, 48.5, 48.7]


def test_couple_zooplankton_bio_oracle_refuses_ssp_without_target_year():
    """Garde-fou structural : sur un scénario SSP, si `target_year` n'est pas
    fourni, le tool DOIT refuser l'appel et renvoyer un marqueur clair
    `TARGET_YEAR_REQUIRED` listant les décennies disponibles (2020, 2030, …,
    2090). L'agent forwarde ce message à l'utilisateur et attend qu'il choisisse,
    plutôt que de laisser ERDDAP retourner 2090 silencieusement (mal interprété
    quand le tableau contient des dates UVP/zooplankton).

    Baseline reste OK sans target_year (single climatology).
    """
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-ssp-refuse"
    source = pd.DataFrame(
        [{"station": "A", "latitude": 50.0, "longitude": -60.0}]
    )
    for key in _store.keys(thread_id):
        _store.clear(key)
    _store.set(thread_id, source, {"source": "uploaded_file"})

    preview_calls = []

    def fake_preview(parameters):
        preview_calls.append(parameters)
        return {
            "dataset_id": "stub",
            "variable": parameters["variable"],
            "rows": [{
                "time": "2090-01-01T00:00:00Z",
                "latitude": parameters["latitude"],
                "longitude": parameters["longitude"],
                parameters["variable"]: 1.0,
            }],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        couple = next(
            tool for tool in make_bio_oracle_tools(thread_id)
            if tool.name == "couple_zooplankton_bio_oracle"
        )

        # 1. SSP without target_year → refuse, no preview call
        result = couple.invoke({
            "latitude_column": "latitude", "longitude_column": "longitude",
            "variable": "thetao", "scenario": "SSP5-8.5",
            "depth_layer": "depthsurf",
        })
        assert "TARGET_YEAR_REQUIRED" in result
        assert "2050" in result and "2090" in result
        assert preview_calls == []  # nothing was fetched

        # 2. SSP with target_year → proceed as before
        result2 = couple.invoke({
            "latitude_column": "latitude", "longitude_column": "longitude",
            "variable": "thetao", "scenario": "SSP5-8.5",
            "depth_layer": "depthsurf", "target_year": 2050,
        })
        assert "TARGET_YEAR_REQUIRED" not in result2
        assert "Couplage Bio-ORACLE chargé" in result2
        assert len(preview_calls) == 1

        # 3. baseline without target_year → still allowed (climatology)
        preview_calls.clear()
        result3 = couple.invoke({
            "latitude_column": "latitude", "longitude_column": "longitude",
            "variable": "thetao", "scenario": "baseline",
            "depth_layer": "depthsurf",
        })
        assert "TARGET_YEAR_REQUIRED" not in result3
        assert "Couplage Bio-ORACLE chargé" in result3
        assert len(preview_calls) == 1


def test_couple_zooplankton_bio_oracle_target_year_in_column_name_for_ssp():
    """Quand un `target_year` est passé pour un scénario SSP, la colonne de
    valeur doit inclure l'année dans son nom (ex `thetao_ssp585_2050`). Sans
    ça, un tableau qui mêle Bio-ORACLE et données terrain (date du sample
    UVP, etc.) peut induire l'utilisateur à associer la projection 2050/2090
    à une autre date présente dans la table.

    Pas de suffixe pour baseline (pas de point temporel à disambiguer) et
    pas de suffixe quand target_year n'est pas fourni (rétrocompat).
    """
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    source = pd.DataFrame(
        [{"station": "A", "latitude": 50.0, "longitude": -60.0}]
    )

    def fake_preview(parameters):
        return {
            "dataset_id": "stub",
            "variable": parameters["variable"],
            "rows": [{
                "time": f"{parameters['target_year']}-01-01T00:00:00Z"
                if parameters.get("target_year") else "2090-01-01T00:00:00Z",
                "latitude": parameters["latitude"],
                "longitude": parameters["longitude"],
                parameters["variable"]: 1.0,
            }],
        }

    with patch("tools.bio_oracle_sources._preview_bio_oracle_point", side_effect=fake_preview):
        # Case 1: SSP scenario + target_year → column name includes year
        thread_a = "thread-target-year-ssp"
        for key in _store.keys(thread_a):
            _store.clear(key)
        _store.set(thread_a, source.copy(), {"source": "uploaded_file"})
        couple_a = next(
            tool for tool in make_bio_oracle_tools(thread_a)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        couple_a.invoke({
            "latitude_column": "latitude", "longitude_column": "longitude",
            "variable": "thetao", "scenario": "SSP5-8.5",
            "depth_layer": "depthsurf", "target_year": 2050,
        })
        keys_a = _store.keys(f"{thread_a}:dataset:df_bio_oracle_coupling_")
        assert len(keys_a) == 1
        df1 = _store.get(keys_a[0])["df"]
        assert "thetao_ssp5_8_5_2050" in df1.columns
        assert "thetao_ssp5_8_5" not in df1.columns

        # Case 2: baseline + target_year → no year suffix (baseline ignores it)
        thread_b = "thread-target-year-baseline"
        for key in _store.keys(thread_b):
            _store.clear(key)
        _store.set(thread_b, source.copy(), {"source": "uploaded_file"})
        couple_b = next(
            tool for tool in make_bio_oracle_tools(thread_b)
            if tool.name == "couple_zooplankton_bio_oracle"
        )
        couple_b.invoke({
            "latitude_column": "latitude", "longitude_column": "longitude",
            "variable": "thetao", "scenario": "baseline",
            "depth_layer": "depthsurf", "target_year": 2050,
        })
        keys_b = _store.keys(f"{thread_b}:dataset:df_bio_oracle_coupling_")
        assert len(keys_b) == 1
        df2 = _store.get(keys_b[0])["df"]
        assert "thetao_baseline" in df2.columns
        assert "thetao_baseline_2050" not in df2.columns


def test_couple_zooplankton_bio_oracle_supports_multiple_variables_one_shot():
    """Quand l'utilisateur demande plusieurs variables Bio-ORACLE (température
    + salinité + oxygène), le tool doit faire UN SEUL appel et produire une
    colonne par variable. Avant ce fix, l'agent devait soit faire 3 appels
    successifs (ce qu'il ne faisait jamais naturellement), soit accepter une
    sortie incomplète.
    """
    import pandas as pd
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store
    from unittest.mock import patch

    thread_id = "thread-multi-vars"
    source = pd.DataFrame(
        [
            {"station": "HC-05", "latitude": 53.4338, "longitude": -54.1171},
            {"station": "HC-04", "latitude": 53.3330, "longitude": -54.3157},
        ]
    )
    for key in _store.keys(thread_id):
        _store.clear(key)
    _store.set(thread_id, source, {"source": "uploaded_file"})

    preview_calls = []

    def fake_preview(parameters):
        preview_calls.append(parameters)
        # different stub value per variable so we can assert columns are independent
        stub = {"thetao": 5.9, "so": 32.5, "o2": 280.0}.get(parameters["variable"], 0.0)
        return {
            "dataset_id": f"{parameters['variable']}_{parameters['scenario']}_depthsurf",
            "title": "stub",
            "variable": parameters["variable"],
            "rows": [
                {
                    "time": "2050-01-01T00:00:00Z",
                    "latitude": parameters["latitude"],
                    "longitude": parameters["longitude"],
                    parameters["variable"]: stub,
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
                "variables": ["thetao", "so", "o2"],
                "scenario": "ssp585",
                "depth_layer": "depthsurf",
                "target_year": 2050,
            }
        )

    assert "Couplage Bio-ORACLE chargé" in result
    # one preview call per (point × variable) = 2 stations × 3 variables = 6 calls
    assert len(preview_calls) == 6
    variables_seen = {call["variable"] for call in preview_calls}
    assert variables_seen == {"thetao", "so", "o2"}

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    df_coupled = _store.get(keys[0])["df"]
    # All three variable columns are present and filled (with target year suffix)
    assert "thetao_ssp585_2050" in df_coupled.columns
    assert "so_ssp585_2050" in df_coupled.columns
    assert "o2_ssp585_2050" in df_coupled.columns
    assert df_coupled["thetao_ssp585_2050"].tolist() == [5.9, 5.9]
    assert df_coupled["so_ssp585_2050"].tolist() == [32.5, 32.5]
    assert df_coupled["o2_ssp585_2050"].tolist() == [280.0, 280.0]


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
                "target_year": 2050,
            }
        )

    assert "Couplage Bio-ORACLE chargé — 2 lignes." in result
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_coupling_")
    assert len(keys) == 1
    coupled = _store.get(keys[0])["df"]
    assert coupled["STATION_NAME"].tolist() == ["24", "312"]
    assert coupled["n_samples"].tolist() == [3, 2]
    # baseline ignores target_year → no year suffix; SSP get _2050 suffix.
    assert coupled["thetao_baseline"].tolist() == [1.0, 1.0]
    assert coupled["thetao_ssp1_2_6_2050"].tolist() == [2.0, 2.0]
    assert coupled["thetao_ssp5_8_5_2050"].tolist() == [5.0, 5.0]


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
    # Column name carries the target year for future scenarios — disambiguates
    # decadal projections from any other date column in the table.
    assert coupled["thetao_ssp1_2_6_2050"].tolist() == [2.5, 2.5]
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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        return _bbox_tile_df(
            8.42,
            dataset_id="thetao_ssp585_2020_2100_depthsurf",
            time="2050-01-01T00:00:00Z",
            latitude=60.0,
            longitude=-65.0,
        )

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    # All 3 points snap to the same canonical 5° tile (60-65 × -70 to -65)
    source = pd.DataFrame(
        {
            "latitude": [60.5, 60.5, 62.0],
            "longitude": [-67.0, -67.0, -68.0],
        }
    )
    _store.set(thread_id, source, {"source": "file:dedup.tsv"})

    import pandas as pd_local
    counter = {"calls": 0}

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        counter["calls"] += 1
        # tile DataFrame with one row per source point — lookup picks nearest
        df = pd_local.DataFrame([
            {"time": "2050-01-01T00:00:00Z", "latitude": 60.5, "longitude": -67.0, "value": 60.5},
            {"time": "2050-01-01T00:00:00Z", "latitude": 62.0, "longitude": -68.0, "value": 62.0},
        ])
        df.attrs["dataset_id"] = "thetao_ssp585_2020_2100_depthsurf"
        return df

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    # All 3 source points fall in the same canonical 5° tile → 1 HTTP call
    assert counter["calls"] == 1
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_temperature_ssp5_8_5"].tolist() == [60.5, 60.5, 62.0]


def test_enrich_with_bio_oracle_snaps_to_grid_and_requires_confirmation_when_too_large():
    """Gros fichier : dédup sur grille Bio-ORACLE puis garde-fou sur le nombre d'appels."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-large-guard"
    for key in _store.keys(thread_id):
        _store.clear(key)

    # 3 unique cells AFTER 1/12° snap (60.0, 60.0, 61.0, 62.0 / -67, -67, -67, -67)
    # all in the same canonical 5° tile (60-65 × -70 to -65)
    source = pd.DataFrame(
        {
            "latitude": [60.501, 60.502, 61.501, 62.501],
            "longitude": [-67.001, -67.002, -67.501, -67.502],
        }
    )
    _store.set(thread_id, source, {"source": "file:large.csv"})

    refusal_calls = []

    def fake_refusal_fetch(*, variable, scenario, depth_layer, target_year, tile):
        refusal_calls.append(tile)
        return _bbox_tile_df(1.0, dataset_id="thetao_baseline")

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox",
        side_effect=fake_refusal_fetch,
    ):
        enrich = next(
            t for t in make_bio_oracle_tools(thread_id)
            if t.name == "enrich_with_bio_oracle"
        )
        refused = enrich.invoke({
            "variables": ["temperature"],
            "scenarios": ["baseline"],
            "max_unique_queries": 2,
        })

    assert refusal_calls == []
    assert "Confirmation required" in refused
    assert "3 unique Bio-ORACLE queries" in refused

    calls = []

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        calls.append(tile)
        import pandas as pd_local
        df = pd_local.DataFrame([
            {"time": "baseline", "latitude": 60.0, "longitude": -65.0, "value": 60.0},
            {"time": "baseline", "latitude": 61.0, "longitude": -66.0, "value": 61.0},
            {"time": "baseline", "latitude": 62.0, "longitude": -67.0, "value": 62.0},
        ])
        df.attrs["dataset_id"] = "thetao_baseline"
        return df

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox",
        side_effect=fake_fetch_bbox,
    ):
        enrich.invoke({
            "variables": ["temperature"],
            "scenarios": ["baseline"],
            "max_unique_queries": 2,
            "confirmed": True,
        })

    # All 4 source points across 60-62°N × -65 to -67°W → 1 canonical 5° tile
    assert len(calls) == 1
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_match_status"].tolist() == [
        "matched",
        "matched",
        "matched",
        "matched",
    ]
    assert enriched["bio_oracle_temperature_baseline"].iloc[0] == enriched[
        "bio_oracle_temperature_baseline"
    ].iloc[1]


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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        return _bbox_tile_df(
            hash((variable, scenario)) % 100 / 10.0,
            dataset_id=f"{variable}_{scenario}",
            time="2050-01-01T00:00:00Z",
            latitude=60.0,
            longitude=-65.0,
        )

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        import pandas as pd_local
        # Tile around the first source point only — second point (0, 0) gets
        # a tile fetch returning all-NaN → no_value.
        if tile["lat_min"] <= 0 <= tile["lat_max"]:
            df = pd_local.DataFrame([
                {"time": None, "latitude": 0.0, "longitude": 0.0, "value": None}
            ])
        else:
            df = pd_local.DataFrame([
                {"time": "2050-01-01", "latitude": 60.0, "longitude": -65.0, "value": 8.0}
            ])
        df.attrs["dataset_id"] = "x"
        return df

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    with patch("tools.bio_oracle_sources._fetch_bio_oracle_bbox") as mock_fetch:
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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        import pandas as pd_local
        if tile["lat_min"] <= 0 <= tile["lat_max"]:
            df = pd_local.DataFrame([
                {"time": None, "latitude": 0.0, "longitude": 0.0, "value": None}
            ])
            df.attrs["dataset_id"] = None
            return df
        df = pd_local.DataFrame([
            {"time": "2050-01-01T00:00:00Z", "latitude": 60.0, "longitude": -65.0, "value": 8.42}
        ])
        df.attrs["dataset_id"] = f"{variable}_{scenario}_2020_2100_depthsurf"
        return df

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        return _bbox_tile_df(
            math.nan,
            dataset_id="thetao_baseline_2000_2019_depthsurf",
            time="2010-01-01T00:00:00Z",
            latitude=49.5,
            longitude=-63.0,
        )

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
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

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        fetch_calls.append(tile)
        return _bbox_tile_df(
            8.0,
            dataset_id="thetao_baseline_2000_2019_depthsurf",
            time="2010-01-01",
            latitude=60.0,
            longitude=-65.0,
        )

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            t for t in make_bio_oracle_tools(thread_id)
            if t.name == "enrich_with_bio_oracle"
        )
        enrich.invoke({"variables": ["temperature"], "scenarios": ["baseline"]})

    # Only the 1st point (60, -65) generates a tile fetch — others are out-of-range
    assert len(fetch_calls) == 1
    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert enriched["bio_oracle_match_status"].tolist() == [
        "matched",
        "no_value",
        "no_value",
        "no_value",
    ]


def test_enrich_with_bio_oracle_can_target_specific_dataset_via_source_variable():
    """source_variable cible un dataset persistant au lieu du df actif."""
    import pandas as pd
    from unittest.mock import patch

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-bio-source-var"
    for key in _store.keys(thread_id):
        _store.clear(key)

    filet = pd.DataFrame(
        {
            "station_id": ["FILET-1"],
            "latitude": [60.0],
            "longitude": [-65.0],
        }
    )
    _store.set(
        f"{thread_id}:dataset:df_file_filet",
        filet,
        {"source": "file:filet.tsv", "variable_name": "df_file_filet"},
    )
    uvp = pd.DataFrame(
        {"Profile": ["UVP-A"], "latitude": [74.0], "longitude": [-80.0]}
    )
    _store.set(thread_id, uvp, {"source": "file:uvp.tsv"})

    def fake_fetch_bbox(*, variable, scenario, depth_layer, target_year, tile):
        return _bbox_tile_df(8.42, dataset_id="x", time="2050-01-01")

    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch_bbox
    ):
        enrich = next(
            t for t in make_bio_oracle_tools(thread_id)
            if t.name == "enrich_with_bio_oracle"
        )
        enrich.invoke({
            "source_variable": "df_file_filet",
            "variables": ["temperature"],
            "scenarios": ["SSP5-8.5"],
        })

    keys = _store.keys(f"{thread_id}:dataset:df_bio_oracle_enriched_")
    enriched = _store.get(keys[-1])["df"]
    assert "station_id" in enriched.columns
    assert "Profile" not in enriched.columns
    assert enriched["station_id"].tolist() == ["FILET-1"]
