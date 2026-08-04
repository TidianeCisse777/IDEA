"""Tests TDD — tools/data_tools.py (slice 2)"""
import io
import base64
import sys
from pathlib import Path

import pandas as pd
import pytest

from tools.data_tools import (
    _GRAPHS_DIR,
    make_tools,
    _patch_cartopy_gridliner_polygon,
    _graph_savefig_kwargs,
    _cartopy_safe_tight_layout,
    _uvp_skill_hint,
)
from core.runtime_paths import graphs_dir
from tools.session_store import SessionStore, default_store as _store


_GENERIC_GRAPH_CONTRACT_CODE = """
graph_contract = {
    'kind': 'generic',
    'axes': [{'axis_index': 0, 'x': 'x', 'y': 'y'}],
    'inverted_axes': [],
    'mappings': {},
    'zero_policy': {'mode': 'include', 'artist_gid': None},
    'source_variables': [],
}
"""


@pytest.fixture
def tsv_path(tmp_path):
    df = pd.DataFrame({
        "profile_id": ["ips_007", "ips_008", "ips_009"],
        "depth": [10.5, 25.0, 50.0],
        "temperature": [2.1, 1.8, 1.2],
    })
    p = tmp_path / "sample.tsv"
    df.to_csv(p, sep="\t", index=False)
    return str(p)


@pytest.fixture(autouse=True)
def clear_sessions(monkeypatch):
    """Isolate each test on a fresh in-memory SessionStore (backend-agnostic).

    `make_tools` resolves its store via `tools.data_tools.default_store` at call
    time, so patching that global plus this module's `_store` keeps tool writes
    and test reads on the same in-memory store regardless of
    `SESSION_STORE_DATABASE_URL` (which would otherwise swap in `SessionStorePG`).
    """
    store = SessionStore()
    monkeypatch.setattr("tools.session_store.default_store", store)
    monkeypatch.setattr("tools.data_tools.default_store", store)
    monkeypatch.setattr(sys.modules[__name__], "_store", store)
    yield


def test_run_graph_uses_shared_graphs_directory():
    assert _GRAPHS_DIR == graphs_dir()


# --- Comportement 1 : load_file_tool ---

def test_load_file_tool_stores_df(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert _store.has("thread-1")
    assert _store.get("thread-1")["df"] is not None
    assert _store.get("thread-1")["df"].shape == (3, 3)


def test_load_file_tool_pins_canonical_loaded_file_anchor(tsv_path):
    """load_file doit épingler le fichier sous {thread}:loaded_file pour qu'il
    reste l'ancre canonique après qu'un sous-ensemble a pris le slot actif."""
    from tools.dataset_registry import loaded_file_dataset

    tools = make_tools("thread-anchor")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    load_file_tool.invoke({"path": tsv_path})

    anchor = loaded_file_dataset(_store, "thread-anchor")
    assert anchor is not None
    assert anchor["df"].shape == (3, 3)
    assert anchor["meta"]["source"].startswith("file:")


def test_load_file_tool_returns_summary(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert "3" in result  # n_rows
    assert "profile_id" in result


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("data/neolabs/neolabs_sample.csv", "df_file_neolabs_sample"),
        ("/tmp/webui_uploads/123_neolabs_abundance.csv", "df_file_neolabs_abundance"),
    ],
)
def test_neolabs_file_names_are_stable_across_upload_paths(path, expected):
    from tools.data_tools import _file_variable_name

    assert _file_variable_name(path) == expected


