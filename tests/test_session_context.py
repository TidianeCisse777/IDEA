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
