"""A join/merge result must persist as a new named df (multi-file workflow)."""

import pandas as pd

from tools.data_tools import make_tools
from tools.session_store import SessionStore


def _tools(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    tools = {t.name: t for t in make_tools("join-thread", store=store)}
    return store, tools


def _load(tools, tmp_path, name, frame):
    path = tmp_path / f"{name}.csv"
    frame.to_csv(path, index=False)
    tools["load_file"].invoke({"path": str(path)})


def test_merge_result_is_persisted_as_new_df(tmp_path):
    store, tools = _tools(tmp_path)
    _load(tools, tmp_path, "stations_a", pd.DataFrame({"station": ["S1", "S2"], "latitude": [60.0, 61.0]}))
    _load(tools, tmp_path, "temps_b", pd.DataFrame({"station": ["S1", "S2"], "temperature": [3.1, 3.5]}))

    out = tools["run_pandas"].invoke(
        {"code": "result = df_file_stations_a.merge(df_file_temps_b, on='station', how='left')"}
    )

    assert "persisted=true" in out
    # the persisted join variable is reusable in a later run_pandas call
    import re

    match = re.search(r"variable=(df_join_[0-9a-f]+)", out)
    assert match, out
    join_var = match.group(1)
    reuse = tools["run_pandas"].invoke({"code": f"result = list({join_var}.columns)"})
    assert "temperature" in reuse and "latitude" in reuse


def test_plain_aggregation_result_stays_ephemeral(tmp_path):
    store, tools = _tools(tmp_path)
    _load(tools, tmp_path, "solo", pd.DataFrame({"station": ["S1", "S1", "S2"], "v": [1, 2, 3]}))

    out = tools["run_pandas"].invoke(
        {"code": "result = df_file_solo.groupby('station', as_index=False)['v'].sum()"}
    )
    assert "persisted=false" in out