def test_second_loaded_file_invites_the_user_to_name_its_table(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "neolabs_sample.csv"
    pd.DataFrame({"x": [1]}).to_csv(first, index=False)
    pd.DataFrame({"sample_id": ["S1"]}).to_csv(second, index=False)

    load = next(t for t in make_tools("thread-file-reference") if t.name == "load_file")
    load.invoke({"path": str(first)})
    result = load.invoke({"path": str(second)})

    assert "Nouvelle table disponible : `df_file_neolabs_sample`" in result
    assert "Table à citer dans une prochaine demande" in result


def test_loading_both_neolabs_files_routes_join_to_deterministic_preparation(tmp_path):
    abundance_path = tmp_path / "neolabs_abundance.csv"
    sample_path = tmp_path / "neolabs_sample.csv"
    pd.DataFrame(
        {
            "SAMPLE_ID": [1],
            "ANALYSIS_ID": [10],
            "TAXON_ID": ["Calanus"],
            "CLASS": ["Copepoda"],
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [12.0],
        }
    ).to_csv(abundance_path, index=False)
    pd.DataFrame(
        {
            "sample_id": [1],
            "analysis_id": [10],
            "deployment_id": ["D1"],
            "net_sampling_ids": ["N1"],
            "tow_type": ["V-Tow"],
        }
    ).to_csv(sample_path, index=False)

    load = next(t for t in make_tools("thread-neolabs-pair") if t.name == "load_file")
    load.invoke({"path": str(abundance_path)})
    result = load.invoke({"path": str(sample_path)})

    assert "prepare_neolabs_analysis" in result
    assert str(abundance_path) in result
    assert str(sample_path) in result
    assert "astype(str)" in result


def test_run_pandas_marks_truncated_dataframe_preview():
    """Le modèle ne doit pas compléter une table au-delà des lignes visibles."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-pandas-truncated-preview"
    df = pd.DataFrame({"row_id": range(25), "value": range(25)})
    store_dataset(
        _store,
        thread_id,
        df,
        variable_name="df_file_preview",
        meta={"source": "file:test.csv", "n_rows": 25, "n_cols": 2},
        latest_alias="df_file_preview",
        is_loaded_file=True,
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = df.copy()"})

    assert "25 lignes × 2 colonnes" in result
    assert "aperçu des 20 premières lignes seulement" in result
    assert "Ne complète pas les lignes absentes" in result


def test_run_pandas_exposes_loaded_file_after_ecotaxa_result():
    """Le sandbox garde le fichier de référence quand le df actif devient EcoTaxa."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-pandas-cross-source"
    file_df = pd.DataFrame({"sample_id": ["A", "B"]})
    cache_df = pd.DataFrame({"sample_id": ["A", "C"]})
    store_dataset(
        _store,
        thread_id,
        file_df,
        variable_name="df_file_reference",
        meta={"source": "file:test.tsv", "n_rows": 2, "n_cols": 1},
        latest_alias="df_file_reference",
        is_loaded_file=True,
    )
    store_dataset(
        _store,
        thread_id,
        cache_df,
        variable_name="df_ecotaxa_cache_query",
        meta={"source": "ecotaxa_cache", "n_rows": 2, "n_cols": 1},
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({
        "code": "result = loaded_file.merge(df_ecotaxa_cache_query, on='sample_id', how='left', indicator=True)",
    })

    assert "A" in result
    assert "B" in result
    assert "_merge" in result


def test_run_pandas_blocks_string_casts_on_neolabs_join_keys():
    """Casting nullable NeoLabs ids to str must not persist a zero-match join."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-neolabs-unsafe-string-join"
    abundance = pd.DataFrame(
        {
            "SAMPLE_ID": pd.Series([1], dtype="int64"),
            "ANALYSIS_ID": pd.Series([10], dtype="int64"),
            "TAXON_ID": ["Calanus"],
            "CLASS": ["Copepoda"],
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [12.0],
        }
    )
    samples = pd.DataFrame(
        {
            "sample_id": pd.Series([1, 2], dtype="int64"),
            "analysis_id": pd.Series([10.0, pd.NA], dtype="Float64"),
            "deployment_id": ["D1", "D2"],
            "net_sampling_ids": ["N1", "N2"],
            "tow_type": ["V-Tow", "V-Tow"],
        }
    )
    store_dataset(
        _store,
        thread_id,
        abundance,
        variable_name="df_file_neolabs_abundance",
        meta={"source": "file:neolabs_abundance.csv"},
        is_loaded_file=True,
    )
    store_dataset(
        _store,
        thread_id,
        samples,
        variable_name="df_file_neolabs_sample",
        meta={"source": "file:neolabs_sample.csv"},
        is_loaded_file=True,
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke(
        {
            "code": """
ab = df_file_neolabs_abundance.copy()
sm = df_file_neolabs_sample.copy()
ab['ANALYSIS_ID'] = ab['ANALYSIS_ID'].astype(str)
sm['analysis_id'] = sm['analysis_id'].astype(str)
result = ab.merge(
    sm,
    left_on=['SAMPLE_ID', 'ANALYSIS_ID'],
    right_on=['sample_id', 'analysis_id'],
    how='left',
)
""",
            "persist_as": "df_derived_bad_neolabs_join",
        }
    )

    assert "bloqué" in result.casefold()
    assert "astype(str)" in result
    assert "prepare_neolabs_analysis" in result
    assert _store.get(
        f"{thread_id}:dataset:df_derived_bad_neolabs_join"
    ) is None


def test_run_pandas_persists_join_with_readable_description():
    """A persisted df_join_* must carry a human-readable `description` (operands +
    key) so the state capsule can tell joins apart by what they are, not only by
    an opaque hash name — parity with EcoTaxa selections."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-join-description"
    store_dataset(
        _store, thread_id, pd.DataFrame({"sample_id": ["A", "B"]}),
        variable_name="df_file_net",
        meta={"source": "file:net.tsv", "n_rows": 2, "n_cols": 1},
        latest_alias="df_file_net", is_loaded_file=True,
    )
    store_dataset(
        _store, thread_id, pd.DataFrame({"sample_id": ["A", "C"], "temp": [4.0, 5.0]}),
        variable_name="df_ctd",
        meta={"source": "ctd", "n_rows": 2, "n_cols": 2},
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    run_pandas.invoke({
        "code": "result = df_file_net.merge(df_ctd, on='sample_id', how='left')",
    })

    joins = [
        (_store.get(k) or {}).get("meta") or {}
        for k in _store.keys(prefix=f"{thread_id}:dataset:")
        if (((_store.get(k) or {}).get("meta") or {}).get("source") == "analysis:join")
    ]
    assert joins, "join was not persisted"
    description = joins[0].get("description") or ""
    assert "df_file_net" in description
    assert "df_ctd" in description
    assert "sample_id" in description


def test_run_pandas_returns_explicit_printed_control_output():
    """Les tableaux préparés par print ne doivent pas disparaître du tool."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-pandas-printed-control"
    df = pd.DataFrame({"row_id": [1, 2], "value": [10, 20]})
    store_dataset(
        _store,
        thread_id,
        df,
        variable_name="df_file_control",
        meta={"source": "file:test.csv", "n_rows": 2, "n_cols": 2},
        latest_alias="df_file_control",
        is_loaded_file=True,
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({
        "code": "print('CONTROL_ROWS'); print(df.to_markdown(index=False)); result = df",
    })

    assert "Sortie contrôlée du code :" in result
    assert "CONTROL_ROWS" in result
    assert "|        1 |      10 |" in result


def test_run_pandas_returns_printed_output_without_result_assignment():
    """Une pré-vérification imprimée reste exploitable sans DataFrame result."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-pandas-printed-only"
    df = pd.DataFrame({"row_id": [1]})
    store_dataset(
        _store,
        thread_id,
        df,
        variable_name="df_file_printed_only",
        meta={"source": "file:test.csv", "n_rows": 1, "n_cols": 1},
        latest_alias="df_file_printed_only",
        is_loaded_file=True,
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "print('coverage_rows=1')"})

    assert "coverage_rows=1" in result
    assert "aucune variable `result` assignée" in result


def test_load_file_success_replaces_external_source_affinity(tsv_path):
    from tools.source_scope import (
        SourceAffinity,
        read_source_affinity,
        write_source_affinity,
    )

    write_source_affinity(
        _store,
        "thread-file-affinity",
        SourceAffinity(
            active_sources=("ecotaxa",),
            evidence="explicit_name",
            origin_user_text="Explore EcoTaxa",
            updated_at="2026-07-15T12:00:00+00:00",
        ),
    )

    load_file_tool = next(
        tool for tool in make_tools("thread-file-affinity") if tool.name == "load_file"
    )
    load_file_tool.invoke({"path": tsv_path})

    assert read_source_affinity(_store, "thread-file-affinity").active_sources == (
        "file",
    )


def test_load_file_failure_preserves_external_source_affinity(tmp_path):
    from tools.source_scope import (
        SourceAffinity,
        read_source_affinity,
        write_source_affinity,
    )

    original = SourceAffinity(
        active_sources=("ecotaxa",),
        evidence="explicit_name",
        origin_user_text="Explore EcoTaxa",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    write_source_affinity(_store, "thread-file-failure", original)
    load_file_tool = next(
        tool for tool in make_tools("thread-file-failure") if tool.name == "load_file"
    )

    load_file_tool.invoke({"path": str(tmp_path / "missing.tsv")})

    assert read_source_affinity(_store, "thread-file-failure") == original


def test_load_file_preserves_distinct_files_with_named_variables(tmp_path):
    first = tmp_path / "stations 2024.tsv"
    second = tmp_path / "profiles.tsv"
    pd.DataFrame({"station": ["A"]}).to_csv(first, sep="\t", index=False)
    pd.DataFrame({"profile": ["P1"]}).to_csv(second, sep="\t", index=False)

    thread_id = "thread-multi-files"
    load_file_tool = next(t for t in make_tools(thread_id) if t.name == "load_file")
    first_result = load_file_tool.invoke({"path": str(first)})
    second_result = load_file_tool.invoke({"path": str(second)})

    assert _store.get(f"{thread_id}:dataset:df_file_stations_2024")["df"].equals(
        pd.DataFrame({"station": ["A"]})
    )
    assert _store.get(f"{thread_id}:dataset:df_file_profiles")["df"].equals(
        pd.DataFrame({"profile": ["P1"]})
    )
    assert "df_file_stations_2024" in first_result
    assert "df_file_profiles" in second_result


def test_load_file_exposes_ogsl_alias_for_derived_ogsl_csv(tmp_path):
    ogsl_path = tmp_path / "ogsl_iml4.csv"
    pd.DataFrame({
        "longitude": [-68.5],
        "latitude": [48.7],
        "time": ["2024-06-01T00:00:00Z"],
        "cruiseID": ["Mingan2024"],
        "stationID": ["IML4"],
        "TE90": [4.2],
    }).to_csv(ogsl_path, index=False)

    thread_id = "thread-ogsl-file"
    load_file_tool = next(t for t in make_tools(thread_id) if t.name == "load_file")
    load_file_tool.invoke({"path": str(ogsl_path)})

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = list(df_ogsl.columns)"})

    assert "stationID" in result
    assert "TE90" in result


def test_load_file_exposes_ecotaxa_alias_for_uvp_export(tmp_path):
    ecotaxa_path = tmp_path / "ecotaxa_uvp_sample.tsv"
    pd.DataFrame({
        "object_id": ["obj_1", "obj_2"],
        "sample_id": ["ips_007", "ips_007"],
        "object_depth_min": [3.0, 12.0],
        "object_major": [12.5, 8.3],
        "object_annotation_category": ["Calanus", "Oithona"],
    }).to_csv(ecotaxa_path, sep="\t", index=False)

    thread_id = "thread-ecotaxa-file"
    load_file_tool = next(t for t in make_tools(thread_id) if t.name == "load_file")
    load_file_tool.invoke({"path": str(ecotaxa_path)})

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = list(df_ecotaxa.columns)"})

    assert "sample_id" in result
    assert "object_depth_min" in result


def test_load_file_exposes_ecotaxa_alias_for_standard_ecotaxa_export():
    thread_id = "thread-standard-ecotaxa-export"
    load_file_tool = next(t for t in make_tools(thread_id) if t.name == "load_file")
    load_result = load_file_tool.invoke({"path": "data/demo/ecotaxa_sample_50.tsv"})

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = 'df_ecotaxa' in locals()"})

    assert "Alias de session : `ecotaxa`" in load_result
    assert "Route EcoPart" in load_result
    assert result == "True"


def test_load_file_exposes_ecopart_alias_for_uvp_export(tmp_path):
    ecopart_path = tmp_path / "ecopart_uvp_sample.tsv"
    pd.DataFrame({
        "Profile": ["ips_007", "ips_007"],
        "Depth [m]": [2.5, 7.5],
        "Sampled volume [L]": [100.0, 110.0],
        "LPM (1-2 µm) [# l-1]": [1.0, 1.5],
    }).to_csv(ecopart_path, sep="\t", index=False)

    thread_id = "thread-ecopart-file"
    load_file_tool = next(t for t in make_tools(thread_id) if t.name == "load_file")
    load_file_tool.invoke({"path": str(ecopart_path)})

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = list(df_ecopart.columns)"})

    assert "Profile" in result
    assert "Sampled volume [L]" in result


# --- Comportement 2 : run_pandas ---

def test_run_pandas_scalar(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = len(df)"})
    assert "3" in result


def test_run_pandas_dataframe_returns_markdown(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = df.head(2)"})
    assert "profile_id" in result
    assert "lignes" in result
    assert "Persistence: persisted=false; variable=null" in result
    assert "résultat éphémère" in result


def test_run_pandas_dataframe_returns_analysis_attrs(tsv_path):
    tools = make_tools("thread-dataframe-attrs")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    result = run_pandas.invoke(
        {
            "code": (
                "result = df.head(2).copy(); "
                "result.attrs = {'pearson': -0.6417, 'n_retained': 3, "
                "'n_zero_abundance': 1}"
            )
        }
    )

    assert "Attributs d'analyse" in result
    assert '"pearson": -0.6417' in result
    assert '"n_retained": 3' in result
    assert '"n_zero_abundance": 1' in result


def test_run_pandas_persists_canonical_sample_depth_result_for_later_calls(tsv_path):
    thread_id = "thread-canonical-sample-depth"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    first = run_pandas.invoke(
        {
            "code": (
                "canonical = df.head(1).rename(columns={'profile_id': 'sample_id', "
                "'depth': 'depth_bin'}).copy(); "
                "canonical['copepod_count'] = 1; "
                "canonical['sampled_volume_L'] = 100.0; "
                "canonical['abundance_ind_L'] = 0.01; "
                "canonical['abundance_ind_m3'] = 10.0; "
                "canonical['canonical_method_version'] = 'copepod-sample-depth-v1'; "
                "result = canonical"
            )
        }
    )
    second = run_pandas.invoke(
        {"code": "result = int(df_canonical_sample_depth['copepod_count'].sum())"}
    )

    stored = _store.get(
        f"{thread_id}:dataset:df_canonical_sample_depth"
    )
    assert stored is not None
    assert stored["df"]["copepod_count"].tolist() == [1]
    assert "Variable persistante : `df_canonical_sample_depth`" in first
    assert (
        "Persistence: persisted=true; variable=df_canonical_sample_depth" in first
    )
    assert second == "1"


def test_run_pandas_arbitrary_dataframe_is_absent_from_next_call(tsv_path):
    thread_id = "thread-ephemeral-analysis-result"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    first = run_pandas.invoke({
        "code": "temporary_summary = df.head(1).copy(); result = temporary_summary"
    })
    second = run_pandas.invoke({"code": "result = len(temporary_summary)"})

    assert "persisted=false" in first
    assert "NameError" in second
    assert "temporary_summary" in second


def test_run_pandas_persists_explicitly_named_subset_for_later_enrichment(tsv_path):
    """A user-selected subset must be reusable as the exact enrichment source."""
    thread_id = "thread-persisted-subset-for-enrichment"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    result = run_pandas.invoke(
        {
            "code": "result = df.loc[df['profile_id'].eq('ips_007')].copy()",
            "persist_as": "df_subset_ips_007",
        }
    )

    stored = _store.get(f"{thread_id}:dataset:df_subset_ips_007")
    assert stored is not None
    assert stored["df"]["profile_id"].tolist() == ["ips_007"]
    assert "Persistence: persisted=true; variable=df_subset_ips_007" in result


def test_run_pandas_never_overwrites_a_persisted_source_with_persist_as(tsv_path):
    """A staging copy must not silently replace the named source table."""
    from tools.dataset_registry import store_dataset

    thread_id = "thread-persist-as-overwrite-guard"
    tools = make_tools(thread_id)
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    source = pd.DataFrame({"sample_id": ["A", "B"], "value": [1, 2]})
    store_dataset(
        _store,
        thread_id,
        source,
        variable_name="df_ecotaxa_export",
        meta={"source": "ecotaxa:export", "n_rows": 2, "n_cols": 2},
    )

    result = run_pandas.invoke(
        {
            "code": "result = df_ecotaxa_export.head(1).copy()",
            "persist_as": "df_ecotaxa_export",
        }
    )

    stored = _store.get(f"{thread_id}:dataset:df_ecotaxa_export")
    assert "remplacerait une table déjà persistée" in result
    assert stored["df"].shape == (2, 2)


def test_run_pandas_reports_persisted_canonical_zero_count(tsv_path):
    thread_id = "thread-canonical-zero-count"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    output = run_pandas.invoke({
        "code": (
            "result = pd.DataFrame({"
            "'sample_id': ['A', 'A'], 'depth_bin': [2.5, 7.5], "
            "'copepod_count': [1, 0], 'sampled_volume_L': [10.0, 10.0], "
            "'abundance_ind_L': [0.1, 0.0], "
            "'abundance_ind_m3': [100.0, 0.0], "
            "'canonical_method_version': ['copepod-sample-depth-v1'] * 2})"
        )
    })

    stored = _store.get(
        f"{thread_id}:dataset:df_canonical_sample_depth"
    )
    assert "n_zero_abundance=1" in output
    assert stored["meta"]["n_zero_abundance"] == 1


def test_run_pandas_keyerror_points_to_variable_holding_the_column(tsv_path):
    """A KeyError on a column absent from the active df must name the persisted
    df_* variables that DO carry it — so the agent retargets instead of
    concluding the column is missing."""
    thread_id = "thread-keyerror-hint"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    # Persist an enriched table that carries the environmental column.
    _store.set(
        f"{thread_id}:dataset:df_ctd_enriched",
        pd.DataFrame({"object_id": [1], "amundsen_te90_degC": [-1.5]}),
        {"variable_name": "df_ctd_enriched"},
    )

    out = run_pandas.invoke(
        {"code": "result = df['amundsen_te90_degC'].mean()"}
    )

    assert "Erreur" in out
    assert "df_ctd_enriched" in out
    assert "amundsen_te90_degC" in out


@pytest.mark.parametrize(
    ("requested", "canonical"),
    [
        ("TE90", "amundsen_te90_degC"),
        ("PSAL", "amundsen_psal_psu"),
        ("PRES", "amundsen_pres_dbar"),
        ("SIGT", "amundsen_sigt"),
        ("OXYM", "amundsen_oxym"),
        ("pH", "amundsen_ph"),
        ("NTRA", "amundsen_ntra"),
        ("FLOR", "amundsen_flor"),
    ],
)
def test_run_pandas_keyerror_suggests_canonical_amundsen_column(
    tsv_path, requested, canonical
):
    thread_id = f"thread-amundsen-alias-{requested.lower()}"
    tools = make_tools(thread_id)
    next(t for t in tools if t.name == "load_file").invoke({"path": tsv_path})
    _store.set(
        f"{thread_id}:dataset:df_amundsen_enriched_exact",
        pd.DataFrame({canonical: [1.0]}),
        {"variable_name": "df_amundsen_enriched_exact"},
    )

    out = next(t for t in tools if t.name == "run_pandas").invoke(
        {"code": f"result = df[{requested!r}].mean()"}
    )

    assert f"`{requested}`" in out
    assert f"`{canonical}`" in out
    assert "df_amundsen_enriched_exact" in out


def test_run_pandas_persists_canonical_intermediate_carrying_env(tsv_path):
    """A canonical table built as an intermediate (result is something else)
    must still be persisted, with its environmental columns retained."""
    thread_id = "thread-canonical-intermediate"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    first = run_pandas.invoke(
        {
            "code": (
                "canonical = pd.DataFrame({"
                "'sample_id': ['RA25', 'RA25'], 'depth_bin': [12.5, 17.5], "
                "'copepod_count': [1, 3], 'sampled_volume_L': [70.4, 64.0], "
                "'abundance_ind_L': [0.0142, 0.0469], "
                "'abundance_ind_m3': [14.2, 46.9], "
                "'amundsen_te90_degC': [-1.5, -1.4], "
                "'canonical_method_version': ['copepod-sample-depth-v1', "
                "'copepod-sample-depth-v1']})\n"
                "result = canonical[['abundance_ind_L']].corrwith("
                "canonical['amundsen_te90_degC'])"
            )
        }
    )

    stored = _store.get(f"{thread_id}:dataset:df_canonical_sample_depth")
    assert stored is not None
    assert "amundsen_te90_degC" in stored["df"].columns
    assert "df_canonical_sample_depth" in first

    # La table canonique enrichie est réutilisable au tour suivant.
    second = run_pandas.invoke(
        {"code": "result = 'amundsen_te90_degC' in df_canonical_sample_depth.columns"}
    )
    assert second == "True"


def test_run_pandas_exposes_multiple_ecopart_projects():
    thread_id = "thread-run-pandas-multiple-ecopart"
    keys = [
        thread_id,
        f"{thread_id}:ecopart",
        f"{thread_id}:ecopart:105",
        f"{thread_id}:ecopart:42",
    ]
    for key in keys:
        _store.clear(key)

    df_105 = pd.DataFrame({"value": [1, 2, 3]})
    df_42 = pd.DataFrame({"value": [4, 5]})
    _store.set(thread_id, df_42, {"source": "ecopart:42"})
    _store.set(f"{thread_id}:ecopart", df_42, {"source": "ecopart:42"})
    _store.set(f"{thread_id}:ecopart:105", df_105, {"source": "ecopart:105"})
    _store.set(f"{thread_id}:ecopart:42", df_42, {"source": "ecopart:42"})

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({
        "code": "result = (len(df_ecopart_105), len(df_ecopart_42), len(df_ecopart))"
    })

    assert result == "(3, 2, 2)"

    for key in keys:
        _store.clear(key)


def test_run_pandas_exposes_registered_datasets_from_multiple_sources():
    from tools.dataset_registry import store_dataset

    thread_id = "thread-run-pandas-registered"
    df_ecotaxa = pd.DataFrame({"value": [1, 2, 3]})
    df_file = pd.DataFrame({"value": [4, 5]})
    store_dataset(
        _store,
        thread_id,
        df_ecotaxa,
        variable_name="df_ecotaxa_1165",
        meta={"source": "ecotaxa:1165"},
        latest_alias="ecotaxa",
    )
    store_dataset(
        _store,
        thread_id,
        df_file,
        variable_name="df_file_stations_2024",
        meta={"source": "file:stations_2024.tsv"},
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({
        "code": "result = (len(df_ecotaxa_1165), len(df_file_stations_2024))"
    })

    assert result == "(3, 2)"


def test_run_pandas_exposes_ogsl_enriched_table():
    """Régression : une table rangée sous l'alias ogsl_enriched doit être relue
    comme df_ogsl_enriched dans run_pandas (elle disparaissait en silence)."""
    from tools.dataset_registry import store_dataset, OGSL_ENRICHED

    thread_id = "thread-run-pandas-ogsl-enriched"
    df_base = pd.DataFrame({"value": [1, 2, 3]})
    df_enriched = pd.DataFrame({"value": [1, 2, 3, 4]})
    store_dataset(_store, thread_id, df_base,
                  variable_name="df_file_ogsl", meta={"source": "file:ogsl"})
    store_dataset(_store, thread_id, df_enriched,
                  variable_name="df_ogsl_enriched",
                  meta={"source": "ogsl_enriched"}, latest_alias=OGSL_ENRICHED)

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = len(df_ogsl_enriched)"})

    assert result == "4"

    for key in (thread_id, f"{thread_id}:ogsl_enriched",
                f"{thread_id}:dataset:df_ogsl_enriched"):
        _store.clear(key)


def test_run_pandas_can_execute_sklearn_pca_for_ordination(tsv_path):
    tools = make_tools("thread-pca")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})

    result = run_pandas.invoke({
        "code": """
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

X = df[["depth", "temperature"]].astype(float)
scores = PCA(n_components=2).fit_transform(StandardScaler().fit_transform(X))
result = pd.DataFrame(scores, columns=["PC1", "PC2"]).round(6)
"""
    })

    assert "PC1" in result
    assert "PC2" in result
    assert "Erreur" not in result


# --- Comportement 3 : erreur pandas ---

def test_run_pandas_error_shows_columns(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = df['colonne_inexistante'].mean()"})
    assert "Erreur" in result
    assert "profile_id" in result  # aperçu colonnes


# --- Comportement 4 : sans fichier ---

def test_run_pandas_no_file_loaded():
    tools = make_tools("thread-sans-fichier")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = df.head()"})
    assert "aucun fichier" in result.lower()


# --- Comportement 5 : run_graph renvoie seulement l'artefact ---

def test_run_graph_returns_artifact_without_tool_caption(tmp_path):
    thread_id = "thread-graph"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_graph = next(t for t in tools if t.name == "run_graph")

    df = pd.DataFrame({
        "depth": [10, 20, 30],
        "temperature": [2.1, 1.8, 1.2],
    })
    p = tmp_path / "graph.tsv"
    df.to_csv(p, sep="\t", index=False)
    load_file_tool.invoke({"path": str(p)})
    _store.update_meta(thread_id, {"loaded_skills": ["graph_writer"]})

    code = """
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(df["depth"], df["temperature"], marker="o")
ax.set_title("Température par profondeur")
ax.set_xlabel("Profondeur (m)")
ax.set_ylabel("Température (°C)")
graph_explanation = (
    "Lecture rapide:\\n"
    "- Le graphe relie profondeur et température pour visualiser la tendance verticale.\\n"
    "- La courbe en ligne met en évidence la décroissance de température avec la profondeur.\\n"
    "- Le code reste minimal pour conserver une lecture directe du profil."
)
"""

    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})
    assert "/graphs/" in result
    assert "Lecture rapide" not in result
    assert "courbe en ligne" not in result


def test_successful_graph_persists_its_editable_state(tmp_path):
    """La prochaine retouche doit repartir du script réellement rendu."""
    thread_id = "thread-editable-graph"
    tools = make_tools(thread_id)
    load_file = next(tool for tool in tools if tool.name == "load_file")
    run_graph = next(tool for tool in tools if tool.name == "run_graph")
    path = tmp_path / "graph.tsv"
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_csv(path, sep="\t", index=False)
    load_file.invoke({"path": str(path)})
    _store.update_meta(thread_id, {"loaded_skills": ["graph_writer"]})
    code = (
        "fig, ax = plt.subplots()\n"
        "plot_df = df[['x', 'y']].copy()\n"
        "ax.plot(plot_df['x'], plot_df['y'])\n"
        + _GENERIC_GRAPH_CONTRACT_CODE
    )

    run_graph.invoke({"code": code})

    state = _store.get(f"{thread_id}:last_graph_state")
    assert state is not None
    assert state["meta"]["code"] == code
    assert state["meta"]["plot_data_ref"] == "df_graph_plot"
    assert state["meta"]["graph_id"]


def test_failed_graph_edit_keeps_the_last_successful_state(tmp_path):
    thread_id = "thread-edit-failure"
    tools = make_tools(thread_id)
    load_file = next(tool for tool in tools if tool.name == "load_file")
    run_graph = next(tool for tool in tools if tool.name == "run_graph")
    path = tmp_path / "graph.tsv"
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_csv(path, sep="\t", index=False)
    load_file.invoke({"path": str(path)})
    _store.update_meta(thread_id, {"loaded_skills": ["graph_writer"]})
    original_code = "fig, ax = plt.subplots()\nax.plot(df['x'], df['y'])\n" + _GENERIC_GRAPH_CONTRACT_CODE
    run_graph.invoke({"code": original_code})

    failed = run_graph.invoke({"code": "raise RuntimeError('retouche invalide')"})

    state = _store.get(f"{thread_id}:last_graph_state")
    assert "retouche invalide" in failed
    assert state["meta"]["code"] == original_code


def test_later_successful_graph_replaces_the_editable_state(tmp_path):
    thread_id = "thread-replace-graph"
    tools = make_tools(thread_id)
    load_file = next(tool for tool in tools if tool.name == "load_file")
    run_graph = next(tool for tool in tools if tool.name == "run_graph")
    path = tmp_path / "graph.tsv"
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_csv(path, sep="\t", index=False)
    load_file.invoke({"path": str(path)})
    _store.update_meta(thread_id, {"loaded_skills": ["graph_writer"]})
    first = "fig, ax = plt.subplots()\nax.plot(df['x'], df['y'])\n" + _GENERIC_GRAPH_CONTRACT_CODE
    second = "fig, ax = plt.subplots()\nax.bar(df['x'], df['y'])\n" + _GENERIC_GRAPH_CONTRACT_CODE

    run_graph.invoke({"code": first})
    first_state = _store.get(f"{thread_id}:last_graph_state")["meta"]
    run_graph.invoke({"code": second})
    second_state = _store.get(f"{thread_id}:last_graph_state")["meta"]

    assert second_state["code"] == second
    assert second_state["graph_id"] != first_state["graph_id"]


def test_run_graph_works_without_loaded_file_for_standalone_map():
    """Carte d'une zone nommée : pas de df nécessaire, run_graph doit exécuter."""
    thread_id = "thread-standalone-graph"
    _store.clear(thread_id)
    _store.set(thread_id, None, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id) if t.name == "run_graph")
    code = (
        "fig, ax = plt.subplots(figsize=(4, 4))\n"
        "ax.text(0.5, 0.5, 'Mer du Labrador', ha='center', va='center')\n"
        "ax.set_xlim(0, 1); ax.set_ylim(0, 1)\n"
    )
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})
    assert "/graphs/" in result
    assert "No file loaded" not in result

    _store.clear(thread_id)


