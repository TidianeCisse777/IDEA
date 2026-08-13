"""Core persistence behavior of controlled pandas execution."""

from __future__ import annotations

import pandas as pd

from tools.data_tools import make_tools
from tools.session_store import SessionStore


def _tools(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    return store, {tool.name: tool for tool in make_tools("join-thread", store=store)}


def _load(tools, tmp_path, name, frame):
    path = tmp_path / f"{name}.csv"
    frame.to_csv(path, index=False)
    tools["load_file"].invoke({"path": str(path)})


def _invoke(tool, **arguments):
    content, artifact = tool.invoke(arguments)
    return content, artifact


def test_merge_is_persisted_and_reusable(tmp_path):
    _, tools = _tools(tmp_path)
    _load(tools, tmp_path, "stations_a", pd.DataFrame({"station": ["S1", "S2"], "latitude": [60.0, 61.0]}))
    _load(tools, tmp_path, "temps_b", pd.DataFrame({"station": ["S1", "S2"], "temperature": [3.1, 3.5]}))

    _, artifact = _invoke(
        tools["run_pandas"],
        code="result = df_file_stations_a.merge(df_file_temps_b, on='station', how='left')",
    )

    assert artifact["persisted"] is True
    assert artifact["data_ref"].startswith("df_join_")
    content, _ = _invoke(
        tools["run_pandas"],
        code=f"result = list({artifact['data_ref']}.columns)",
    )
    assert "temperature" in content and "latitude" in content


def test_plain_aggregation_stays_ephemeral(tmp_path):
    _, tools = _tools(tmp_path)
    _load(tools, tmp_path, "solo", pd.DataFrame({"station": ["S1", "S1", "S2"], "v": [1, 2, 3]}))

    _, artifact = _invoke(
        tools["run_pandas"],
        code="result = df_file_solo.groupby('station', as_index=False)['v'].sum()",
    )

    assert artifact["persisted"] is False
    assert artifact["data_ref"] is None


def test_derived_copy_of_join_is_reusable(tmp_path):
    _, tools = _tools(tmp_path)
    _load(tools, tmp_path, "left", pd.DataFrame({"sample_id": [1, 2], "cast": [10, 20]}))
    _load(tools, tmp_path, "right", pd.DataFrame({"sample_id": [1, 2], "deployment": [100, 200]}))
    _, joined = _invoke(
        tools["run_pandas"],
        code="result = df_file_left.merge(df_file_right, on='sample_id', how='left')",
    )
    _, derived = _invoke(
        tools["run_pandas"],
        code=(
            f"df = {joined['data_ref']}.copy(); "
            "df['cast_id'] = df['cast'].astype(str) + '_' + df['deployment'].astype(str); "
            "result = df"
        ),
    )

    assert derived["persisted"] is True
    content, _ = _invoke(
        tools["run_pandas"],
        code=f"result = {derived['data_ref']}['cast_id'].tolist()",
    )
    assert "10_100" in content and "20_200" in content


def test_recomputing_named_analysis_versions_result_and_preserves_source(tmp_path):
    store, tools = _tools(tmp_path)
    _load(
        tools,
        tmp_path,
        "observations",
        pd.DataFrame({"sample_id": [1, 2], "value": [2.0, 3.0]}),
    )

    _, first = _invoke(
        tools["run_pandas"],
        code="result = df_file_observations.assign(score=lambda frame: frame['value'])",
        persist_as="df_observation_scores",
        description="Scores par observation.",
        grain="une ligne par observation",
        filters={},
    )
    _, second = _invoke(
        tools["run_pandas"],
        code=(
            "result = df_file_observations.assign("
            "score=lambda frame: frame['value'] * 10)"
        ),
        persist_as="df_observation_scores",
        description="Scores corrigés par observation.",
        grain="une ligne par observation",
        filters={},
    )

    assert first["status"] == second["status"] == "success"
    assert first["data_ref"] == second["data_ref"] == "df_observation_scores"
    current = store.get("join-thread:dataset:df_observation_scores")
    assert current is not None
    assert current["meta"]["analysis_key"] == "run_pandas:df_observation_scores"
    assert current["meta"]["version"] == 2
    assert current["meta"]["lifecycle_state"] == "current"
    assert current["df"]["score"].tolist() == [20.0, 30.0]

    archive_keys = store.keys(
        "join-thread:archive:dataset:df_observation_scores:"
    )
    assert len(archive_keys) == 1
    archived = store.get(archive_keys[0])
    assert archived is not None
    assert archived["meta"]["version"] == 1
    assert archived["meta"]["lifecycle_state"] == "superseded"
    assert archived["meta"]["superseded_by"] == "df_observation_scores@v2"
    assert archived["df"]["score"].tolist() == [2.0, 3.0]

    source = store.get("join-thread:dataset:df_file_observations")
    assert source is not None
    assert source["meta"]["retention_class"] == "anchor"
    assert source["meta"]["lifecycle_state"] == "current"


def test_run_pandas_materializes_only_exactly_referenced_dataframes(tmp_path):
    _, tools = _tools(tmp_path)
    for index in range(10):
        _load(
            tools,
            tmp_path,
            f"source_{index:02d}",
            pd.DataFrame({"sample_id": [index], "value": [float(index)]}),
        )

    _, artifact = _invoke(
        tools["run_pandas"],
        code="result = df_file_source_09.head(1)",
    )

    assert artifact["status"] == "success"
    assert artifact["metrics"]["executor_dataframe_input_count"] == 1
    assert artifact["metrics"]["executor_dataframe_inputs"] == [
        "df_file_source_09"
    ]
