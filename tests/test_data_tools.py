"""Tests TDD — tools/data_tools.py (slice 2)"""
import io
import base64
import sys
from pathlib import Path

import pandas as pd
import pytest

from tools.data_tools import make_tools, _patch_cartopy_gridliner_polygon, _uvp_skill_hint
from tools.session_store import SessionStore, default_store as _store


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


def test_run_graph_works_without_loaded_file_for_standalone_map():
    """Carte d'une zone nommée : pas de df nécessaire, run_graph doit exécuter."""
    thread_id = "thread-standalone-graph"
    _store.clear(thread_id)

    run_graph = next(t for t in make_tools(thread_id) if t.name == "run_graph")
    code = (
        "fig, ax = plt.subplots(figsize=(4, 4))\n"
        "ax.text(0.5, 0.5, 'Mer du Labrador', ha='center', va='center')\n"
        "ax.set_xlim(0, 1); ax.set_ylim(0, 1)\n"
    )
    result = run_graph.invoke({"code": code})
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
        "code": "fig, ax = plt.subplots(); ax.plot(df['x'], df['y'])",
    })

    assert "load_skill(\"graph_writer\")" in result
    assert "before run_graph" in result
    assert "/graphs/" not in result


def test_run_graph_blocks_unreadable_oversized_figures(tmp_path):
    thread_id = "thread-oversized-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    result = run_graph.invoke({
        "code": "fig, ax = plt.subplots(figsize=(10, 22)); ax.plot(df['x'], df['y'])",
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
    result = run_graph.invoke({"code": code})

    assert "Graph quality blocked" in result
    assert "legend entries" in result
    assert "/graphs/" not in result


def test_run_graph_blocks_too_many_visible_tick_labels(tmp_path):
    thread_id = "thread-tick-label-graph"
    store = SessionStore(tmp_path / "sessions")
    df = pd.DataFrame({"x": list(range(80)), "y": list(range(80))})
    store.set(thread_id, df, {"loaded_skills": ["graph_writer"]})

    run_graph = next(t for t in make_tools(thread_id, store=store) if t.name == "run_graph")
    code = """
fig, ax = plt.subplots(figsize=(10, 8))
ax.imshow([[0, 1], [1, 0]])
ax.set_yticks(range(80))
ax.set_yticklabels([f"station-{i}" for i in range(80)])
"""
    result = run_graph.invoke({"code": code})

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
ax.set_xticks(range(12))
ax.set_xticklabels([
    "Animalia | Arthropoda | Copepoda | Calanoida | Calanidae | Calanus hyperboreus"
    for _ in range(12)
], rotation=45)
"""
    result = run_graph.invoke({"code": code})

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