def test_run_graph_requires_graph_writer_after_loaded_analysis_skill(tmp_path):
    thread_id = "thread-graph-writer-gate"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["neolabs_abundance_analysis"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    result = run_graph.invoke({
        "code": (
            "fig, ax = plt.subplots(); ax.plot(df['x'], df['y'])"
            + _GENERIC_GRAPH_CONTRACT_CODE
        ),
    })

    assert "/graphs/" in result
    assert store.get(thread_id)["meta"]["loaded_skills"] == [
        "neolabs_abundance_analysis",
        "graph_writer",
    ]


def test_run_graph_infers_generic_contract_when_missing(tmp_path):
    """A plain matplotlib figure without graph_contract now auto-infers a generic contract."""
    thread_id = "thread-missing-graph-contract"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({"x": [1, 2], "y": [3, 4]}),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")

    result = run_graph.invoke({
        "code": "fig, ax = plt.subplots(); ax.set_xlabel('x'); ax.set_ylabel('y'); ax.plot(df['x'], df['y'])",
    })

    assert "/graphs/" in result


def test_run_graph_upgrades_an_unambiguous_lat_lon_scatter_to_station_map(tmp_path):
    """A model omission must not turn a valid cast map into a blocked turn."""
    pytest.importorskip("cartopy.crs")
    thread_id = "thread-cast-map-contract-fallback"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame(
            {
                "cast_id": ["cast-01", "cast-02"],
                "lon": [-71.2, -70.7],
                "lat": [78.3, 78.8],
            }
        ),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")

    result = run_graph.invoke({"code": """
fig, ax = plt.subplots(figsize=(8, 8))
ax.scatter(df['lon'], df['lat'], s=40, c='tab:blue')
ax.set_title('Casts dans la baie de Baffin')
ax.set_xlabel('Longitude')
ax.set_ylabel('Latitude')
"""})

    assert "/graphs/" in result
    assert store.get(thread_id)["meta"]["graph_quality_blocked"] is False


def test_run_graph_renders_compliant_vertical_profile_contract(tmp_path):
    thread_id = "thread-valid-vertical-contract"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({"depth_m": [5, 10], "abundance_ind_L": [0.0, 1.2]}),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots()
ax.plot(df['abundance_ind_L'], df['depth_m'])
ax.invert_yaxis()
graph_contract = {
    'kind': 'vertical_profile',
    'axes': [{'axis_index': 0, 'x': 'abundance_ind_L', 'y': 'depth_m'}],
    'inverted_axes': [{'axis_index': 0, 'axis': 'y'}],
    'mappings': {},
    'zero_policy': {'mode': 'include', 'artist_gid': None},
    'source_variables': ['abundance_ind_L', 'depth_m'],
}
"""

    result = run_graph.invoke({"code": code})

    assert "/graphs/" in result
    assert store.get(thread_id)["meta"]["graph_quality_blocked"] is False


def test_run_graph_renders_two_panel_temperature_salinity_profile(tmp_path):
    thread_id = "thread-environmental-vertical-contract"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({
            "depth_m": [0.0, 10.0, 20.0],
            "temperature_degC": [-0.8, -1.0, -1.3],
            "salinity_psu": [30.1, 30.7, 31.2],
        }),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    result = run_graph.invoke({"code": """
fig, axes = plt.subplots(1, 2, sharey=True)
axes[0].plot(df['temperature_degC'], df['depth_m'])
axes[1].plot(df['salinity_psu'], df['depth_m'])
axes[0].set_xlabel('Température (°C)'); axes[0].set_ylabel('Profondeur (m)')
axes[1].set_xlabel('Salinité (PSU)')
axes[0].invert_yaxis()
graph_contract = {
    'kind': 'vertical_profile',
    'axes': [
        {'axis_index': 0, 'x': 'temperature_degC', 'y': 'depth_m'},
        {'axis_index': 1, 'x': 'salinity_psu', 'y': 'depth_m'},
    ],
    'inverted_axes': [
        {'axis_index': 0, 'axis': 'y'},
        {'axis_index': 1, 'axis': 'y'},
    ],
    'mappings': {},
    'zero_policy': {'mode': 'include', 'artist_gid': None},
    'source_variables': ['temperature_degC', 'salinity_psu', 'depth_m'],
}
"""})

    assert "/graphs/" in result
    assert store.get(thread_id)["meta"]["graph_quality_blocked"] is False


def test_run_graph_requires_derived_abundance_for_raw_object_export(tmp_path):
    thread_id = "thread-object-grain-profile"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({
            "object_id": ["a", "b"],
            "object_depth_min": [10.0, 20.0],
            "object_annotation_category": ["Ostracoda", "Ostracoda"],
        }),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")

    result = run_graph.invoke({
        "code": "raise ValueError('No abundance column found in active enriched table')"
    })

    assert "one object per row" in result
    assert "count object_id by sample_id and object_depth_min" in result


def test_run_graph_renders_compact_legend_for_thirty_vertical_profiles(tmp_path):
    thread_id = "thread-vertical-profile-compact-legend"
    profiles = [f"profile-{index:02d}" for index in range(30)]
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({
            "profile": profiles,
            "depth_m": list(range(30)),
            "abundance_ind_m3": list(range(30)),
        }),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(10, 8))
for profile, group in df.groupby('profile'):
    ax.plot(group['abundance_ind_m3'], group['depth_m'], label=profile)
ax.invert_yaxis()
ax.legend(ncol=3, fontsize=6)
graph_contract = {
    'kind': 'vertical_profile',
    'axes': [{'axis_index': 0, 'x': 'abundance_ind_m3', 'y': 'depth_m'}],
    'inverted_axes': [{'axis_index': 0, 'axis': 'y'}],
    'mappings': {},
    'zero_policy': {'mode': 'include', 'artist_gid': None},
    'source_variables': ['profile', 'depth_m', 'abundance_ind_m3'],
}
"""

    result = run_graph.invoke({"code": code})

    assert "/graphs/" in result
    assert store.get(thread_id)["meta"]["graph_quality_blocked"] is False


def test_compact_vertical_profile_legend_keeps_tick_readability_guard(tmp_path):
    thread_id = "thread-vertical-profile-compact-legend-ticks"
    profiles = [f"profile-{index:02d}" for index in range(30)]
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({
            "profile": profiles,
            "depth_m": list(range(30)),
            "abundance_ind_m3": list(range(30)),
        }),
        {"loaded_skills": ["graph_writer"]},
    )
    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(10, 8))
