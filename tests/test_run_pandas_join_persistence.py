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


def test_named_join_is_persisted_when_result_is_only_a_summary(tmp_path):
    store, tools = _tools(tmp_path)
    _load(tools, tmp_path, "stations_a", pd.DataFrame({"station": ["S1", "S2"], "latitude": [60.0, 61.0]}))
    _load(tools, tmp_path, "temps_b", pd.DataFrame({"station": ["S1", "S2"], "temperature": [3.1, 3.5]}))

    out = tools["run_pandas"].invoke(
        {
            "code": (
                "joined = df_file_stations_a.merge(df_file_temps_b, on='station', how='left'); "
                "result = {'shape': joined.shape}"
            )
        }
    )

    assert "persisted=true" in out
    import re

    match = re.search(r"variable=(df_join_[0-9a-f]+)", out)
    assert match, out
    join_var = match.group(1)
    reuse = tools["run_pandas"].invoke(
        {"code": f"result = list({join_var}.columns)"}
    )
    assert "temperature" in reuse and "latitude" in reuse


def test_plain_aggregation_result_stays_ephemeral(tmp_path):
    store, tools = _tools(tmp_path)
    _load(tools, tmp_path, "solo", pd.DataFrame({"station": ["S1", "S1", "S2"], "v": [1, 2, 3]}))

    out = tools["run_pandas"].invoke(
        {"code": "result = df_file_solo.groupby('station', as_index=False)['v'].sum()"}
    )
    assert "persisted=false" in out


def test_modified_copy_of_persisted_join_is_reusable(tmp_path):
    """A named-table update must survive the isolated next pandas call."""
    store, tools = _tools(tmp_path)
    _load(
        tools,
        tmp_path,
        "abundance",
        pd.DataFrame({"sample_id": [1, 2], "cast_number": [10, 20]}),
    )
    _load(
        tools,
        tmp_path,
        "sample",
        pd.DataFrame({"sample_id": [1, 2], "deployment_id": [100, 200]}),
    )

    joined = tools["run_pandas"].invoke(
        {
            "code": (
                "result = df_file_abundance.merge("
                "df_file_sample, on='sample_id', how='left')"
            )
        }
    )
    import re

    join_match = re.search(r"variable=(df_join_[0-9a-f]+)", joined)
    assert join_match, joined
    join_var = join_match.group(1)

    updated = tools["run_pandas"].invoke(
        {
            "code": (
                f"df = {join_var}.copy(); "
                "df['cast_id'] = (df['cast_number'].astype(str) + '_' "
                "+ df['deployment_id'].astype(str)); "
                "result = df"
            )
        }
    )

    assert "persisted=true" in updated
    derived_match = re.search(r"variable=(df_derived_[a-z0-9_]+)", updated)
    assert derived_match, updated
    derived_var = derived_match.group(1)

    reuse = tools["run_pandas"].invoke(
        {"code": f"result = {derived_var}['cast_id'].tolist()"}
    )
    assert "10_100" in reuse
    assert "20_200" in reuse


def test_analytical_merge_does_not_replace_active_join_with_control_table(tmp_path):
    store, tools = _tools(tmp_path)
    _load(
        tools,
        tmp_path,
        "joined_source",
        pd.DataFrame(
            {
                "sample_id": ["S1", "S2", "S3"],
                "year": [2020, 2020, 2021],
                "taxon": ["A", "B", "A"],
                "station": ["ST1", "ST2", "ST1"],
            }
        ),
    )
    active_before = store.get("join-thread")["meta"]["variable_name"]

    out = tools["run_pandas"].invoke(
        {
            "code": (
                "base = df.copy(); "
                "taxon_year = base.groupby(['year', 'taxon'], as_index=False).agg("
                "taxon_samples=('sample_id', 'nunique'), taxon_stations=('station', 'nunique')); "
                "year_totals = base.groupby('year', as_index=False).agg("
                "total_samples=('sample_id', 'nunique'), total_stations=('station', 'nunique')); "
                "control = taxon_year.merge(year_totals, on='year', how='left'); "
                "control['prop_samples'] = control['taxon_samples'] / control['total_samples']; "
                "result = control"
            )
        }
    )

    assert "persisted=false" in out
    assert store.get("join-thread")["meta"]["variable_name"] == active_before
