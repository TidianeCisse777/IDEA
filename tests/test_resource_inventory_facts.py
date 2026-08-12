"""Factual resource inventory contracts."""

from __future__ import annotations

import pandas as pd

from agents.exploration_state import new_exploration_run, render_dataframe_context
from tools.data_tools import make_tools
from tools.resource_inventory import build_resource_inventory
from tools.session_store import SessionStore


def test_dataframe_values_override_declared_scope(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    thread_id = "observed-scope"
    frame = pd.DataFrame(
        {
            "project_id": [17808, 17808, 18084],
            "sample_profileid": ["P-01", "P-02", "P-03"],
            "sample_id": [101, 102, 103],
            "station": ["M1b", "M2b", "M3a"],
            "sample_datetime": [
                "2025-06-29T12:00:00Z",
                "2025-07-01T13:30:00Z",
                "2025-07-08T09:00:00Z",
            ],
        }
    )
    store.set(
        f"{thread_id}:dataset:df_export",
        frame,
        {
            "variable_name": "df_export",
            "source": "analysis:derived",
            "project_ids": [99999],
            "profile_ids": ["WRONG-PROFILE"],
        },
    )

    record = next(
        item
        for item in build_resource_inventory(store, thread_id)
        if item.name == "df_export"
    )

    assert record.scope["scope_basis"] == "dataframe_values"
    assert record.scope["project_ids"] == [17808, 18084]
    assert record.scope["profile_ids"] == ["P-01", "P-02", "P-03"]
    assert record.scope["sample_ids"] == [101, 102, 103]
    assert record.scope["stations"] == ["M1b", "M2b", "M3a"]
    assert record.scope["date_from"] == "2025-06-29T12:00:00+00:00"
    assert record.scope["date_to"] == "2025-07-08T09:00:00+00:00"
    assert record.scope["declared_conflicts"]["project_ids"] == [99999]
    assert record.scope["declared_conflicts"]["profile_ids"] == ["WRONG-PROFILE"]


def test_run_pandas_claims_do_not_become_resource_facts(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    thread_id = "claimed-metadata"
    tools = {tool.name: tool for tool in make_tools(thread_id, store=store)}
    path = tmp_path / "export.csv"
    pd.DataFrame(
        {
            "project_id": [17808, 17808],
            "sample_profileid": ["P-01", "P-02"],
            "value": [1, 2],
        }
    ).to_csv(path, index=False)
    tools["load_file"].invoke({"path": str(path)})

    _, artifact = tools["run_pandas"].invoke(
        {
            "code": "result = df_file_export.copy()",
            "persist_as": "df_claimed_uvp_match",
            "description": "Correspondance UVP certifiée pour le projet 99999",
            "grain": "une ligne par profil UVP certifié",
            "filters": {"project_id": 99999},
        }
    )

    assert artifact["status"] == "success"
    entry = store.get(f"{thread_id}:dataset:df_claimed_uvp_match")
    assert entry is not None
    meta = entry["meta"]
    assert meta["description"] == "Table explicitement persistée : df_claimed_uvp_match"
    assert meta["llm_claims"] == {
        "description": "Correspondance UVP certifiée pour le projet 99999",
        "grain": "une ligne par profil UVP certifié",
        "filters": {"project_id": 99999},
    }
    assert "grain" not in meta
    assert "filters" not in meta

    record = next(
        item
        for item in build_resource_inventory(store, thread_id)
        if item.name == "df_claimed_uvp_match"
    )
    assert record.description == "Table explicitement persistée : df_claimed_uvp_match"
    assert record.grain != "une ligne par profil UVP certifié"
    assert record.scope["project_ids"] == [17808]
    assert "declared_conflicts" not in record.scope


def test_dataframe_card_names_source_parents_and_present_identifiers(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    thread_id = "clear-dataframe-card"
    store.set(
        f"{thread_id}:dataset:df_uvp_net_pairs",
        pd.DataFrame(
            {
                "project_id": [17808],
                "profile_id": ["P-01"],
                "net_sample_id": [101],
                "station": ["M1b"],
                "time_delta_h": [2.5],
            }
        ),
        {
            "variable_name": "df_uvp_net_pairs",
            "source": "analysis:join",
            "parent_variables": ["df_neolabs_sample", "df_ecotaxa_export"],
        },
    )
    resources = build_resource_inventory(store, thread_id)
    run = new_exploration_run("Inspecte les correspondances.", resources)

    context = render_dataframe_context(
        run,
        active_variable="df_uvp_net_pairs",
    )

    assert "source=analysis:join" in context
    assert "parents=df_neolabs_sample,df_ecotaxa_export" in context
    assert "identifiers_present=project_id,profile_id,net_sample_id,station" in context