for profile, group in df.groupby('profile'):
    ax.plot(group['abundance_ind_m3'], group['depth_m'], label=profile)
ax.invert_yaxis()
ax.legend(ncol=3, fontsize=6)
ax.set_xticks(range(60))
graph_contract = {
    'kind': 'vertical_profile',
    'axes': [{'axis_index': 0, 'x': 'abundance_ind_m3', 'y': 'depth_m'}],
    'inverted_axes': [{'axis_index': 0, 'axis': 'y'}],
    'mappings': {},
    'zero_policy': {'mode': 'include', 'artist_gid': None},
    'source_variables': ['profile', 'depth_m', 'abundance_ind_m3'],
}
"""

    result = run_graph.invoke({"code": code})

    assert "Graph quality blocked" in result
    assert "tick labels" in result


def test_run_pandas_persists_explicit_named_derived_dataframe(tmp_path):
    thread_id = "thread-derived-dataframe"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        thread_id,
        pd.DataFrame({"depth_m": [5.0, 10.0], "abundance_ind_L": [1.0, 2.0]}),
        {"loaded_skills": ["graph_writer"]},
    )
    run_pandas = next(t for t in make_tools(thread_id, store=store) if t.name == "run_pandas")

    result = run_pandas.invoke({"code": """
abundance_df = df.assign(abundance_ind_m3=df['abundance_ind_L'] * 1000)
result = abundance_df
"""})

    persisted = store.get(f"{thread_id}:dataset:df_derived_abundance_df")
    assert "Persistence: persisted=true; variable=df_derived_abundance_df" in result
    assert persisted is not None
    assert persisted["df"]["abundance_ind_m3"].tolist() == [1000.0, 2000.0]


def test_run_graph_blocks_unreadable_oversized_figures(tmp_path):
    thread_id = "thread-oversized-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    result = run_graph.invoke({
        "code": (
            "fig, ax = plt.subplots(figsize=(10, 22)); ax.plot(df['x'], df['y'])"
            + _GENERIC_GRAPH_CONTRACT_CODE
        ),
    })

    assert "Graph quality blocked" in result
    assert "figure size" in result
    assert "/graphs/" not in result


def test_run_graph_blocks_legends_with_too_many_entries(tmp_path):
    thread_id = "thread-legend-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(8, 6))
for i in range(25):
    ax.plot([1, 2], [i, i + 1], label=f"group-{i}")
ax.legend()
"""
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert "Graph quality blocked" in result
    assert "legend entries" in result
    assert "/graphs/" not in result


