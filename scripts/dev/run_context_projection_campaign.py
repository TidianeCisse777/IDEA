#!/usr/bin/env python3
"""Run deterministic campaigns against IDEA's model-bound context projection.

The campaign uses the production middleware with a local spy model. It never
calls an LLM, a source API, LangSmith, or the network. It validates only what
the application places in the model request: task, DataFrames, exploration
frontier, last-graph facts, and useful history.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterable, Sequence
from unittest.mock import patch

import pandas as pd

# This harness is deliberately offline. Set both current and legacy tracing
# switches before importing LangChain or the production agent module so no
# background LangSmith client is initialised from the developer's .env file.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dev.inspect_six_dataframe_context import (  # noqa: E402
    DATAFRAME_NAMES,
    MANY_DATAFRAME_COUNT,
    ModelCapture,
    build_frontier_payload,
    capture_model_request,
    resolve_frontier_payload,
    seed_many_dataframes,
    seed_six_dataframes,
)
from tools.dataset_registry import store_dataset  # noqa: E402
from tools.session_store import SessionStore  # noqa: E402
import agent as agent_module  # noqa: E402
from agents.exploration_middleware import ExplorationStateMiddleware  # noqa: E402
from agents.exploration_state import IdeaAgentState  # noqa: E402
from scripts.dev.inspect_six_dataframe_context import (  # noqa: E402
    _SpyChatModel,
    _capture_from_model_call,
)
from tools.tool_catalog import build_tool_catalog  # noqa: E402


FACETS = (
    "current_task", "dataframes", "frontier", "graph", "history",
    "long_turns", "thread_isolation",
)
BASE_THREAD = "context-projection-campaign"
CURRENT_QUESTION = (
    "Donne, pour chaque station, le nombre de profils UVP associés à un "
    "prélèvement et le delta temporel moyen."
)


@dataclass(frozen=True)
class CampaignCheck:
    """One deterministic assertion over the exact model-bound request."""

    scenario: str
    facet: str
    name: str
    passed: bool
    evidence: str


def _check(
    scenario: str,
    facet: str,
    name: str,
    condition: bool,
    evidence: str,
) -> CampaignCheck:
    return CampaignCheck(
        scenario=scenario,
        facet=facet,
        name=name,
        passed=bool(condition),
        evidence=evidence,
    )


def _content_text(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        str(block.get("text") or "")
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _index_names(context: str) -> tuple[str, ...]:
    return tuple(re.findall(r"^\* (df_[A-Za-z0-9_]+) \|", context, re.MULTILINE))


def _detail_names(context: str) -> tuple[str, ...]:
    return tuple(re.findall(r"^- (df_[A-Za-z0-9_]+)$", context, re.MULTILINE))


def _human_messages(capture: ModelCapture) -> list[BaseMessage]:
    return [message for message in capture.messages if message.type == "human"]


def _forbidden_external_call(*args, **kwargs):
    raise AssertionError(
        "Context projection campaign attempted an external model or network call"
    )


@contextmanager
def offline_only():
    """Fail immediately if campaign code attempts an LLM or socket connection."""

    with ExitStack() as stack:
        stack.enter_context(
            patch("langchain_openai.ChatOpenAI.invoke", _forbidden_external_call)
        )
        stack.enter_context(
            patch("langchain_openai.ChatOpenAI.ainvoke", _forbidden_external_call)
        )
        stack.enter_context(patch("socket.create_connection", _forbidden_external_call))
        stack.enter_context(
            patch.object(socket.socket, "connect", _forbidden_external_call)
        )
        yield


def _seed_one_dataframe(store: SessionStore, thread_id: str) -> None:
    frame = pd.DataFrame(
        {
            "sample_id": ["SAMPLE_ROW_VALUE_MUST_NOT_APPEAR"],
            "station": ["STATION_ROW_VALUE_MUST_NOT_APPEAR"],
            "value": [7.5],
        }
    )
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name="df_single_sample",
        meta={
            "source": "file:/uploads/single_sample.csv",
            "description": "Single sample table with station and measured value.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
    )


def _capture(
    store: SessionStore,
    thread_id: str,
    question: str,
    message_id: str,
    *,
    exploration: dict | None = None,
    input_messages: Sequence[BaseMessage] | None = None,
) -> ModelCapture:
    return capture_model_request(
        store,
        thread_id,
        question,
        message_id,
        exploration=exploration,
        input_messages=input_messages,
    )


@dataclass(frozen=True)
class TurnSnapshot:
    thread_id: str
    turn: int
    question: str
    capture: ModelCapture
    checkpoint_messages: tuple[BaseMessage, ...]


TurnMutation = Callable[
    [int, SessionStore, Any, dict[str, Any]],
    None,
]


class CheckpointedProjectionSession:
    def __init__(
        self,
        store: SessionStore,
        thread_id: str,
        *,
        response_count: int,
        answer_chars: int = 0,
    ) -> None:
        self.store = store
        self.thread_id = thread_id
        self.turn = 0
        suffix = "R" * max(0, answer_chars)
        responses = [
            AIMessage(content=f"Offline response {index:03d}. {suffix}")
            for index in range(1, response_count + 1)
        ]
        self.spy = _SpyChatModel(responses=responses)
        with patch("tools.session_store.default_store", store):
            catalog = build_tool_catalog(thread_id)
            self.graph = create_agent(
                self.spy,
                list(catalog.tools),
                system_prompt=agent_module._SYSTEM_PROMPT,
                middleware=[
                    ModelCallLimitMiddleware(
                        run_limit=agent_module._MAX_MODEL_CALLS_PER_TURN,
                        exit_behavior="end",
                    ),
                    ExplorationStateMiddleware(thread_id=thread_id),
                    agent_module._ContextMiddleware(
                        user_id="context-campaign",
                        thread_id=thread_id,
                        catalog_names=catalog.names,
                    ),
                ],
                state_schema=IdeaAgentState,
                checkpointer=MemorySaver(),
                store=InMemoryStore(),
            )
        self.config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id}
        }

    def invoke(
        self,
        question: str,
        *,
        mutate_before: TurnMutation | None = None,
    ) -> TurnSnapshot:
        self.turn += 1
        self.spy.current_turn = self.turn
        if mutate_before is not None:
            mutate_before(
                self.turn,
                self.store,
                self.graph,
                self.config,
            )
        calls_before = len(self.spy.calls)
        message = HumanMessage(
            content=question,
            id=f"{self.thread_id}-human-{self.turn:03d}",
        )
        with patch("tools.session_store.default_store", self.store):
            result = self.graph.invoke(
                {"messages": [message]},
                config=self.config,
            )
        new_calls = self.spy.calls[calls_before:]
        if len(new_calls) != 1:
            raise AssertionError(
                f"Expected one model call on turn {self.turn}, got {len(new_calls)}"
            )
        checkpoint_messages = tuple(result.get("messages") or ())
        capture = replace(
            _capture_from_model_call(new_calls[0]),
            audit=agent_module.get_context_audit(self.thread_id),
            state_messages=checkpoint_messages,
            turn=self.turn,
        )
        return TurnSnapshot(
            thread_id=self.thread_id,
            turn=self.turn,
            question=question,
            capture=capture,
            checkpoint_messages=checkpoint_messages,
        )


def run_checkpointed_projection(
    store: SessionStore,
    thread_id: str,
    questions: Sequence[str],
    *,
    answer_chars: int = 0,
    mutate_before_turn: TurnMutation | None = None,
) -> list[TurnSnapshot]:
    session = CheckpointedProjectionSession(
        store,
        thread_id,
        response_count=len(questions),
        answer_chars=answer_chars,
    )
    return [
        session.invoke(question, mutate_before=mutate_before_turn)
        for question in questions
    ]


def campaign_current_task(store: SessionStore) -> list[CampaignCheck]:
    scenario = "current-task-two-turn-history"
    thread_id = f"{BASE_THREAD}-task"
    seed_six_dataframes(store, thread_id)
    first_question = "Inspecte les profils UVP disponibles."
    second_question = CURRENT_QUESTION
    history: list[BaseMessage] = [
        HumanMessage(content=first_question, id="task-history-human-1"),
        AIMessage(content="Inspection terminée.", id="task-history-ai-1"),
        HumanMessage(content=second_question, id="task-history-human-2"),
    ]
    capture = _capture(
        store,
        thread_id,
        second_question,
        "task-current",
        input_messages=history,
    )
    context = capture.runtime_context
    task = capture.task_context
    humans = _human_messages(capture)
    return [
        _check(
            scenario,
            "current_task",
            "latest objective is authoritative",
            f"Objective: {second_question}" in task
            and f"Objective: {first_question}" not in task,
            task[:500],
        ),
        _check(
            scenario,
            "current_task",
            "deliverable and selection contract are projected",
            "Required deliverables: answer" in task
            and "DATA SELECTION CONTRACT:" in task
            and "active status and recency are metadata only" in task,
            task[:700],
        ),
        _check(
            scenario,
            "current_task",
            "source route is a non-blocking hint",
            "Preferred source route:" in task
            and "never a DataFrame or tool restriction" in task,
            task[-350:],
        ),
        _check(
            scenario,
            "current_task",
            "task precedes dataframe catalog",
            context.find("## CURRENT TASK")
            < context.find("## AVAILABLE DATAFRAMES"),
            "CURRENT TASK -> AVAILABLE DATAFRAMES",
        ),
        _check(
            scenario,
            "current_task",
            "previous user turn remains useful history",
            len(humans) == 2 and first_question in _content_text(humans[0]),
            f"human_messages={len(humans)}",
        ),
        _check(
            scenario,
            "current_task",
            "current user request remains exact",
            capture.exact_user_request == second_question,
            f"exact_user_request={capture.exact_user_request}",
        ),
    ]


def campaign_dataframes(store: SessionStore) -> list[CampaignCheck]:
    checks: list[CampaignCheck] = []

    one_thread = f"{BASE_THREAD}-df-one"
    _seed_one_dataframe(store, one_thread)
    one = _capture(
        store,
        one_thread,
        "Résume la table de prélèvements.",
        "df-one",
    )
    checks.extend([
        _check(
            "one-dataframe",
            "dataframes",
            "single live dataframe indexed and expanded",
            _index_names(one.dataset_context) == ("df_single_sample",)
            and _detail_names(one.dataset_context) == ("df_single_sample",),
            f"index={_index_names(one.dataset_context)}; "
            f"details={_detail_names(one.dataset_context)}",
        ),
        _check(
            "one-dataframe",
            "dataframes",
            "description grain schema and key are visible",
            "description=Single sample table" in one.dataset_context
            and "grain=one row per sample" in one.dataset_context
            and "schema_by_role=" in one.dataset_context
            and "keys=sample_id" in one.dataset_context,
            one.dataset_context[:900],
        ),
        _check(
            "one-dataframe",
            "dataframes",
            "raw row values are excluded",
            "SAMPLE_ROW_VALUE_MUST_NOT_APPEAR" not in one.dataset_context
            and "STATION_ROW_VALUE_MUST_NOT_APPEAR" not in one.dataset_context,
            "fixture row sentinels absent",
        ),
    ])

    six_thread = f"{BASE_THREAD}-df-six"
    seed_six_dataframes(store, six_thread)
    six = _capture(store, six_thread, CURRENT_QUESTION, "df-six")
    index = _index_names(six.dataset_context)
    details = _detail_names(six.dataset_context)
    checks.extend([
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "all live dataframe names remain visible",
            set(index) == set(DATAFRAME_NAMES) and len(index) == len(DATAFRAME_NAMES),
            f"index={index}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "index is alphabetical rather than active-first",
            index == tuple(sorted(DATAFRAME_NAMES)),
            f"index={index}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "active status does not hide alternatives",
            "df_uvp_net_candidates | status=active" in six.dataset_context
            and "df_station_summary | status=available" in six.dataset_context
            and set(details) == set(DATAFRAME_NAMES),
            f"expanded={details}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "request-relevant station summary is expanded first",
            bool(details) and details[0] == "df_station_summary",
            f"first_detail={details[0] if details else 'none'}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "wide schema keeps useful roles and declares truncation",
            "schema_visibility=10/78 (partial" in six.dataset_context
            and "DEPLOYMENT_DATE_START:object" in six.dataset_context
            and "DEPLOYMENT_TIME_START:object" in six.dataset_context
            and "volume_m3:float64" in six.dataset_context,
            "wide sample card exposes time and measure columns",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "scope and lineage are projected",
            'scope={"filter.same_station":true,"filter.delta_h_max":10}'
            in six.dataset_context
            and "parent_variables:df_neolabs_sample" in six.dataset_context
            and "parent_variables:df_ecotaxa_cache_query" in six.dataset_context,
            "join filters and both parents visible",
        ),
    ])

    explicit = _capture(
        store,
        six_thread,
        "Utilise df_old_plot et décris ses colonnes.",
        "df-explicit",
    )
    explicit_details = _detail_names(explicit.dataset_context)
    checks.append(
        _check(
            "explicit-dataframe-reference",
            "dataframes",
            "explicit dataframe receives first detailed card",
            bool(explicit_details) and explicit_details[0] == "df_old_plot",
            f"first_detail={explicit_details[0] if explicit_details else 'none'}",
        )
    )

    many_thread = f"{BASE_THREAD}-df-many"
    many_names = seed_many_dataframes(store, many_thread)
    target = many_names[-1]
    many = _capture(
        store,
        many_thread,
        f"Analyse précisément {target}.",
        "df-many",
    )
    many_index = _index_names(many.dataset_context)
    many_details = _detail_names(many.dataset_context)
    checks.extend([
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "complete index survives bounded expansion",
            set(many_index) == set(many_names)
            and len(many_index) == MANY_DATAFRAME_COUNT,
            f"indexed={len(many_index)}",
        ),
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "detailed cards are bounded",
            1 <= len(many_details) <= 8,
            f"expanded={len(many_details)}",
        ),
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "explicit target remains expanded",
            bool(many_details) and many_details[0] == target,
            f"target={target}; first_detail={many_details[0] if many_details else 'none'}",
        ),
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "catalog remains within configured budget",
            len(many.dataset_context) <= 12_000,
            f"characters={len(many.dataset_context)}",
        ),
    ])
    return checks


def campaign_frontier(store: SessionStore) -> list[CampaignCheck]:
    thread_id = f"{BASE_THREAD}-frontier"
    seed_six_dataframes(store, thread_id)
    objective = "Calcule le nombre d’objets par profil EcoTaxa."
    pending_payload, messages = build_frontier_payload(store, thread_id, objective)
    pending = _capture(
        store,
        thread_id,
        objective,
        "frontier-pending",
        exploration=pending_payload,
    )
    resolved_payload = resolve_frontier_payload(pending_payload, messages)
    resolved = _capture(
        store,
        thread_id,
        objective,
        "frontier-resolved",
        exploration=resolved_payload,
    )
    clean_thread = f"{BASE_THREAD}-frontier-clean"
    seed_six_dataframes(store, clean_thread)
    clean = _capture(store, clean_thread, "Liste les tables disponibles.", "frontier-clean")
    return [
        _check(
            "pending-frontier",
            "frontier",
            "pending step and dependency are visible",
            "object_count" in pending.exploration_context
            and "Resolve every pending data dependency" in pending.exploration_context,
            pending.exploration_context[:900],
        ),
        _check(
            "pending-frontier",
            "frontier",
            "failure evidence is visible and bounded",
            "Evidence collected:" in pending.exploration_context
            and len(pending.exploration_context) <= 4_500,
            f"characters={len(pending.exploration_context)}",
        ),
        _check(
            "resolved-frontier",
            "frontier",
            "resolved dependency leaves active work",
            "Resolve every pending data dependency" not in resolved.exploration_context
            and 'Data dependencies: []' in resolved.exploration_context
            and "df_object_count_by_profile" in resolved.exploration_context,
            resolved.exploration_context[:900],
        ),
        _check(
            "clean-frontier",
            "frontier",
            "empty frontier has no invented dependency",
            "Data dependencies: []" in clean.exploration_context
            and "Resolve every pending data dependency" not in clean.exploration_context,
            clean.exploration_context,
        ),
        _check(
            "pending-frontier",
            "frontier",
            "frontier follows dataframe catalog",
            pending.runtime_context.find("## AVAILABLE DATAFRAMES")
            < pending.runtime_context.find("## EXPLORATION FRONTIER"),
            "AVAILABLE DATAFRAMES -> EXPLORATION FRONTIER",
        ),
    ]


def campaign_graph(store: SessionStore) -> list[CampaignCheck]:
    thread_id = f"{BASE_THREAD}-graph"
    seed_six_dataframes(store, thread_id)
    facts = (
        "lignes tracées=42 · colonnes utilisées=station,delta_h · "
        "table de rendu=df_graph_plot · encodages=x=station;y=delta_h"
    )
    code_sentinel = "SECRET_GRAPH_CODE_MUST_NOT_BE_PROJECTED"
    without_graph = _capture(
        store,
        thread_id,
        "Prépare une analyse des profils.",
        "graph-absent",
    )
    store.set(f"{thread_id}:last_graph_grounding", None, {"facts": facts})
    store.set(
        f"{thread_id}:last_graph_state",
        None,
        {"code": code_sentinel, "graph_id": "projection-campaign-graph"},
    )
    producing_turn = _capture(
        store,
        thread_id,
        "Résume le dernier graphique.",
        "graph-present",
    )
    following_turn = _capture(
        store,
        thread_id,
        "Quels faits du graphique sont encore disponibles ?",
        "graph-following",
    )
    checkpoint_text = "\n".join(
        _content_text(message) for message in producing_turn.state_messages
    )
    return [
        _check(
            "no-last-graph",
            "graph",
            "graph block is absent without graph state",
            not without_graph.graph_facts_context,
            "LAST GRAPH absent",
        ),
        _check(
            "last-graph-present",
            "graph",
            "verified facts are projected",
            "LAST GRAPH" in producing_turn.graph_facts_context
            and facts in producing_turn.graph_facts_context,
            producing_turn.graph_facts_context,
        ),
        _check(
            "last-graph-present",
            "graph",
            "graph code is not projected",
            code_sentinel not in producing_turn.runtime_context,
            "graph code sentinel absent",
        ),
        _check(
            "last-graph-present",
            "graph",
            "graph facts are transient",
            facts not in producing_turn.system and facts not in checkpoint_text,
            "facts absent from permanent system and checkpointed messages",
        ),
        _check(
            "last-graph-present",
            "graph",
            "graph block is ordered between dataframes and frontier",
            producing_turn.runtime_context.find("## AVAILABLE DATAFRAMES")
            < producing_turn.runtime_context.find("LAST GRAPH")
            < producing_turn.runtime_context.find("## EXPLORATION FRONTIER"),
            "AVAILABLE DATAFRAMES -> LAST GRAPH -> EXPLORATION FRONTIER",
        ),
        _check(
            "last-graph-following-turn",
            "graph",
            "verified facts remain available on following turn",
            facts in following_turn.graph_facts_context,
            following_turn.graph_facts_context,
        ),
    ]


def _history_messages(current_question: str) -> list[BaseMessage]:
    old_payload = (
        "Result status=success. Persisted variable=df_old_result. "
        + "OLD_TOOL_PAYLOAD " * 600
    )
    recent_payload = (
        "Result status=success. Persisted variable=df_recent_result. "
        + "RECENT_TOOL_PAYLOAD " * 40
    )
    return [
        HumanMessage(content="Prépare une ancienne analyse.", id="history-human-1"),
        AIMessage(
            content="",
            id="history-ai-1",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df_neolabs_sample.copy()"},
                "id": "history-call-1",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=old_payload,
            name="run_pandas",
            tool_call_id="history-call-1",
            id="history-tool-1",
            artifact={"status": "success", "persisted": True, "data_ref": "df_old_result"},
        ),
        AIMessage(content="Ancienne analyse prête.", id="history-ai-1-final"),
        HumanMessage(content="Prépare ensuite une analyse récente.", id="history-human-2"),
        AIMessage(
            content="",
            id="history-ai-2",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df_ecotaxa_cache_query.copy()"},
                "id": "history-call-2",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=recent_payload,
            name="run_pandas",
            tool_call_id="history-call-2",
            id="history-tool-2",
            artifact={"status": "success", "persisted": True, "data_ref": "df_recent_result"},
        ),
        AIMessage(content="Analyse récente prête.", id="history-ai-2-final"),
        HumanMessage(content=current_question, id="history-human-3"),
    ]


def campaign_history(store: SessionStore) -> list[CampaignCheck]:
    scenario = "three-turn-compacted-history"
    thread_id = f"{BASE_THREAD}-history"
    seed_six_dataframes(store, thread_id)
    question = "Compare maintenant les deux ressources préparées."
    capture = _capture(
        store,
        thread_id,
        question,
        "history-current",
        input_messages=_history_messages(question),
    )
    humans = _human_messages(capture)
    tool_messages = [
        message for message in capture.messages if isinstance(message, ToolMessage)
    ]
    message_types = tuple(message.type for message in capture.messages)
    checkpoint_text = "\n".join(_content_text(message) for message in capture.state_messages)
    compacted = [
        message
        for message in tool_messages
        if "Résultat compacté" in _content_text(message)
    ]
    old_tool = next(
        (message for message in tool_messages if message.tool_call_id == "history-call-1"),
        None,
    )
    recent_tool = next(
        (message for message in tool_messages if message.tool_call_id == "history-call-2"),
        None,
    )
    current_human = humans[-1] if humans else None
    current_text = _content_text(current_human) if current_human else ""
    return [
        _check(
            scenario,
            "history",
            "human ai and tool chronology is preserved",
            message_types == (
                "system",
                "human", "ai", "tool", "ai",
                "human", "ai", "tool", "ai",
                "human",
            ),
            f"message_types={message_types}",
        ),
        _check(
            scenario,
            "history",
            "old tool payload is semantically compacted",
            old_tool is not None
            and "Résultat compacté" in _content_text(old_tool)
            and "data_ref=df_old_result" in _content_text(old_tool)
            and len(_content_text(old_tool)) < 1_200,
            f"compacted_tool_messages={len(compacted)}",
        ),
        _check(
            scenario,
            "history",
            "recent tool evidence remains semantically intact",
            recent_tool is not None
            and "status=success" in _content_text(recent_tool)
            and "data_ref=df_recent_result" in _content_text(recent_tool),
            "recent status and persistent data reference preserved",
        ),
        _check(
            scenario,
            "history",
            "application context prefixes only current provider-bound user message",
            current_text.count("<application_turn_context>") == 1
            and all(
                "<application_turn_context>" not in _content_text(message)
                for message in humans[:-1]
            ),
            f"human_messages={len(humans)}",
        ),
        _check(
            scenario,
            "history",
            "original current request is final unchanged block",
            capture.exact_user_request == question,
            f"exact_user_request={capture.exact_user_request}",
        ),
        _check(
            scenario,
            "history",
            "transient application context is not checkpointed",
            "<application_turn_context>" not in checkpoint_text,
            "synthetic context absent from state messages",
        ),
        _check(
            scenario,
            "history",
            "context audit reports compaction",
            int(capture.audit.get("old_tool_messages_compacted", 0)) >= 1
            and int(capture.audit.get("old_tool_result_chars_saved", 0)) > 0,
            "compacted="
            f"{capture.audit.get('old_tool_messages_compacted')}; saved_chars="
            f"{capture.audit.get('old_tool_result_chars_saved')}",
        ),
    ]


def campaign_long_turns(store: SessionStore) -> list[CampaignCheck]:
    scenario = "three-turn-checkpointed-context"
    questions = (
        "Tour 01 — inspecte les ressources.",
        "Tour 02 — résume les DataFrames.",
        "Tour 03 — rappelle la demande courante.",
    )
    snapshots = run_checkpointed_projection(
        store,
        f"{BASE_THREAD}-long-turns",
        questions,
    )
    checkpoint_humans = [
        message
        for message in snapshots[-1].checkpoint_messages
        if message.type == "human"
    ]
    return [
        _check(
            scenario,
            "long_turns",
            "three snapshots preserve sequential turns",
            len(snapshots) == 3
            and tuple(snapshot.turn for snapshot in snapshots) == (1, 2, 3)
            and tuple(snapshot.question for snapshot in snapshots) == questions,
            f"snapshots={len(snapshots)}; turns="
            f"{tuple(snapshot.turn for snapshot in snapshots)}",
        ),
        _check(
            scenario,
            "long_turns",
            "turn three checkpoint retains three human messages",
            snapshots[-1].turn == 3
            and len(checkpoint_humans) == 3
            and _content_text(checkpoint_humans[-1]) == questions[-1],
            f"checkpoint_human_messages={len(checkpoint_humans)}",
        ),
    ]


CAMPAIGNS: dict[str, Callable[[SessionStore], list[CampaignCheck]]] = {
    "current_task": campaign_current_task,
    "dataframes": campaign_dataframes,
    "frontier": campaign_frontier,
    "graph": campaign_graph,
    "history": campaign_history,
    "long_turns": campaign_long_turns,
}


def run_campaign(facets: Iterable[str]) -> list[CampaignCheck]:
    """Run selected context facets with isolated local persistence."""

    selected = tuple(facets)
    with TemporaryDirectory(prefix="idea-context-projection-") as directory:
        store = SessionStore(directory)
        with offline_only():
            return [
                result
                for facet in selected
                for result in CAMPAIGNS[facet](store)
            ]


def _print_text(results: Sequence[CampaignCheck]) -> None:
    current_facet = None
    for result in results:
        if result.facet != current_facet:
            current_facet = result.facet
            print(f"\n=== {current_facet.upper()} ===")
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.scenario} :: {result.name}")
        if not result.passed:
            print(f"       evidence: {result.evidence[:1_000]}")
    passed = sum(result.passed for result in results)
    failed = len(results) - passed
    print(f"\nSUMMARY: {passed} passed, {failed} failed, {len(results)} total")


def _print_json(results: Sequence[CampaignCheck]) -> None:
    payload = {
        "offline": True,
        "llm_calls": 0,
        "network_calls": 0,
        "summary": {
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
            "total": len(results),
        },
        "checks": [asdict(result) for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate IDEA's projected model context without an LLM."
    )
    parser.add_argument(
        "--facet",
        action="append",
        choices=FACETS,
        help="Run one facet; repeat the option to run several. Default: all.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable report instead of terminal output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run_campaign(args.facet or FACETS)
    if args.json:
        _print_json(results)
    else:
        _print_text(results)
    return int(any(not result.passed for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
