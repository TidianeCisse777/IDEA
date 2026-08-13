"""Regression tests for EcoTaxa's two-turn export confirmation."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from langchain_core.messages import HumanMessage, ToolMessage

from tools.session_store import SessionStore


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


def test_new_preflight_cannot_be_self_confirmed_in_the_same_user_turn(
    tmp_path,
    monkeypatch,
):
    """Reproduce the Baie d'Ungava two-sample fallback export regression."""
    import tools.copepod_sources as sources
    from tools.user_turn_scope import bind_user_turn

    thread_id = "ungava-export-confirmation"
    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr(sources, "_store", store)
    monkeypatch.setattr(
        sources,
        "resolve_sample_projects",
        lambda sample_ids: {int(sample_id): 42 for sample_id in sample_ids},
    )
    monkeypatch.setattr(
        sources,
        "summarize_samples",
        lambda sample_ids: [
            {
                "sample_id": int(sample_id),
                "projid": 42,
                "nb_validated": 1,
                "nb_predicted": 0,
                "nb_dubious": 0,
                "nb_unclassified": 0,
                "per_taxon": [],
            }
            for sample_id in sample_ids
        ],
    )
    # Before the fix, the same-turn confirmation reached this cached success
    # path and therefore performed the export without a later user message.
    monkeypatch.setattr(
        sources,
        "load_result",
        lambda *_args, **_kwargs: SimpleNamespace(
            dataframe=pd.DataFrame({"object_id": ["unexpected-export"]}),
            cached_at="2026-08-13T00:00:00Z",
            provenance={},
        ),
    )
    export = {
        tool.name: tool for tool in sources.make_source_tools(thread_id)
    }["export_ecotaxa_samples"]

    with bind_user_turn("human-turn-95"):
        preflight = _call(
            export,
            "preflight-two-samples",
            sample_ids=[18084000062, 18084000064],
            status="V",
            confirmed=False,
        )
        confirmation = _call(
            export,
            "confirm-two-samples",
            sample_ids=[18084000062, 18084000064],
            status="V",
            confirmed=True,
        )

    assert preflight.artifact["status"] == "blocked"
    assert confirmation.artifact["status"] == "blocked"
    assert confirmation.artifact["metrics"] == {
        "fresh_user_confirmation_required": True,
    }
    assert "nouveau message utilisateur" in str(confirmation.content)

    with bind_user_turn("human-turn-96"):
        later_confirmation = _call(
            export,
            "confirm-after-user-turn",
            sample_ids=[18084000062, 18084000064],
            status="V",
            confirmed=True,
        )

    assert later_confirmation.artifact["status"] == "success"
    assert later_confirmation.artifact["provenance"]["sample_ids"] == [
        18084000062,
        18084000064,
    ]


def test_changing_from_validated_to_all_objects_requires_a_new_two_turn_preflight(
    tmp_path,
    monkeypatch,
):
    """A user's scope change cannot inherit confirmation from the V-only plan."""
    import tools.copepod_sources as sources
    from tools.user_turn_scope import bind_user_turn

    thread_id = "ungava-all-objects-confirmation"
    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr(sources, "_store", store)
    monkeypatch.setattr(
        sources,
        "resolve_sample_projects",
        lambda sample_ids: {int(sample_id): 42 for sample_id in sample_ids},
    )
    monkeypatch.setattr(
        sources,
        "summarize_samples",
        lambda sample_ids: [
            {
                "sample_id": int(sample_id),
                "projid": 42,
                "nb_validated": 654,
                "nb_predicted": 27_310,
                "nb_dubious": 0,
                "nb_unclassified": 0,
                "per_taxon": [],
            }
            for sample_id in sample_ids
        ],
    )
    monkeypatch.setattr(
        sources,
        "load_result",
        lambda *_args, **_kwargs: SimpleNamespace(
            dataframe=pd.DataFrame({"object_id": ["all-objects"]}),
            cached_at="2026-08-13T00:00:00Z",
            provenance={},
        ),
    )
    export = {
        tool.name: tool for tool in sources.make_source_tools(thread_id)
    }["export_ecotaxa_samples"]

    with bind_user_turn("human-validated-request"):
        _call(
            export,
            "preflight-validated",
            sample_ids=[18084000064],
            status="V",
            confirmed=False,
        )

    with bind_user_turn("human-all-objects-request"):
        changed_scope = _call(
            export,
            "confirm-all-without-preflight",
            sample_ids=[18084000064],
            status="",
            confirmed=True,
        )
        _call(
            export,
            "preflight-all",
            sample_ids=[18084000064],
            status="",
            confirmed=False,
        )
        same_turn_confirmation = _call(
            export,
            "confirm-all-same-turn",
            sample_ids=[18084000064],
            status="",
            confirmed=True,
        )

    assert changed_scope.artifact["metrics"] == {"preflight_required": True}
    assert same_turn_confirmation.artifact["metrics"] == {
        "fresh_user_confirmation_required": True,
    }

    with bind_user_turn("human-confirm-all"):
        exact_confirmation = _call(
            export,
            "confirm-all-later",
            sample_ids=[18084000064],
            status="",
            confirmed=True,
        )

    assert exact_confirmation.artifact["status"] == "success"
    assert exact_confirmation.artifact["provenance"]["sample_ids"] == [18084000064]


def test_agent_middleware_binds_tools_to_latest_human_message():
    from agents.exploration_middleware import ExplorationStateMiddleware
    from tools.user_turn_scope import current_user_turn_marker

    middleware = ExplorationStateMiddleware(thread_id="turn-binding")
    request = SimpleNamespace(
        state={"messages": [HumanMessage(content="Confirme", id="human-confirm")]},
        tool_call={"id": "tool-call", "name": "dummy", "args": {}},
    )

    observed = middleware.wrap_tool_call(
        request,
        lambda _request: current_user_turn_marker(),
    )

    assert observed == "human-confirm"