def test_run_graph_blocks_dense_opaque_scatter(tmp_path):
    """Overplotting guard: a scatter with many fully opaque points hides the
    distribution and must be blocked (conservative threshold)."""
    thread_id = "thread-overplot-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
import numpy as np
fig, ax = plt.subplots(figsize=(8, 6))
rng = np.random.default_rng(0)
ax.scatter(rng.random(2500), rng.random(2500))
"""
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert "Graph quality blocked" in result
    assert "alpha" in result.lower() or "transparence" in result.lower()
    assert "/graphs/" not in result


def test_run_graph_allows_dense_scatter_with_transparency(tmp_path):
    """The same dense scatter renders once transparency makes the density
    readable — the guard is conservative, not a blanket point-count cap."""
    thread_id = "thread-overplot-ok-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
import numpy as np
fig, ax = plt.subplots(figsize=(8, 6))
rng = np.random.default_rng(0)
ax.scatter(rng.random(2500), rng.random(2500), alpha=0.4, s=6)
"""
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert "Graph quality blocked" not in result
    assert "/graphs/" in result


def test_run_graph_blocks_too_many_visible_tick_labels(tmp_path):
    thread_id = "thread-tick-label-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": list(range(80)), "y": list(range(80))})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(10, 8))
ax.imshow([[0, 1], [1, 0]])
ax.invert_yaxis()
ax.set_yticks(range(80))
ax.set_yticklabels([f"station-{i}" for i in range(80)])
"""
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert "Graph quality blocked" in result
    assert "tick labels" in result
    assert "/graphs/" not in result


def test_run_graph_blocks_overlong_tick_labels(tmp_path):
    thread_id = "thread-long-label-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(10, 8))
ax.imshow([[0, 1], [1, 0]])
ax.invert_yaxis()
ax.set_xticks(range(12))
ax.set_xticklabels([
    "Animalia | Arthropoda | Copepoda | Calanoida | Calanidae | Calanus hyperboreus"
    for _ in range(12)
], rotation=45)
"""
    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert "Graph quality blocked" in result
    assert "tick labels are too long" in result
    assert "call run_graph again" in result
    assert "/graphs/" not in result


