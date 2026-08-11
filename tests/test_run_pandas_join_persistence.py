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
