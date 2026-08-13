"""Cross-tool confirmation routing regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from langchain_core.messages import ToolMessage

from tools.session_store import SessionStore
from tools.user_turn_scope import bind_user_turn


def _call(tool, call_id: str, **arguments) -> ToolMessage:  # noqa: ANN001
    message = tool.invoke(
        {
            "type": "tool_call",
            "id": call_id,
            "name": tool.name,
            "args": arguments,
        }
    )
    assert isinstance(message, ToolMessage)
    return message


def test_ecopart_preflight_supersedes_an_older_ecotaxa_confirmation(
    tmp_path,
    monkeypatch,
):
    """After EcoPart 18084→1063, ``je confirme`` cannot run EcoTaxa again."""
    from tools import copepod_sources, ecopart_sources

    class FakeEcopartClient:
        def login(self):
            return None

        def search_samples(self, **kwargs):
            assert kwargs["project_id"] == 1063
            return [
                {
                    "name": "20241022-155403",
                    "visibility": "PUBLIC Y",
                }
            ]

    thread_id = "ungava-cross-tool-confirmation"
    store = SessionStore(tmp_path / "sessions")
    ecotaxa = pd.DataFrame(
        {
            "object_id": ["obj-1"],
            "sample_id": [18084000064],
            "sample_profileid": ["20241022-155403"],
            "object_depth_min": [5.0],
        }
    )
    ecotaxa_meta = {
        "source": "ecotaxa_export_campaign",
        "project_id": 18084,
        "variable_name": "df_ecotaxa_18084",
    }
    store.set(thread_id, ecotaxa, ecotaxa_meta)
    store.set(f"{thread_id}:ecotaxa", ecotaxa, ecotaxa_meta)
    monkeypatch.setattr(copepod_sources, "_store", store)
    monkeypatch.setattr(ecopart_sources, "_store", store)
    monkeypatch.setattr(
        copepod_sources,
        "resolve_sample_projects",
        lambda sample_ids: {int(sample_id): 18084 for sample_id in sample_ids},
    )
    monkeypatch.setattr(
        copepod_sources,
        "summarize_samples",
        lambda _sample_ids: [
            {
                "sample_id": 18084000064,
                "projid": 18084,
                "nb_validated": 654,
                "nb_predicted": 27_310,
                "nb_dubious": 0,
                "nb_unclassified": 0,
                "per_taxon": [],
            }
        ],
    )
    monkeypatch.setattr(
        copepod_sources,
        "load_result",
        lambda *_args, **_kwargs: SimpleNamespace(
            dataframe=pd.DataFrame({"object_id": ["wrong-second-export"]}),
            cached_at="2026-08-13T00:00:00Z",
            provenance={},
        ),
    )
    monkeypatch.setattr(ecopart_sources, "EcopartClient", FakeEcopartClient)
    monkeypatch.setattr(
        ecopart_sources,
        "load_result",
        lambda *_args, **_kwargs: SimpleNamespace(
            dataframe=pd.DataFrame({"object_id": ["joined-object"]}),
            cached_at="2026-08-13T00:00:00Z",
            provenance={"ecotaxa_project_id": 18084, "ecopart_project_id": 1063},
        ),
    )
    monkeypatch.setattr(
        ecopart_sources,
        "bootstrap_consumer_cache",
        lambda *_args, **_kwargs: None,
    )

    export_ecotaxa = {
        tool.name: tool for tool in copepod_sources.make_source_tools(thread_id)
    }["export_ecotaxa_samples"]
    enrich_ecopart = {
        tool.name: tool for tool in ecopart_sources.make_ecopart_tools(thread_id)
    }["enrich_ecotaxa_with_ecopart_remote"]

    with bind_user_turn("human-ecotaxa-preflight"):
        _call(
            export_ecotaxa,
            "ecotaxa-preflight",
            sample_ids=[18084000064],
            status="",
            confirmed=False,
        )
    with bind_user_turn("human-ecopart-request"):
        ecopart_preflight = _call(
            enrich_ecopart,
            "ecopart-preflight",
            ecotaxa_project_id=18084,
            ecopart_project_id=1063,
            confirmed=False,
        )
        same_turn_ecopart = _call(
            enrich_ecopart,
            "ecopart-confirmed-too-early",
            ecotaxa_project_id=18084,
            ecopart_project_id=1063,
            confirmed=True,
        )
    with bind_user_turn("human-confirm-ecopart"):
        wrong_tool = _call(
            export_ecotaxa,
            "wrong-ecotaxa-confirmation",
            sample_ids=[18084000064],
            status="",
            confirmed=True,
        )
        correct_tool = _call(
            enrich_ecopart,
            "correct-ecopart-confirmation",
            ecotaxa_project_id=18084,
            ecopart_project_id=1063,
            confirmed=True,
        )

    assert ecopart_preflight.artifact["status"] == "blocked"
    assert "EcoTaxa 18084 → EcoPart 1063" in str(ecopart_preflight.content)
    assert (
        "Profils EcoPart reconnus exactement (1) : 20241022-155403."
        in str(ecopart_preflight.content)
    )
    assert same_turn_ecopart.artifact["status"] == "blocked"
    assert same_turn_ecopart.artifact["metrics"] == {
        "fresh_user_confirmation_required": True,
    }
    assert wrong_tool.artifact["status"] == "blocked"
    assert wrong_tool.artifact["metrics"] == {
        "confirmation_operation_mismatch": True,
    }
    assert correct_tool.artifact["status"] == "success"
    assert correct_tool.artifact["provenance"]["ecopart_project_id"] == 1063