def test_run_pandas_refuses_table_after_graph_quality_block(tmp_path):
    thread_id = "thread-graph-quality-recovery"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(
        thread_id,
        df,
        {"loaded_skills": ["graph_writer"], "graph_quality_blocked": True},
    )

    run_pandas = next(t for t in make_tools(thread_id, store=store) if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = df"})

    assert "Graph quality recovery" in result
    assert "call run_graph again" in result
    assert "x" not in result


def test_cartopy_gridliner_polygon_patch_closes_open_ring():
    gridliner = pytest.importorskip("cartopy.mpl.gridliner")

    _patch_cartopy_gridliner_polygon()
    poly = gridliner.sgeom.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])

    assert poly.exterior.is_ring


def test_cartopy_gridliner_polygon_patch_removes_non_finite_vertices():
    gridliner = pytest.importorskip("cartopy.mpl.gridliner")

    _patch_cartopy_gridliner_polygon()
    poly = gridliner.sgeom.Polygon(
        [(0, 0), (1, 0), (float("nan"), float("nan")), (1, 1), (0, 1)]
    )

    assert poly.exterior.is_ring
    assert all(
        pd.notna(value)
        for coordinate in poly.exterior.coords
        for value in coordinate
    )


def test_cartopy_gridliner_polygon_patch_turns_all_nan_ring_into_empty_polygon():
    gridliner = pytest.importorskip("cartopy.mpl.gridliner")

    _patch_cartopy_gridliner_polygon()
    poly = gridliner.sgeom.Polygon(
        [(float("nan"), float("nan"))] * 4
    )

    assert poly.is_empty


def test_cartopy_graphs_skip_tight_bbox_but_regular_graphs_keep_it():
    ccrs = pytest.importorskip("cartopy.crs")
    import matplotlib.pyplot as plt

    plt.close("all")
    plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    assert _graph_savefig_kwargs(plt) == {"format": "png"}

    plt.close("all")
    plt.subplots()
    assert _graph_savefig_kwargs(plt) == {
        "format": "png",
        "bbox_inches": "tight",
    }
    plt.close("all")


def test_cartopy_safe_tight_layout_skips_geoaxes_but_keeps_regular_axes(monkeypatch):
    ccrs = pytest.importorskip("cartopy.crs")
    import matplotlib.pyplot as plt

    plt.close("all")
    geo_figure, _ = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    monkeypatch.setattr(
        geo_figure,
        "tight_layout",
        lambda *args, **kwargs: pytest.fail("tight_layout called for Cartopy"),
    )
    with _cartopy_safe_tight_layout(plt):
        plt.tight_layout()

    plt.close("all")
    regular_figure, _ = plt.subplots()
    called = []
    monkeypatch.setattr(
        regular_figure,
        "tight_layout",
        lambda *args, **kwargs: called.append(True),
    )
    with _cartopy_safe_tight_layout(plt):
        plt.tight_layout()

    assert called == [True]
    plt.close("all")


