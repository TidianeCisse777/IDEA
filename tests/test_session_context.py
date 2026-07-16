import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tools.dataset_registry import store_dataset
from tools.session_store import SessionStore
from tools.session_context import (
    build_dataset_state_capsule,
    reject_ungrounded_ecotaxa_identifiers,
)


def test_capsule_names_active_local_dataset_without_stale_project(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "hawke-context"

    stale = pd.DataFrame({"sample_id": [42000002]})
    store_dataset(
        store,
        thread_id,
        stale,
        variable_name="df_ecotaxa_42",
        meta={"source": "ecotaxa:42", "project_id": 42, "n_rows": 1},
        latest_alias="ecotaxa",
    )
    hawke = pd.DataFrame({
        "sample_id": ["hc_01_030924", "hc_02_030924"],
        "object_date": ["2024-09-03", "2024-09-03"],
        "latitude": [-44.2, -44.3],
        "longitude": [172.7, 172.8],
    })
    store_dataset(
        store,
        thread_id,
        hawke,
        variable_name="df_file_ecotaxa_hawkechannel_30jan",
        meta={
            "source": "file:/data/ecotaxa_hawkechannel_30jan.tsv",
            "path": "/data/ecotaxa_hawkechannel_30jan.tsv",
            "n_rows": 137128,
            "n_cols": 201,
        },
        latest_alias="ecotaxa",
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "df_file_ecotaxa_hawkechannel_30jan" in capsule
    assert "137128" in capsule
    assert "sample_id" in capsule
    assert "project_id=42" not in capsule
    assert "42000002" not in capsule
    assert len(capsule) <= 2000


def test_capsule_is_deterministic_and_contains_no_row_values(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "deterministic-context"
    frame = pd.DataFrame({
        "sample_id": ["secret-row-value"],
        "object_date": ["2024-09-03"],
    })
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name="df_file_hawke",
        meta={"source": "file:/data/hawke.tsv", "n_rows": 1, "n_cols": 2},
        latest_alias="ecotaxa",
    )

    first = build_dataset_state_capsule(store, thread_id)
    second = build_dataset_state_capsule(store, thread_id)

    assert first == second
    assert "secret-row-value" not in first
    assert "ACTIVE DATASET STATE" in first


def test_capsule_surfaces_environment_columns_recognized_by_enrichment(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "ecotaxa-enrichment-context"
    frame = pd.DataFrame({
        "sample_id": ["17498000002"],
        "object_lat": [68.1],
        "object_lon": [-64.2],
        "object_date": ["2024-09-21"],
        "object_depth_min": [10.0],
    })
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name="df_ecotaxa_sample",
        meta={"source": "ecotaxa:17498", "n_rows": 1, "n_cols": 5},
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "object_lat" in capsule
    assert "object_lon" in capsule
    assert "object_date" in capsule
    assert "object_depth_min" in capsule
    assert "environment_columns=latitude:object_lat,longitude:object_lon" in capsule
    assert "direct station/cast identifiers are not required" in capsule


def test_old_turn_cannot_ground_remote_ecotaxa_sample_id(tmp_path):
    store = SessionStore(tmp_path)
    messages = [
        HumanMessage(content="Regarde le projet 42 et le sample 42000002"),
        AIMessage(content="D'accord."),
        HumanMessage(content="Donne le contexte de ces données locales"),
    ]

    rejection = reject_ungrounded_ecotaxa_identifiers(
        store,
        "contaminated-thread",
        messages,
        "summarize_ecotaxa_sample_deployment",
        {"sample_id": 42000002},
    )

    assert rejection is not None
    assert "identifiant EcoTaxa non fondé" in rejection
    assert "42000002" in rejection


def test_current_user_message_grounds_remote_ecotaxa_sample_id(tmp_path):
    store = SessionStore(tmp_path)
    messages = [HumanMessage(content="Résume le sample 42000002")]

    rejection = reject_ungrounded_ecotaxa_identifiers(
        store,
        "explicit-thread",
        messages,
        "summarize_ecotaxa_sample_deployment",
        {"sample_id": 42000002},
    )

    assert rejection is None


def test_current_turn_discovery_result_grounds_remote_project_id(tmp_path):
    store = SessionStore(tmp_path)
    messages = [
        HumanMessage(content="Trouve le projet Hawke Channel"),
        AIMessage(
            content="",
            tool_calls=[{"name": "find", "args": {}, "id": "call-1", "type": "tool_call"}],
        ),
        ToolMessage(content="Projet trouvé : project_id 1004", tool_call_id="call-1"),
    ]

    rejection = reject_ungrounded_ecotaxa_identifiers(
        store,
        "discovery-thread",
        messages,
        "summarize_ecotaxa_project",
        {"project_id": 1004},
    )

    assert rejection is None


def test_capsule_surfaces_loaded_file_when_active_is_derived_subset(tmp_path):
    """Régression cartes-samples-labrador-2026 : quand un sous-ensemble dérivé
    est le df actif, la capsule doit nommer le fichier chargé comme source
    canonique pour que le modèle y reparte au lieu du sous-ensemble."""
    from tools.dataset_registry import LOADED_FILE_KEY

    store = SessionStore(tmp_path)
    thread_id = "labrador-context"

    loaded = pd.DataFrame({
        "sample_id": ["s1", "s2"],
        "latitude": [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    store_dataset(
        store, thread_id, loaded,
        variable_name="df_file_neolabs_taxonomy",
        meta={"source": "file:/data/neolabs.tsv", "n_rows": 2, "n_cols": 3},
        latest_alias="df_file_neolabs_taxonomy",
        is_loaded_file=True,
    )
    # Un filtre Baffin devient le df actif (écrase le slot actif).
    subset = loaded.iloc[[0]]
    store_dataset(
        store, thread_id, subset,
        variable_name="df_in_baie_de_baffin_neolabs",
        meta={"source": "filter_by_zone:Baie de Baffin", "n_rows": 1},
        latest_alias="df_in_baie_de_baffin_neolabs",
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "variable=df_in_baie_de_baffin_neolabs" in capsule  # actif = dérivé
    assert "loaded_file=df_file_neolabs_taxonomy" in capsule    # ancre canonique
    assert "derived subset" in capsule
    assert len(capsule) <= 2000


def test_capsule_omits_loaded_file_note_when_active_is_the_file(tmp_path):
    """Pas d'ancre redondante quand le df actif EST le fichier chargé."""
    store = SessionStore(tmp_path)
    thread_id = "plain-file-context"

    loaded = pd.DataFrame({"sample_id": ["s1"], "latitude": [74.0], "longitude": [-68.0]})
    store_dataset(
        store, thread_id, loaded,
        variable_name="df_file_neolabs",
        meta={"source": "file:/data/neolabs.tsv", "n_rows": 1, "n_cols": 3},
        latest_alias="df_file_neolabs",
        is_loaded_file=True,
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "loaded_file=" not in capsule
    assert "CANONICAL SOURCE" not in capsule


def test_capsule_lists_live_zone_subsets_with_their_zone(tmp_path):
    """The capsule must name each live derived zone subset with its zone.

    Otherwise the agent re-infers from history which df_in_* variable maps to
    which zone and picks the wrong one (docs/e2e/cartes-samples-labrador-2026).
    """
    store = SessionStore(tmp_path)
    thread_id = "labrador-context"

    base = pd.DataFrame({
        "station": [1, 2, 3],
        "latitude": [60.0, 61.0, 62.0],
        "longitude": [-60.0, -61.0, -62.0],
    })
    store_dataset(
        store, thread_id, base,
        variable_name="df_file_stations",
        meta={"source": "file:/d/stations.tsv", "path": "/d/stations.tsv", "n_rows": 3, "n_cols": 3},
        is_loaded_file=True,
    )
    store_dataset(
        store, thread_id, base.iloc[:2],
        variable_name="df_in_labrador_sea_stations",
        meta={"source": "filter_by_zone:labrador-sea", "zone_canonical": "labrador-sea", "n_rows": 2},
        latest_alias="df_in_labrador_sea_stations",
    )
    store_dataset(
        store, thread_id, base.iloc[2:],
        variable_name="df_in_baffin_bay_stations",
        meta={"source": "filter_by_zone:baffin-bay", "zone_canonical": "baffin-bay", "n_rows": 1},
        latest_alias="df_in_baffin_bay_stations",
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "df_in_labrador_sea_stations" in capsule
    assert "labrador-sea" in capsule
    assert "df_in_baffin_bay_stations" in capsule
    assert "baffin-bay" in capsule


def test_capsule_derived_block_absent_without_zone_subsets(tmp_path):
    """No derived block noise when only a plain loaded file exists."""
    store = SessionStore(tmp_path)
    thread_id = "plain-context"
    loaded = pd.DataFrame({"sample_id": ["s1"], "latitude": [74.0], "longitude": [-68.0]})
    store_dataset(
        store, thread_id, loaded,
        variable_name="df_file_only",
        meta={"source": "file:/data/only.tsv", "n_rows": 1, "n_cols": 3},
        is_loaded_file=True,
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "DERIVED ZONE SUBSETS" not in capsule


def test_capsule_shows_active_source_scope_when_messages_given(tmp_path):
    """The capsule surfaces the authorized source scope as readable state."""
    store = SessionStore(tmp_path)
    thread_id = "scope-context"
    frame = pd.DataFrame({"station": [1], "latitude": [60.0], "longitude": [-60.0]})
    store_dataset(
        store, thread_id, frame,
        variable_name="df_file_scope",
        meta={"source": "file:/d/s.tsv", "n_rows": 1, "n_cols": 3},
        is_loaded_file=True,
    )
    from tools.source_scope import activate_file_source

    activate_file_source(store, thread_id, origin_user_text="/d/s.tsv")

    msgs = [{"role": "user", "content": "carte des stations"}]
    capsule = build_dataset_state_capsule(store, thread_id, msgs)

    assert "ACTIVE SOURCE SCOPE" in capsule
    assert "authorized=file" in capsule


def test_capsule_omits_source_scope_without_messages(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "noscope-context"
    frame = pd.DataFrame({"station": [1], "latitude": [60.0], "longitude": [-60.0]})
    store_dataset(
        store, thread_id, frame,
        variable_name="df_file_noscope",
        meta={"source": "file:/d/s.tsv", "n_rows": 1, "n_cols": 3},
        is_loaded_file=True,
    )
    capsule = build_dataset_state_capsule(store, thread_id)
    assert "ACTIVE SOURCE SCOPE" not in capsule


def test_capsule_lists_all_loaded_files_by_name(tmp_path):
    """A multi-file session must name every loaded file so the agent targets the
    right df without reloading."""
    store = SessionStore(tmp_path)
    thread_id = "multifile-context"
    store_dataset(
        store, thread_id, pd.DataFrame({"station": ["S1"], "latitude": [60.0]}),
        variable_name="df_file_stations_a",
        meta={"source": "file:/d/stations_a.csv", "path": "/d/stations_a.csv", "n_rows": 3, "n_cols": 2},
        is_loaded_file=True,
    )
    store_dataset(
        store, thread_id, pd.DataFrame({"station": ["S1"], "temperature": [3.1]}),
        variable_name="df_file_temperatures_b",
        meta={"source": "file:/d/temperatures_b.csv", "path": "/d/temperatures_b.csv", "n_rows": 3, "n_cols": 2},
        is_loaded_file=True,
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "LOADED FILES" in capsule
    assert "df_file_stations_a" in capsule
    assert "df_file_temperatures_b" in capsule


def test_capsule_identifies_persisted_join_as_active_file(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "thread-active-join-capsule"
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({"sample_id": ["S1"], "latitude": [60.0]}),
        variable_name="df_join_abundance_sample",
        meta={"source": "analysis:join", "n_rows": 1, "n_cols": 2},
        latest_alias="df_join_abundance_sample",
    )

    capsule = build_dataset_state_capsule(store, thread_id)

    assert "ACTIVE PERSISTED JOIN" in capsule
    assert "df_join_abundance_sample" in capsule


def test_capsule_no_loaded_files_block_for_single_file(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "single-file-context"
    store_dataset(
        store, thread_id, pd.DataFrame({"station": ["S1"]}),
        variable_name="df_file_solo",
        meta={"source": "file:/d/solo.csv", "path": "/d/solo.csv", "n_rows": 1, "n_cols": 1},
        is_loaded_file=True,
    )
    capsule = build_dataset_state_capsule(store, thread_id)
    assert "LOADED FILES" not in capsule
