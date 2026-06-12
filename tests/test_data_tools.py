"""Tests TDD — tools/data_tools.py (slice 2)"""
import io
import base64
from pathlib import Path

import pandas as pd
import pytest

from tools.data_tools import make_tools, _uvp_skill_hint
from tools.session_store import default_store as _store


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
def clear_sessions():
    _store._store.clear()
    yield
    _store._store.clear()


# --- Comportement 1 : load_file_tool ---

def test_load_file_tool_stores_df(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert _store.has("thread-1")
    assert _store.get("thread-1")["df"] is not None
    assert _store.get("thread-1")["df"].shape == (3, 3)


def test_load_file_tool_returns_summary(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert "3" in result  # n_rows
    assert "profile_id" in result


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


# --- Comportement 5 : run_graph ajoute une lecture rapide ---

def test_run_graph_includes_quick_reading(tmp_path):
    tools = make_tools("thread-graph")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_graph = next(t for t in tools if t.name == "run_graph")

    df = pd.DataFrame({
        "depth": [10, 20, 30],
        "temperature": [2.1, 1.8, 1.2],
    })
    p = tmp_path / "graph.tsv"
    df.to_csv(p, sep="\t", index=False)
    load_file_tool.invoke({"path": str(p)})

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

    result = run_graph.invoke({"code": code})
    assert "/graphs/" in result
    assert "Lecture rapide" in result
    assert "courbe en ligne" in result


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

    run_graph = next(t for t in make_tools(thread_id) if t.name == "run_graph")
    result = run_graph.invoke({
        "code": (
            "fig, ax = plt.subplots()\n"
            "ax.bar(['105', '42'], [len(df_ecopart_105), len(df_ecopart_42)])"
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