def test_run_graph_skips_model_tight_layout_for_cartopy():
    pytest.importorskip("cartopy.crs")
    thread_id = "thread-cartopy-safe-tight-layout"
    _store.clear(thread_id)
    _store.set(thread_id, None, {"loaded_skills": ["graph_writer"]})
    run_graph = next(t for t in make_tools(thread_id) if t.name == "run_graph")
    code = """
import cartopy.crs as ccrs
fig, ax = plt.subplots(subplot_kw={'projection': ccrs.PlateCarree()})
fig.tight_layout = lambda *args, **kwargs: (_ for _ in ()).throw(
    ValueError('Cartopy tight_layout must be skipped')
)
ax.scatter([-60], [55], transform=ccrs.PlateCarree())
plt.tight_layout()
"""

    result = run_graph.invoke({"code": code + _GENERIC_GRAPH_CONTRACT_CODE})

    assert result.startswith("![graph](")
    assert "/graphs/" in result


def test_run_graph_exposes_multiple_ecopart_projects():
    thread_id = "thread-run-graph-multiple-ecopart"
    keys = [
        thread_id,
        f"{thread_id}:ecopart",
        f"{thread_id}:ecopart:105",
        f"{thread_id}:ecopart:42",
    ]
    for key in keys:
        _store.clear(key)

    df_105 = pd.DataFrame({"value": [1, 2, 3]})
    df_42 = pd.DataFrame({"value": [4, 5]})
    _store.set(thread_id, df_42, {"source": "ecopart:42"})
    _store.set(f"{thread_id}:ecopart", df_42, {"source": "ecopart:42"})
    _store.set(f"{thread_id}:ecopart:105", df_105, {"source": "ecopart:105"})
    _store.set(f"{thread_id}:ecopart:42", df_42, {"source": "ecopart:42"})
    _store.update_meta(thread_id, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id) if t.name == "run_graph")
    result = run_graph.invoke({
        "code": (
            "fig, ax = plt.subplots()\n"
            "ax.bar(['105', '42'], [len(df_ecopart_105), len(df_ecopart_42)])"
            + _GENERIC_GRAPH_CONTRACT_CODE
        )
    })

    assert "/graphs/" in result
    assert "NameError" not in result

    for key in keys:
        _store.clear(key)


# --- Détection UVP : _uvp_skill_hint ---

def test_uvp_hint_ecotaxa_fre_major():
    """fre_major + sample_id → hint uvp_ecotaxa."""
    cols = ["object_id", "sample_id", "fre_major", "fre_area", "txo_display_name"]
    hint = _uvp_skill_hint(cols)
    assert "uvp_ecotaxa" in hint


def test_uvp_hint_ecotaxa_object_major():
    """object_major (UVP5) + sample_id → hint uvp_ecotaxa."""
    cols = ["object_id", "sample_id", "object_major", "object_area", "object_annotation_category"]
    hint = _uvp_skill_hint(cols)
    assert "uvp_ecotaxa" in hint


def test_uvp_hint_ecopart():
    """Sampled volume [L] + LPM → hint uvp_ecopart."""
    cols = ["Profile", "Depth [m]", "Sampled volume [L]", "LPM (64-128 µm) [# l-1]"]
    hint = _uvp_skill_hint(cols)
    assert "uvp_ecopart" in hint


def test_uvp_hint_none_for_generic_file():
    """Fichier sans signature UVP → pas de hint."""
    cols = ["station", "depth", "temperature", "salinity"]
    hint = _uvp_skill_hint(cols)
    assert hint == ""


def _neolabs_tsv(tmp_path):
    p = tmp_path / "neolabs.tsv"
    pd.DataFrame({
        "SAMPLE_ID": [1, 1, 2],
        "STATION_NAME": ["A", "A", "A"],
        "TAXON_ID": ["Calanus", "Oithona", "Calanus"],
        "CLASS": ["Copepoda", "Copepoda", "Copepoda"],
        "Total abundance (ind./m3 depth vol)": [10.0, 5.0, 20.0],
        "latitude": [60.0, 60.0, 60.0],
        "longitude": [-65.0, -65.0, -65.0],
    }).to_csv(p, sep="\t", index=False)
    return str(p)


def test_run_pandas_blocks_handrolled_neolabs_copepod_density(tmp_path):
    thread_id = "thread-neolabs-guard"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": _neolabs_tsv(tmp_path)})

    out = run_pandas.invoke({
        "code": (
            "cop = df[df['CLASS'] == 'Copepoda']\n"
            "result = cop.groupby('STATION_NAME')"
            "['Total abundance (ind./m3 depth vol)'].sum()"
        )
    })

    assert "bloqué" in out
    assert "neolabs_copepod_density" in out


def test_run_pandas_allows_neolabs_contract_call(tmp_path):
    thread_id = "thread-neolabs-contract"
    tools = make_tools(thread_id)
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": _neolabs_tsv(tmp_path)})

    out = run_pandas.invoke({
        "code": (
            "from core.neolabs_abundance import neolabs_copepod_density\n"
            "result = neolabs_copepod_density(df)"
        )
    })

    assert "bloqué" not in out
    # station A : sample1=15, sample2=20 -> moyenne 17.5
    assert "17.5" in out


def test_hint_neolabs_taxonomy_routes_to_contract():
    """Fichier NeoLabs taxonomy → hint skill + contrat neolabs_copepod_density."""
    cols = [
        "SAMPLE_ID", "STATION_NAME", "TAXON_ID", "CLASS",
        "Total abundance (ind./m3 depth vol)", "latitude", "longitude",
    ]
    hint = _uvp_skill_hint(cols)
    assert "neolabs_abundance_analysis" in hint
    assert "neolabs_copepod_density" in hint
    assert "moyenne tous-taxons" in hint


def test_uvp_hint_taxa_db_intermediate_does_not_trigger():
    """taxa_db.csv intermédiaire (sortie de scripts/uvp_metrics_pipeline.py)
    a sample_id + depth_bin + sampled_volume + category mais PAS object_major.
    Sa signature de colonnes est trop générique (un export filet ZooScan
    pourrait matcher), donc on NE déclenche PAS de hint au load_file.

    Le routing vers uvp_ecotaxa pour cette table est désormais piloté par
    intent (system prompt: "user asks abundance/density on UVP-like df →
    load_skill uvp_ecotaxa"), pas par hint au load_file. Voir la règle
    "UVP abundance / density intent" dans agents/copepod_system_prompt.py.
    """
    cols = [
        "cruise", "ship", "station", "sample_id", "lat", "lon",
        "date", "time", "object_id",
        "depth", "depth_bin", "sampled_volume",
        "status", "category", "hierarchy", "ctd_filename",
    ]
    hint = _uvp_skill_hint(cols)
    assert hint == ""


def test_uvp_hint_taxa_morpho_db_intermediate():
    """taxa_morpho_db.csv (intermédiaire) a object_major + sample_id : le
    hint doit déjà se déclencher (règle historique préservée).
    """
    cols = [
        "station", "sample_id", "lat", "lon", "object_id",
        "category", "depth", "object_area", "object_major",
        "object_skeleton_area",
    ]
    hint = _uvp_skill_hint(cols)
    assert "uvp_ecotaxa" in hint


# Note: a previous version of this file asserted that the hint must NOT match
# on net-sample exports (WP2, Multinet, ZooScan with sample_id/depth_bin/
# sampled_volume/category in lowercase). We dropped that strict requirement
# on purpose: a false positive is mild (the skill itself now contains a
# "Not for net samples" guard at the top — see agents/skills/uvp_ecotaxa.md),
# while a false negative (missing the UVP hint on a real UVP intermediate
# table) was the actual bug that produced wrong m5 rankings. Keep the
# signature broad; let the skill content disambiguate at read time.


def test_load_file_includes_uvp_hint(tmp_path):
    """load_file sur un fichier EcoPart → réponse inclut le hint uvp_ecopart."""
    df = pd.DataFrame({
        "Profile":             ["ips_007"],
        "Depth [m]":           [5.0],
        "Sampled volume [L]":  [98.5],
        "LPM (64-128 µm) [# l-1]": [12.3],
    })
    p = tmp_path / "ecopart.tsv"
    df.to_csv(p, sep="\t", index=False)

    tools = make_tools("thread-uvp")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": str(p)})
    assert "uvp_ecopart" in result


def test_ecotaxa_demo_export_does_not_trigger_uvp_hint():
    """Un export EcoTaxa de démo ne doit pas déclencher le hint UVP raw."""
    path = Path("data/demo/ecotaxa_sample_50.tsv")
    df = pd.read_csv(path, sep="\t")

    hint = _uvp_skill_hint(list(df.columns))

    assert hint == ""


def test_graph_recovery_pending_requires_block_and_graph_writer():
    from tools.data_tools import graph_recovery_pending

    assert graph_recovery_pending(
        {"graph_quality_blocked": True, "loaded_skills": ["graph_writer"]}) is True
    # graph_writer pas chargé → pas de recovery
    assert graph_recovery_pending(
        {"graph_quality_blocked": True, "loaded_skills": ["graph_planner"]}) is False
    # pas de blocage → pas de recovery
    assert graph_recovery_pending(
        {"graph_quality_blocked": False, "loaded_skills": ["graph_writer"]}) is False
    assert graph_recovery_pending({}) is False


def test_graph_block_clears_on_new_user_turn_not_mid_loop(tmp_path):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from tools.data_tools import _mark_graph_quality_blocked, reset_graph_block_on_new_turn
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    tid = "thread-graph-turn"
    store.update_meta(tid, {"loaded_skills": ["graph_writer"]})
    _mark_graph_quality_blocked(store, tid)

    # Milieu de boucle ReAct : dernier message = résultat d'outil → flag conservé.
    reset_graph_block_on_new_turn(
        store, tid,
        [HumanMessage("fais un graphe"), AIMessage(""),
         ToolMessage("blocked", tool_call_id="c1")],
    )
    assert (store.get(tid)["meta"] or {}).get("graph_quality_blocked") is True

    # Nouveau tour utilisateur : dernier message = message humain → flag effacé.
    reset_graph_block_on_new_turn(
        store, tid,
        [ToolMessage("blocked", tool_call_id="c1"), HumanMessage("moyenne de X ?")],
    )
    assert (store.get(tid)["meta"] or {}).get("graph_quality_blocked") is False


def test_run_pandas_unblocks_after_new_user_turn(tmp_path):
    """Régression du flag collant : après un graphe bloqué, run_pandas est gaté
    dans le même tour, mais répond à nouveau au tour utilisateur suivant."""
    from langchain_core.messages import HumanMessage

    from tools.dataset_registry import store_dataset
    from tools.data_tools import _mark_graph_quality_blocked, reset_graph_block_on_new_turn
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    tid = "thread-graph-jam"
    df = pd.DataFrame({"x": [1, 2, 3]})
    store_dataset(store, tid, df, variable_name="df_file_x", meta={"source": "file:x"})
    store.update_meta(tid, {"loaded_skills": ["graph_writer"]})
    _mark_graph_quality_blocked(store, tid)

    run_pandas = next(t for t in make_tools(tid, store=store) if t.name == "run_pandas")

    # Même tour : le repli tableau est bloqué (protection conservée).
    blocked = run_pandas.invoke({"code": "result = len(df)"})
    assert "recovery" in blocked.lower()

    # Nouveau tour utilisateur : le flag est réarmé, run_pandas répond.
    reset_graph_block_on_new_turn(store, tid, [HumanMessage("moyenne de X ?")])
    ok = run_pandas.invoke({"code": "result = len(df)"})
    assert ok == "3"


def test_run_graph_can_access_plot_df_persisted_by_run_pandas(tmp_path):
    """run_graph must see a DataFrame that run_pandas persisted as plot_df.

    The root cause of the missing rank-abundance graph: the agent does
    `plot_df = ...; result = plot_df` in run_pandas, then tries to use
    `plot_df` in run_graph — but run_graph only sees persisted DataFrames,
    not the ephemeral `result`. After this fix, the persisted `plot_df`
    variable must be available in run_graph's execution namespace.
    """
    from tools.dataset_registry import store_dataset

    store = SessionStore(tmp_path / "sessions")
    tid = "thread-plot-df"

    df = pd.DataFrame({"taxon": ["Calanus", "Oithona"], "abundance": [100.0, 50.0]})
    store_dataset(store, tid, df, variable_name="df_file_taxa",
                  meta={"source": "file:taxa.csv"})
    store.update_meta(tid, {"loaded_skills": ["graph_writer"]})

    tools_list = make_tools(tid, store=store)
    run_pandas = next(t for t in tools_list if t.name == "run_pandas")
    run_graph_tool = next(t for t in tools_list if t.name == "run_graph")

    # run_pandas persists plot_df
    run_pandas.invoke({
        "code": (
            "plot_df = df_file_taxa.sort_values('abundance', ascending=False)\n"
            "result = plot_df"
        )
    })

    # run_graph must see plot_df in its namespace without recomputing
    graph_code = (
        _GENERIC_GRAPH_CONTRACT_CODE
        + "\nimport matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
        "assert 'plot_df' in dir() or plot_df is not None\n"
        "fig, ax = plt.subplots()\n"
        "ax.bar(plot_df['taxon'], plot_df['abundance'])\n"
        "ax.set_xlabel('taxon'); ax.set_ylabel('y')\n"
    )
    result = run_graph_tool.invoke({"code": graph_code})
    assert "error" not in result.lower() or "name 'plot_df'" not in result
    # The graph payload must remain addressable for a later edit, but it must
    # not replace the loaded source table as the next analysis target.
    active = store.get(tid)
    assert active["meta"]["variable_name"] == "df_file_taxa"
    assert list(active["df"].columns) == ["taxon", "abundance"]
    rendered = store.get(f"{tid}:dataset:df_graph_plot")
    assert rendered is not None
    assert list(rendered["df"].columns) == ["taxon", "abundance"]
    assert len(rendered["df"]) == 2


def test_run_graph_does_not_materialize_unreferenced_session_datasets(tmp_path):
    """A graph using one persisted table must not load every table in the session.

    In production a certified Net–UVP join can be several GB.  Reloading that
    join merely to render a graph based on a small derived table exhausts the
    worker before matplotlib runs.
    """
    from tools.dataset_registry import store_dataset

    class TrackingStore(SessionStore):
        def __init__(self, storage_dir):
            super().__init__(storage_dir)
            self.read_keys: list[str] = []

        def get(self, thread_id):
            self.read_keys.append(thread_id)
            return super().get(thread_id)

    store = TrackingStore(tmp_path / "sessions")
    tid = "thread-graph-minimal-load"
    small_key = f"{tid}:dataset:df_small_plot"
    large_key = f"{tid}:dataset:df_large_unreferenced"
    store_dataset(
        store,
        tid,
        pd.DataFrame({"x": [1, 2], "y": [3, 4]}),
        variable_name="df_small_plot",
        meta={"source": "analysis:small"},
    )
    store_dataset(
        store,
        tid,
        pd.DataFrame({"x": range(1000), "y": range(1000)}),
        variable_name="df_large_unreferenced",
        meta={"source": "analysis:large"},
        set_active=False,
    )
    store.update_meta(tid, {"loaded_skills": ["graph_writer"]})
    store.read_keys.clear()

    run_graph = next(t for t in make_tools(tid, store=store) if t.name == "run_graph")
    result = run_graph.invoke({"code": (
        _GENERIC_GRAPH_CONTRACT_CODE
        + "\nfig, ax = plt.subplots()\n"
        "ax.plot(df_small_plot['x'], df_small_plot['y'])\n"
    )})

    assert "![graph]" in result
    assert small_key in store.read_keys
    assert large_key not in store.read_keys
