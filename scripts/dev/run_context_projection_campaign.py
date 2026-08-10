#!/usr/bin/env python3
"""Run deterministic campaigns against IDEA's model-bound context projection.

The campaign uses the production middleware with a local spy model. It never
calls an LLM, a source API, LangSmith, or the network. It validates only what
the application places in the model request: task, DataFrames, exploration
frontier, last-graph facts, useful history, and provider-visible tools.
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
    run_checkpointed_multiturn_harness,
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
    "tools", "long_turns", "thread_isolation",
)
DEFAULT_FACETS = FACETS
BASE_THREAD = "context-projection-campaign"
CURRENT_QUESTION = (
    "Donne, pour chaque station, le nombre de profils UVP associés à un "
    "prélèvement et le delta temporel moyen."
)
LONG_TURN_COUNT = 50
PENDING_WINDOW_QUESTION = (
    "Tours 20–25 — reprends la même analyse avec la dépendance en cours."
)
LONG_TURN_GRAPH_FACT = (
    "lignes tracées=50 · colonnes utilisées=station,value · "
    "table de rendu=df_long_turn_added · encodages=x=station;y=value"
)
LIFECYCLE_ORPHAN = "df_mt_orphan"
LIFECYCLE_REVIVABLE = "df_mt_revivable"
LIFECYCLE_PARENT = "df_mt_parent"
LIFECYCLE_CHILD = "df_mt_child"


def _long_turn_questions(count: int = LONG_TURN_COUNT) -> tuple[str, ...]:
    return tuple(
        PENDING_WINDOW_QUESTION
        if 20 <= turn <= 25
        else f"Tour 08 — analyse précisément {LIFECYCLE_REVIVABLE}."
        if turn == 8
        else "Tour 12 — analyse précisément df_neolabs_sample."
        if turn == 12
        else f"Tour {turn:02d} — décris les ressources pertinentes pour l’analyse {turn}."
        for turn in range(1, count + 1)
    )


@dataclass(frozen=True)
class CampaignCheck:
    """One deterministic assertion over the exact model-bound request."""

    scenario: str
    facet: str
    name: str
    passed: bool
    evidence: str
    turn_range: str = "not applicable"
    violated_contract: str = ""

    def __post_init__(self) -> None:
        if not self.violated_contract:
            object.__setattr__(self, "violated_contract", self.name)


def _check(
    scenario: str,
    facet: str,
    name: str,
    condition: bool,
    evidence: str,
    *,
    turn_range: str = "not applicable",
    violated_contract: str | None = None,
) -> CampaignCheck:
    return CampaignCheck(
        scenario=scenario,
        facet=facet,
        name=name,
        passed=bool(condition),
        evidence=evidence,
        turn_range=turn_range,
        violated_contract=violated_contract or name,
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
    return tuple(re.findall(r"^\* (df_[A-Za-z0-9_]+)(?: \||$)", context, re.MULTILINE))


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
    captures: tuple[ModelCapture, ...]
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
        if not new_calls:
            raise AssertionError(
                f"Expected at least one model call on turn {self.turn}, got none"
            )
        checkpoint_messages = tuple(result.get("messages") or ())
        captures = tuple(
            replace(
                _capture_from_model_call(model_call),
                audit=agent_module.get_context_audit(self.thread_id),
                state_messages=checkpoint_messages,
                turn=self.turn,
            )
            for model_call in new_calls
        )
        return TurnSnapshot(
            thread_id=self.thread_id,
            turn=self.turn,
            question=question,
            capture=captures[0],
            captures=captures,
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
        response_count=len(questions) * agent_module._MAX_MODEL_CALLS_PER_TURN,
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
            and "active status and recency are metadata only" in task
            and "Before any calculation, analysis or graph" in task
            and "## PLANNER DATASET CHOICE" in task
            and "The application has not selected a DataFrame" in task
            and "The first plan item must name the candidate DataFrame" in task
            and "call run_pandas only" in task
            and "wait for its result" in task,
            task[:700],
        ),
        _check(
            scenario,
            "current_task",
            "qualification is a sequential ReAct gate",
            "DataFrame qualification is a real ReAct gate" in capture.system
            and "do not batch the calculation or `run_graph` beside it" in capture.system
            and "result` dictionary" in capture.system,
            "plan -> run_pandas qualification -> wait -> calculate or graph",
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
            "- df_uvp_net_candidates\n  status=active" in six.dataset_context
            and "- df_station_summary\n  status=available" in six.dataset_context
            and set(details) == set(DATAFRAME_NAMES),
            f"expanded={details}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "source anchors precede request-relevant intermediates",
            set(details[:3]) == {
                "df_ecotaxa_cache_query",
                "df_neolabs_abundance",
                "df_neolabs_sample",
            }
            and details[3] == "df_station_summary",
            f"details={details}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "wide schema keeps useful roles and declares truncation",
            "schema_visibility=10/78 partial" in six.dataset_context
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
            "explicit intermediate leads the intermediate subset",
            len(explicit_details) >= 4 and explicit_details[3] == "df_old_plot",
            f"details={explicit_details}",
        )
    )

    mixed_thread = f"{BASE_THREAD}-df-mixed"
    mixed_file_names = ("df_file_abundance", "df_file_samples")
    mixed_derived_names = tuple(
        f"df_derived_candidate_{index:02d}" for index in range(10)
    )
    mixed_frame = pd.DataFrame({"sample_id": [1], "value": [2.0]})
    for name in mixed_file_names:
        store_dataset(
            store,
            mixed_thread,
            mixed_frame,
            variable_name=name,
            meta={
                "source": f"file:/uploads/{name}.csv",
                "description": f"Canonical uploaded source {name}.",
                "grain": "one row per sample",
                "primary_key": "sample_id",
            },
            set_active=False,
        )
    for name in mixed_derived_names:
        store_dataset(
            store,
            mixed_thread,
            mixed_frame.copy(),
            variable_name=name,
            meta={
                "source": "analysis:explicit-derived",
                "description": f"Reusable derived candidate {name}.",
                "grain": "one row per sample",
                "primary_key": "sample_id",
            },
            set_active=name == mixed_derived_names[0],
        )
    mixed_target = mixed_derived_names[-1]
    mixed = _capture(
        store,
        mixed_thread,
        f"Analyse précisément {mixed_target}.",
        "df-mixed",
    )
    mixed_details = _detail_names(mixed.dataset_context)
    mixed_non_file_details = tuple(
        name for name in mixed_details if name not in mixed_file_names
    )
    checks.extend([
        _check(
            "mixed-file-and-derived-dataframes",
            "dataframes",
            "file sources are always expanded before derived candidates",
            mixed_details[:2] == mixed_file_names,
            f"details={mixed_details}",
        ),
        _check(
            "mixed-file-and-derived-dataframes",
            "dataframes",
            "file cards do not consume the non-file detail quota",
            len(mixed_non_file_details) == 8
            and mixed_non_file_details[0] == mixed_target,
            f"non_file_details={mixed_non_file_details}",
        ),
    ])

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
            "all file-backed dataframes remain expanded",
            set(many_details) == set(many_names)
            and len(many_details) == MANY_DATAFRAME_COUNT,
            f"expanded={len(many_details)}",
        ),
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "explicit file target remains expanded",
            target in many_details,
            f"target={target}; expanded={target in many_details}",
        ),
        _check(
            "twenty-six-dataframes",
            "dataframes",
            "catalog remains within configured budget",
            len(many.dataset_context) <= 12_000,
            f"characters={len(many.dataset_context)}",
        ),
    ])

    anchor_thread = f"{BASE_THREAD}-df-source-anchors"
    anchor_names = (
        "df_file_samples",
        "df_ecotaxa_cache_query",
        "df_ecotaxa_export_42",
        "df_ecotaxa_ecopart_42",
        "df_amundsen_enriched_42",
        "df_bio_oracle_enriched_42",
    )
    anchor_frame = pd.DataFrame({
        "sample_id": [1, 2],
        "latitude": [60.0, 61.0],
        "longitude": [-65.0, -64.0],
        "value": [2.0, 3.0],
    })
    anchor_meta = (
        {
            "source": "file:/uploads/samples.csv",
            "description": "Canonical uploaded sample table.",
            "grain": "one row per sample",
        },
        {
            "source": "ecotaxa_cache",
            "description": "EcoTaxa cache selection at sample grain.",
            "grain": "one row per EcoTaxa sample",
            "input_dataframes": ["df_file_samples"],
        },
        {
            "source": "ecotaxa:42",
            "description": "Object-level EcoTaxa export.",
            "grain": "one row per EcoTaxa object",
            "source_variable": "df_ecotaxa_cache_query",
        },
        {
            "source": "join:ecotaxa+ecopart:84",
            "description": "EcoTaxa export enriched with EcoPart volume bins.",
            "grain": "one row per EcoTaxa object",
            "parent_variables": ["df_ecotaxa_export_42", "df_ecopart_84"],
        },
        {
            "source": "amundsen_enrichment",
            "description": "EcoPart-enriched rows matched to Amundsen CTD.",
            "grain": "one row per EcoTaxa object",
            "source_variable": "df_ecotaxa_ecopart_42",
        },
        {
            "source": "bio_oracle_enrichment",
            "description": "Amundsen-enriched rows coupled to Bio-ORACLE.",
            "grain": "one row per EcoTaxa object",
            "source_variable": "df_amundsen_enriched_42",
        },
    )
    for name, meta in zip(anchor_names, anchor_meta, strict=True):
        store_dataset(
            store,
            anchor_thread,
            anchor_frame.copy(),
            variable_name=name,
            meta=meta,
            set_active=False,
        )
    intermediate_names = tuple(
        f"df_anchor_intermediate_{index:02d}" for index in range(10)
    )
    for name in intermediate_names:
        store_dataset(
            store,
            anchor_thread,
            anchor_frame.copy(),
            variable_name=name,
            meta={
                "source": "analysis:derived",
                "description": f"Intermediate calculation {name}.",
                "grain": "one row per sample",
            },
            set_active=False,
        )
    anchor_target = intermediate_names[-1]
    anchor_capture = _capture(
        store,
        anchor_thread,
        f"Trace {anchor_target} en conservant les enrichissements disponibles.",
        "df-source-anchors",
    )
    anchor_details = _detail_names(anchor_capture.dataset_context)
    expanded_intermediates = tuple(
        name for name in anchor_details if name in intermediate_names
    )
    checks.extend([
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "files exports cache results and enrichments are all expanded",
            set(anchor_details[:len(anchor_names)]) == set(anchor_names),
            f"anchor_details={anchor_details[:len(anchor_names)]}",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "intermediate expansion remains bounded and request-ranked",
            len(expanded_intermediates) <= 8
            and expanded_intermediates
            and expanded_intermediates[0] == anchor_target,
            f"intermediates={expanded_intermediates}",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "enrichment lineage remains visible on the decision board",
            "source_variable:df_ecotaxa_ecopart_42" in anchor_capture.dataset_context
            and "source_variable:df_amundsen_enriched_42" in anchor_capture.dataset_context,
            "Amundsen and Bio-ORACLE parent variables are visible",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "decision board remains within configured budget",
            len(anchor_capture.dataset_context) <= 12_000,
            f"characters={len(anchor_capture.dataset_context)}",
        ),
    ])

    history_thread = f"{BASE_THREAD}-df-anchor-history"
    history_anchor_names = tuple(
        f"df_ecotaxa_cache_result_history_{index:02d}"
        for index in range(12)
    )
    for index, name in enumerate(history_anchor_names):
        store_dataset(
            store,
            history_thread,
            anchor_frame.copy(),
            variable_name=name,
            meta={
                "source": "ecotaxa_cache_result",
                "description": f"Durable EcoTaxa aggregate {index:02d}.",
                "grain": "one row per station",
            },
            set_active=False,
        )
    aged_capture = None
    for turn in range(1, 8):
        aged_capture = _capture(
            store,
            history_thread,
            "Décris les ressources générales de la session.",
            f"df-anchor-history-{turn}",
        )
    assert aged_capture is not None
    aged_details = tuple(
        name
        for name in _detail_names(aged_capture.dataset_context)
        if name in history_anchor_names
    )
    archived_target = history_anchor_names[-1]
    revived_capture = _capture(
        store,
        history_thread,
        f"Utilise précisément {archived_target} pour la prochaine analyse.",
        "df-anchor-history-revive",
    )
    revived_details = tuple(
        name
        for name in _detail_names(revived_capture.dataset_context)
        if name in history_anchor_names
    )
    checks.extend([
        _check(
            "durable-anchor-history",
            "dataframes",
            "all durable source anchors remain indexed",
            set(history_anchor_names).issubset(
                set(_index_names(aged_capture.dataset_context))
            ),
            f"indexed={len(_index_names(aged_capture.dataset_context))}",
        ),
        _check(
            "durable-anchor-history",
            "dataframes",
            "durable source detail cards are capped independently",
            len(aged_details) == 8
            and "durable source anchors are index-only"
            in aged_capture.dataset_context,
            f"expanded={aged_details}",
        ),
        _check(
            "durable-anchor-history",
            "dataframes",
            "archived source anchors are retained in storage",
            all(
                store.get(f"{history_thread}:dataset:{name}") is not None
                for name in history_anchor_names
            ),
            "12/12 durable anchors retained",
        ),
        _check(
            "durable-anchor-history",
            "dataframes",
            "exact reference revives an archived source card",
            archived_target in revived_details
            and revived_details[0] == archived_target
            and "last_used=current" in revived_capture.dataset_context,
            f"revived_details={revived_details}",
        ),
        _check(
            "durable-anchor-history",
            "dataframes",
            "history-managed catalog remains within budget",
            len(revived_capture.dataset_context) <= 12_000,
            f"characters={len(revived_capture.dataset_context)}",
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


def _seed_long_turn_dataframe_lifecycle(
    store: SessionStore,
    thread_id: str,
) -> None:
    """Seed source, stale, revived and lineage-protected lifecycle cases."""

    frame = pd.DataFrame({"sample_id": [1], "value": [2.0]})
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name=LIFECYCLE_PARENT,
        meta={
            "source": "analysis:join",
            "description": "Transient parent required by a persistent child.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        frame.copy(),
        variable_name=LIFECYCLE_CHILD,
        meta={
            "source": "analysis:explicit-derived",
            "description": "Persistent child retaining its declared parent.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
            "parent_variables": [LIFECYCLE_PARENT],
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        frame.copy(),
        variable_name=LIFECYCLE_REVIVABLE,
        meta={
            "source": "analysis:derived",
            "description": "Transient table explicitly reused before deletion.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        frame.copy(),
        variable_name=LIFECYCLE_ORPHAN,
        meta={
            "source": "analysis:derived",
            "description": "Unreferenced transient table eligible for cleanup.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
    )


def _mutate_long_turn_context(thread_id: str) -> TurnMutation:
    """Return the deterministic state transitions for the long-turn campaign."""

    pending_payload: dict[str, Any] | None = None
    pending_messages: list[BaseMessage] = []

    def mutate(
        turn: int,
        store: SessionStore,
        graph: Any,
        config: dict[str, Any],
    ) -> None:
        nonlocal pending_payload, pending_messages
        if turn == 5:
            store.set(
                f"{thread_id}:last_graph_grounding",
                None,
                {"facts": LONG_TURN_GRAPH_FACT},
            )
        elif turn == 10:
            store_dataset(
                store,
                thread_id,
                pd.DataFrame({
                    "sample_id": ["LT-001", "LT-002"],
                    "station": ["Hebron", "Sentinel"],
                    "value": [12.5, 8.0],
                }),
                variable_name="df_long_turn_added",
                meta={
                    "source": "campaign:long-turn-context",
                    "description": (
                        "Long-turn campaign table with station-level sample values."
                    ),
                    "grain": "one row per sample",
                    "primary_key": "sample_id",
                },
            )
        elif turn == 20:
            pending_payload, pending_messages = build_frontier_payload(
                store,
                thread_id,
                PENDING_WINDOW_QUESTION,
            )
            graph.update_state(config, {"exploration": pending_payload})
        elif turn == 25:
            if pending_payload is None:
                raise AssertionError("Long-turn frontier payload was never created")
            pending_payload = resolve_frontier_payload(
                pending_payload,
                pending_messages,
            )
            graph.update_state(config, {"exploration": pending_payload})

    return mutate


def _long_turn_checks(
    snapshots: Sequence[TurnSnapshot],
    questions: Sequence[str],
    thread_id: str,
) -> list[CampaignCheck]:
    """Validate every capture and checkpoint without assuming complete output."""

    scenario = "fifty-turn-checkpointed-context"
    expected_turns = tuple(range(1, LONG_TURN_COUNT + 1))
    snapshots_by_turn: dict[int, TurnSnapshot] = {}
    for snapshot in snapshots:
        snapshots_by_turn.setdefault(snapshot.turn, snapshot)

    def check(
        name: str,
        violation: tuple[int, str] | None,
        *,
        success_evidence: str,
        violated_contract: str | None = None,
    ) -> CampaignCheck:
        if violation is None:
            return _check(
                scenario,
                "long_turns",
                name,
                True,
                _bounded_evidence(success_evidence),
                turn_range="turns 1-50",
                violated_contract=violated_contract,
            )
        turn, evidence = violation
        return _check(
            scenario,
            "long_turns",
            name,
            False,
            _bounded_evidence(evidence),
            turn_range=f"turn {turn}",
            violated_contract=violated_contract,
        )

    def expected_question(turn: int) -> str | None:
        return questions[turn - 1] if 0 < turn <= len(questions) else None

    def checkpoint_humans(snapshot: TurnSnapshot) -> tuple[BaseMessage, ...]:
        return tuple(
            message
            for message in snapshot.checkpoint_messages
            if message.type == "human"
        )

    def first_mismatch(
        actual: Sequence[object],
        expected: Sequence[object],
    ) -> int | None:
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            if actual_item != expected_item:
                return index
        return len(actual) if len(actual) != len(expected) else None

    sequence_violation: tuple[int, str] | None = None
    for turn in expected_turns:
        snapshot = snapshots_by_turn.get(turn)
        question = expected_question(turn)
        if snapshot is None:
            sequence_violation = (turn, "missing checkpointed snapshot")
            break
        if question is None:
            sequence_violation = (turn, "missing expected question")
            break
        if snapshot.question != question:
            sequence_violation = (
                turn,
                f"question={snapshot.question!r}; expected={question!r}",
            )
            break
    if sequence_violation is None and len(snapshots) != LONG_TURN_COUNT:
        sequence_violation = (
            LONG_TURN_COUNT + 1,
            f"snapshot_count={len(snapshots)}; expected={LONG_TURN_COUNT}",
        )

    provider_captures = tuple(
        (snapshot.turn, call_index, capture)
        for snapshot in snapshots
        for call_index, capture in enumerate(snapshot.captures, start=1)
    )

    system_violation: tuple[int, str] | None = None
    if not provider_captures:
        system_violation = (1, "no provider captures retained")
    else:
        baseline_system = provider_captures[0][2].system
        for turn, call_index, capture in provider_captures:
            if capture.system != baseline_system:
                system_violation = (
                    turn,
                    f"provider_call={call_index}; system differs from turn 1 call 1",
                )
                break

    objective_violation: tuple[int, str] | None = None
    for turn in expected_turns:
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            objective_violation = (turn, "missing snapshot before provider validation")
            break
        if not snapshot.captures:
            objective_violation = (turn, "no provider captures retained")
            break
        for call_index, capture in enumerate(snapshot.captures, start=1):
            if capture.exact_user_request != snapshot.question:
                objective_violation = (
                    turn,
                    "provider_call="
                    f"{call_index}; exact_user_request={capture.exact_user_request!r}; "
                    f"expected={snapshot.question!r}",
                )
                break
            if f"Objective: {snapshot.question}" not in capture.task_context:
                objective_violation = (
                    turn,
                    f"provider_call={call_index}; current objective missing from task context",
                )
                break
        if objective_violation is not None:
            break

    milestone_violation: tuple[int, str] | None = None
    for milestone in (1, 10, 25, 50):
        snapshot = snapshots_by_turn.get(milestone)
        if snapshot is None:
            milestone_violation = (milestone, "missing milestone snapshot")
            break
        expected_contents = tuple(questions[:milestone])
        if len(expected_contents) != milestone:
            milestone_violation = (milestone, "missing expected question prefix")
            break
        humans = checkpoint_humans(snapshot)
        actual_ids = tuple(message.id for message in humans)
        expected_ids = tuple(
            f"{thread_id}-human-{turn:03d}"
            for turn in range(1, milestone + 1)
        )
        id_mismatch = first_mismatch(actual_ids, expected_ids)
        if id_mismatch is not None:
            violating_turn = min(id_mismatch + 1, milestone)
            milestone_violation = (
                violating_turn,
                f"milestone={milestone}; human_id_index={id_mismatch + 1}; "
                f"actual_count={len(actual_ids)}; expected_count={len(expected_ids)}",
            )
            break
        actual_contents = tuple(_content_text(message) for message in humans)
        content_mismatch = first_mismatch(actual_contents, expected_contents)
        if content_mismatch is not None:
            violating_turn = min(content_mismatch + 1, milestone)
            milestone_violation = (
                violating_turn,
                f"milestone={milestone}; human_content_index={content_mismatch + 1}; "
                f"actual_count={len(actual_contents)}; "
                f"expected_count={len(expected_contents)}",
            )
            break

    checkpoint_context_violation: tuple[int, str] | None = None
    for turn in expected_turns:
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            checkpoint_context_violation = (turn, "missing snapshot")
            break
        for message_index, message in enumerate(snapshot.checkpoint_messages, start=1):
            if "<application_turn_context>" in _content_text(message):
                checkpoint_context_violation = (
                    turn,
                    f"checkpoint_message_index={message_index} contains application context",
                )
                break
        if checkpoint_context_violation is not None:
            break

    provider_context_violation: tuple[int, str] | None = None
    for turn in expected_turns:
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            provider_context_violation = (turn, "missing snapshot")
            break
        if not snapshot.captures:
            provider_context_violation = (turn, "no provider captures retained")
            break
        for call_index, capture in enumerate(snapshot.captures, start=1):
            humans = _human_messages(capture)
            marker_count = sum(
                _content_text(message).count("<application_turn_context>")
                for message in capture.messages
            )
            if not humans:
                provider_context_violation = (
                    turn,
                    f"provider_call={call_index}; no Human message reaches the provider",
                )
                break
            if (
                marker_count != 1
                or _content_text(humans[-1]).count("<application_turn_context>") != 1
                or any(
                    "<application_turn_context>" in _content_text(message)
                    for message in humans[:-1]
                )
            ):
                provider_context_violation = (
                    turn,
                    f"provider_call={call_index}; marker_count={marker_count}; "
                    f"human_messages={len(humans)}",
                )
                break
        if provider_context_violation is not None:
            break

    dataframe_violation: tuple[int, str] | None = None
    for turn in range(9, LONG_TURN_COUNT + 1):
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            dataframe_violation = (turn, "missing snapshot")
            break
        contains_added_dataframe = "df_long_turn_added" in snapshot.capture.dataset_context
        if (turn == 9 and contains_added_dataframe) or (
            turn >= 10 and not contains_added_dataframe
        ):
            dataframe_violation = (
                turn,
                f"df_long_turn_added_present={contains_added_dataframe}",
            )
            break

    graph_violation: tuple[int, str] | None = None
    for turn in range(4, LONG_TURN_COUNT + 1):
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            graph_violation = (turn, "missing snapshot")
            break
        contains_graph_fact = LONG_TURN_GRAPH_FACT in snapshot.capture.graph_facts_context
        if (turn == 4 and contains_graph_fact) or (turn >= 5 and not contains_graph_fact):
            graph_violation = (
                turn,
                f"long_turn_graph_fact_present={contains_graph_fact}",
            )
            break

    frontier_violation: tuple[int, str] | None = None
    for turn in range(20, 25):
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            frontier_violation = (turn, "missing snapshot")
            break
        if "Resolve every pending data dependency" not in snapshot.capture.exploration_context:
            frontier_violation = (turn, "pending dependency is not projected")
            break
    if frontier_violation is None:
        snapshot = snapshots_by_turn.get(25)
        if snapshot is None:
            frontier_violation = (25, "missing snapshot")
        elif "Data dependencies: []" not in snapshot.capture.exploration_context:
            frontier_violation = (25, "resolved dependency list is not empty")

    budget_violation: tuple[int, str] | None = None
    for turn in expected_turns:
        snapshot = snapshots_by_turn.get(turn)
        if snapshot is None:
            budget_violation = (turn, "missing snapshot")
            break
        dataframe_chars = len(snapshot.capture.dataset_context)
        frontier_chars = len(snapshot.capture.exploration_context)
        if dataframe_chars > 12_000 or frontier_chars > 4_500:
            budget_violation = (
                turn,
                f"dataset_chars={dataframe_chars}; frontier_chars={frontier_chars}",
            )
            break

    chronology_violation: tuple[int, str] | None = None
    final_snapshot = snapshots_by_turn.get(LONG_TURN_COUNT)
    if final_snapshot is None:
        chronology_violation = (LONG_TURN_COUNT, "missing final snapshot")
    else:
        messages = final_snapshot.checkpoint_messages
        message_types = tuple(message.type for message in messages)
        humans = checkpoint_humans(final_snapshot)
        expected_ids = tuple(
            f"{thread_id}-human-{turn:03d}"
            for turn in expected_turns
        )
        actual_ids = tuple(message.id for message in humans)
        id_mismatch = first_mismatch(actual_ids, expected_ids)
        actual_contents = tuple(_content_text(message) for message in humans)
        content_mismatch = first_mismatch(actual_contents, tuple(questions))
        if id_mismatch is not None:
            chronology_violation = (
                min(id_mismatch + 1, LONG_TURN_COUNT),
                f"final_human_id_index={id_mismatch + 1}",
            )
        elif content_mismatch is not None:
            chronology_violation = (
                min(content_mismatch + 1, LONG_TURN_COUNT),
                f"final_human_content_index={content_mismatch + 1}",
            )
        elif (
            not message_types
            or message_types[0] != "human"
            or message_types[-1] != "ai"
            or any(message_type not in {"human", "ai"} for message_type in message_types)
            or any(
                index > 0 and message_types[index - 1] != "ai"
                for index, message_type in enumerate(message_types)
                if message_type == "human"
            )
            or any(
                index + 1 >= len(message_types)
                or message_types[index + 1] != "ai"
                for index, message_type in enumerate(message_types)
                if message_type == "human"
            )
        ):
            chronology_violation = (
                LONG_TURN_COUNT,
                f"message_count={len(messages)}; human_count={len(humans)}",
            )

    return [
        check(
            "fifty snapshots preserve the deterministic turn sequence",
            sequence_violation,
            success_evidence="50 sequential snapshots match all expected questions",
            violated_contract="fifty sequential checkpointed turns are captured",
        ),
        check(
            "permanent system message is byte-stable across every provider call",
            system_violation,
            success_evidence=f"provider_capture_count={len(provider_captures)}",
        ),
        check(
            "every provider call preserves its exact current objective",
            objective_violation,
            success_evidence="exact user request and task objective match on every call",
        ),
        check(
            "milestone checkpoints preserve ordered Human IDs and contents",
            milestone_violation,
            success_evidence="milestones 1, 10, 25, and 50 match Human ID and content prefixes",
        ),
        check(
            "application turn context is never checkpointed",
            checkpoint_context_violation,
            success_evidence="application context absent from every checkpoint message",
        ),
        check(
            "every provider call injects context once on its current Human message",
            provider_context_violation,
            success_evidence="one application context marker per retained provider capture",
        ),
        check(
            "added dataframe persists from turn 10 onward",
            dataframe_violation,
            success_evidence="turn 9 omits df_long_turn_added; turns 10-50 contain it",
        ),
        check(
            "last graph facts persist from turn 5 onward",
            graph_violation,
            success_evidence="turn 4 omits graph facts; turns 5-50 contain them",
        ),
        check(
            "pending frontier persists before resolving on turn 25",
            frontier_violation,
            success_evidence="turns 20-24 pending; turn 25 has Data dependencies: []",
        ),
        check(
            "dataframe and frontier contexts remain within their budgets",
            budget_violation,
            success_evidence="all dataframe contexts <=12000 and frontier contexts <=4500 chars",
        ),
        check(
            "turn 50 checkpoint chronology remains valid",
            chronology_violation,
            success_evidence="ordered Human IDs and contents retained through final AI response",
        ),
    ]


def _dataframe_lifecycle_checks(
    snapshots: Sequence[TurnSnapshot],
    store: SessionStore,
    thread_id: str,
) -> list[CampaignCheck]:
    """Validate real DataFrame aging, revival, ranking and lineage over 50 turns."""

    scenario = "fifty-turn-dataframe-lifecycle"
    by_turn = {snapshot.turn: snapshot for snapshot in snapshots}

    def context(turn: int) -> str:
        snapshot = by_turn.get(turn)
        return snapshot.capture.dataset_context if snapshot is not None else ""

    def first_presence_violation(
        variable: str,
        expectations: Sequence[tuple[range, bool]],
    ) -> tuple[int, str] | None:
        for turns, expected in expectations:
            for turn in turns:
                snapshot = by_turn.get(turn)
                if snapshot is None:
                    return turn, "missing snapshot"
                present = variable in snapshot.capture.dataset_context
                if present != expected:
                    return (
                        turn,
                        f"variable={variable}; present={present}; expected={expected}",
                    )
        return None

    def result(
        name: str,
        violation: tuple[int, str] | None,
        success: str,
    ) -> CampaignCheck:
        return _check(
            scenario,
            "long_turns",
            name,
            violation is None,
            success if violation is None else violation[1],
            turn_range=("turns 1-50" if violation is None else f"turn {violation[0]}"),
        )

    orphan_violation = first_presence_violation(
        LIFECYCLE_ORPHAN,
        ((range(1, 7), True), (range(7, LONG_TURN_COUNT + 1), False)),
    )
    if (
        orphan_violation is None
        and store.get(f"{thread_id}:dataset:{LIFECYCLE_ORPHAN}") is not None
    ):
        orphan_violation = (
            21,
            f"{LIFECYCLE_ORPHAN} hidden but not deleted after twenty unused turns",
        )

    revival_violation = first_presence_violation(
        LIFECYCLE_REVIVABLE,
        (
            (range(1, 7), True),
            (range(7, 8), False),
            (range(8, 14), True),
            (range(14, LONG_TURN_COUNT + 1), False),
        ),
    )
    if revival_violation is None:
        turn_8_details = _detail_names(context(8))
        turn_8_intermediate_details = tuple(
            name for name in turn_8_details
            if not name.startswith("df_neolabs_")
            and name != "df_ecotaxa_cache_query"
        )
        if (
            not turn_8_intermediate_details
            or turn_8_intermediate_details[0] != LIFECYCLE_REVIVABLE
        ):
            revival_violation = (
                8,
                "first_intermediate_detail="
                f"{turn_8_intermediate_details[0] if turn_8_intermediate_details else 'none'}",
            )

    lineage_violation = first_presence_violation(
        LIFECYCLE_PARENT,
        ((range(1, LONG_TURN_COUNT + 1), True),),
    )
    if lineage_violation is None:
        parent_entry = store.get(f"{thread_id}:dataset:{LIFECYCLE_PARENT}")
        child_entry = store.get(f"{thread_id}:dataset:{LIFECYCLE_CHILD}")
        if parent_entry is None or child_entry is None:
            lineage_violation = (
                LONG_TURN_COUNT,
                f"parent_persisted={parent_entry is not None}; "
                f"child_persisted={child_entry is not None}",
            )

    source_violation: tuple[int, str] | None = None
    source_names = (
        "df_neolabs_sample",
        "df_neolabs_abundance",
        "df_ecotaxa_cache_query",
    )
    for turn in range(1, LONG_TURN_COUNT + 1):
        missing = [name for name in source_names if name not in context(turn)]
        if missing:
            source_violation = (turn, f"missing source DataFrames={missing}")
            break

    ranking_violation: tuple[int, str] | None = None
    turn_12_details = _detail_names(context(12))
    if not turn_12_details or turn_12_details[0] != "df_neolabs_sample":
        ranking_violation = (
            12,
            f"first_detail={turn_12_details[0] if turn_12_details else 'none'}",
        )

    active_violation: tuple[int, str] | None = None
    turn_6 = by_turn.get(6)
    turn_7 = by_turn.get(7)
    active_at_6 = turn_6.capture.audit.get("turn_active_variable") if turn_6 else None
    active_at_7 = turn_7.capture.audit.get("turn_active_variable") if turn_7 else None
    if active_at_6 != LIFECYCLE_ORPHAN:
        active_violation = (6, f"active={active_at_6!r}; expected={LIFECYCLE_ORPHAN}")
    elif active_at_7 in {
        LIFECYCLE_ORPHAN,
        LIFECYCLE_REVIVABLE,
        "df_uvp_net_candidates",
        "df_station_summary",
        "df_old_plot",
    }:
        active_violation = (7, f"active remained stale transient: {active_at_7!r}")
    elif active_at_7 and active_at_7 not in _index_names(context(7)):
        active_violation = (7, f"active={active_at_7!r} is absent from live index")

    return [
        result(
            "unused transient is hidden after six turns and later deleted",
            orphan_violation,
            f"{LIFECYCLE_ORPHAN} visible on 1-6, hidden from 7, deleted by 21",
        ),
        result(
            "explicit reference revives and prioritizes a hidden dataframe",
            revival_violation,
            f"{LIFECYCLE_REVIVABLE} hidden on 7 and leads intermediate details on turn 8",
        ),
        result(
            "visible child preserves its transient lineage parent",
            lineage_violation,
            f"{LIFECYCLE_PARENT} remains visible and persisted through turn 50",
        ),
        result(
            "source dataframes remain available throughout cleanup",
            source_violation,
            "NeoLabs sample/abundance and EcoTaxa source remain indexed on all turns",
        ),
        result(
            "explicit source reference controls detail ranking without filtering",
            ranking_violation,
            "df_neolabs_sample is detailed first on turn 12",
        ),
        result(
            "active anchor leaves a dataframe when it becomes stale",
            active_violation,
            f"active changes from {active_at_6!r} to live {active_at_7!r}",
        ),
    ]


def campaign_long_turns(store: SessionStore) -> list[CampaignCheck]:
    thread_id = f"{BASE_THREAD}-long-turns"
    seed_six_dataframes(store, thread_id)
    _seed_long_turn_dataframe_lifecycle(store, thread_id)
    questions = _long_turn_questions()
    snapshots = run_checkpointed_projection(
        store,
        thread_id,
        questions,
        answer_chars=800,
        mutate_before_turn=_mutate_long_turn_context(thread_id),
    )
    return [
        *_long_turn_checks(snapshots, questions, thread_id),
        *_dataframe_lifecycle_checks(snapshots, store, thread_id),
        *_history_pressure_checks(store),
    ]


def _large_history(
    turns: int = 120,
    answer_chars: int = 5_000,
) -> list[BaseMessage]:
    """Build deterministic history large enough to exercise production trim."""

    messages: list[BaseMessage] = []
    for turn in range(1, turns + 1):
        messages.extend([
            HumanMessage(
                content=f"Historique {turn:03d} — demande synthétique.",
                id=f"pressure-human-{turn}",
            ),
            AIMessage(
                content=f"Réponse {turn:03d} " + ("P" * answer_chars),
                id=f"pressure-ai-{turn}",
            ),
        ])
    messages.append(HumanMessage(
        content="Demande actuelle sous forte pression de contexte.",
        id="pressure-current-human",
    ))
    return messages


def _history_pressure_checks(store: SessionStore) -> list[CampaignCheck]:
    """Validate graceful context degradation under a very large history."""

    scenario = "heavy-history-pressure"
    thread_id = f"{BASE_THREAD}-history-pressure"
    question = "Demande actuelle sous forte pression de contexte."
    seed_six_dataframes(store, thread_id)
    capture = _capture(
        store,
        thread_id,
        question,
        "pressure-current-human",
        input_messages=_large_history(),
    )
    audit = capture.audit
    humans = _human_messages(capture)
    checkpoint_text = "\n".join(
        _content_text(message) for message in capture.state_messages
    )
    non_system = tuple(
        message for message in capture.messages if message.type != "system"
    )
    marker_count = sum(
        _content_text(message).count("<application_turn_context>")
        for message in capture.messages
    )
    return [
        _check(
            scenario,
            "long_turns",
            "current request and task survive history pressure",
            capture.exact_user_request == question
            and f"Objective: {question}" in capture.task_context,
            f"exact_user_request={capture.exact_user_request!r}",
            turn_range="current turn after 120 historical turns",
        ),
        _check(
            scenario,
            "long_turns",
            "production history trimming is activated and bounded",
            int(audit.get("messages_trimmed", 0)) > 0
            and int(audit.get("messages_after_trim", 0))
            < int(audit.get("messages_before", 0))
            and int(audit.get("approx_tokens_model_request", 0))
            <= int(audit.get("max_context_tokens", 0)),
            "messages="
            f"{audit.get('messages_before')}->{audit.get('messages_after_trim')}; "
            f"tokens={audit.get('approx_tokens_model_request')}/"
            f"{audit.get('max_context_tokens')}",
            turn_range="current turn after 120 historical turns",
        ),
        _check(
            scenario,
            "long_turns",
            "trimmed provider history starts safely and ends on current Human",
            bool(non_system)
            and non_system[0].type == "human"
            and non_system[-1].type == "human"
            and bool(humans)
            and capture.exact_user_request == question,
            f"message_types={tuple(message.type for message in capture.messages)}",
            turn_range="current turn after 120 historical turns",
        ),
        _check(
            scenario,
            "long_turns",
            "all current dataframe resources survive history trimming",
            set(DATAFRAME_NAMES).issubset(set(_index_names(capture.dataset_context))),
            f"indexed={_index_names(capture.dataset_context)}",
            turn_range="current turn after 120 historical turns",
        ),
        _check(
            scenario,
            "long_turns",
            "permanent system and transient context boundaries remain intact",
            capture.system == agent_module._SYSTEM_PROMPT
            and marker_count == 1
            and bool(humans)
            and _content_text(humans[-1]).count("<application_turn_context>") == 1
            and all(
                "<application_turn_context>" not in _content_text(message)
                for message in humans[:-1]
            )
            and "<application_turn_context>" not in checkpoint_text,
            f"marker_count={marker_count}; checkpoint_polluted="
            f"{'<application_turn_context>' in checkpoint_text}",
            turn_range="current turn after 120 historical turns",
        ),
    ]


def _seed_private_thread_dataframe(
    store: SessionStore,
    thread_id: str,
    variable_name: str,
    description: str,
) -> None:
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "sample_id": [f"{thread_id}-sample"],
            "station": [f"{thread_id}-station"],
            "value": [1.0],
        }),
        variable_name=variable_name,
        meta={
            "source": f"campaign:{thread_id}",
            "description": description,
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
        set_active=False,
    )


def campaign_tools(store: SessionStore) -> list[CampaignCheck]:
    """Track the exact provider-visible tools across turns and ReAct steps."""

    scenario = "seven-turn-tool-exposure"
    thread_id = f"{BASE_THREAD}-tools"
    seed_six_dataframes(store, thread_id)
    questions = (
        "Bonjour.",
        "Inspecte les données EcoTaxa disponibles dans le cache.",
        "Calcule la moyenne par station dans df_neolabs_sample.",
        "Enrichis les profils avec EcoPart.",
        "Enrichis les profils avec Bio-ORACLE.",
        "Recherche dans la documentation la méthode de comparaison UVP-filet.",
        "Fais un graphique de la moyenne par station.",
    )
    snapshots = run_checkpointed_projection(
        store,
        thread_id,
        questions,
    )
    captures = tuple(snapshot.capture for snapshot in snapshots)
    catalog = build_tool_catalog(thread_id)
    catalog_names = set(catalog.names)
    hidden_legacy = {
        name
        for name, policy in catalog.policies.items()
        if policy.exposure_group == "hidden_legacy"
    }

    def first_call_violation(
        predicate: Callable[[ModelCapture], bool],
        detail: Callable[[ModelCapture], str],
    ) -> tuple[int, str] | None:
        for turn, capture in enumerate(captures, start=1):
            if not predicate(capture):
                return turn, detail(capture)
        return None

    parity_violation = first_call_violation(
        lambda capture: tuple(capture.audit.get("tools_exposed") or ())
        == capture.tool_names
        and int(capture.audit.get("tool_exposure_count") or 0)
        == len(capture.tool_names),
        lambda capture: (
            f"provider={capture.tool_names}; "
            f"audit={tuple(capture.audit.get('tools_exposed') or ())}; "
            f"audit_count={capture.audit.get('tool_exposure_count')}"
        ),
    )
    integrity_violation = first_call_violation(
        lambda capture: bool(capture.tool_names)
        and len(capture.tool_names) == len(set(capture.tool_names))
        and set(capture.tool_names) <= catalog_names,
        lambda capture: (
            f"count={len(capture.tool_names)}; "
            f"unique={len(set(capture.tool_names))}; "
            f"unknown={sorted(set(capture.tool_names) - catalog_names)}"
        ),
    )
    hidden_violation = first_call_violation(
        lambda capture: not (set(capture.tool_names) & hidden_legacy)
        and "load_skill" not in capture.tool_names,
        lambda capture: (
            "forbidden="
            f"{sorted((set(capture.tool_names) & hidden_legacy) | ({'load_skill'} & set(capture.tool_names)))}"
        ),
    )
    permanent_local = {
        "load_file",
        "query_copepod_knowledge_base",
        "run_pandas",
        "run_graph",
    }
    core_violation = first_call_violation(
        lambda capture: permanent_local <= set(capture.tool_names),
        lambda capture: (
            f"missing={sorted(permanent_local - set(capture.tool_names))}"
        ),
    )

    ecotaxa_expected = {
        "query_ecotaxa_cache",
        "list_ecotaxa_cache_tables",
        "describe_ecotaxa_cache_table",
    }
    ecotaxa_names = set(captures[1].tool_names)
    ecopart_names = set(captures[3].tool_names)
    bio_names = set(captures[4].tool_names)
    after_bio_names = set(captures[5].tool_names)
    graph_names = set(captures[6].tool_names)
    distinct_lists = {capture.tool_names for capture in captures}

    from tools.ecopart_sources import make_ecopart_tools
    from tools.tool_result import validate_tool_artifact

    ecopart_return_thread = f"{BASE_THREAD}-tools-ecopart-return"
    with patch("tools.ecopart_sources._store", store):
        ecopart_enrichment = next(
            tool
            for tool in make_ecopart_tools(ecopart_return_thread)
            if tool.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        ecopart_message = ecopart_enrichment.invoke({
            "type": "tool_call",
            "id": "ecopart-return-contract",
            "name": ecopart_enrichment.name,
            "args": {},
        })
    ecopart_artifact = validate_tool_artifact(ecopart_message.artifact)

    with TemporaryDirectory(prefix="idea-tool-react-") as graph_directory:
        react_thread = f"{BASE_THREAD}-tools-react"
        seed_six_dataframes(store, react_thread)
        react_calls, _turn_results = run_checkpointed_multiturn_harness(
            store,
            react_thread,
            Path(graph_directory),
        )
    react_hidden = next(
        (
            (index, sorted(set(capture.tool_names) & hidden_legacy))
            for index, capture in enumerate(react_calls, start=1)
            if set(capture.tool_names) & hidden_legacy
            or "load_skill" in capture.tool_names
        ),
        None,
    )
    react_integrity = next(
        (
            (
                index,
                f"count={len(capture.tool_names)}; "
                f"unique={len(set(capture.tool_names))}; "
                f"unknown={sorted(set(capture.tool_names) - catalog_names)}",
            )
            for index, capture in enumerate(react_calls, start=1)
            if not capture.tool_names
            or len(capture.tool_names) != len(set(capture.tool_names))
            or not set(capture.tool_names) <= catalog_names
        ),
        None,
    )
    forced_calls = tuple(
        capture for capture in react_calls if capture.tool_choice is not None
    )
    forced_choices_valid = bool(forced_calls) and all(
        isinstance(capture.tool_choice, dict)
        and str(
            ((capture.tool_choice.get("function") or {}).get("name"))
        ) in capture.tool_names
        for capture in forced_calls
    )
    forced_tool_names = {
        str(((capture.tool_choice.get("function") or {}).get("name")))
        for capture in forced_calls
        if isinstance(capture.tool_choice, dict)
    }
    turn_one_lists = {
        capture.tool_names for capture in react_calls if capture.turn == 1
    }

    return [
        _check(
            scenario,
            "tools",
            "provider tools exactly match the runtime exposure audit",
            parity_violation is None,
            "all seven turns match"
            if parity_violation is None
            else f"turn {parity_violation[0]}: {parity_violation[1]}",
            turn_range="turns 1-7",
        ),
        _check(
            scenario,
            "tools",
            "every tool list is non-empty unique and catalog-backed",
            integrity_violation is None,
            "all visible names belong to the production catalog"
            if integrity_violation is None
            else f"turn {integrity_violation[0]}: {integrity_violation[1]}",
            turn_range="turns 1-7",
        ),
        _check(
            scenario,
            "tools",
            "hidden legacy and skill-loader tools never reach the provider",
            hidden_violation is None,
            "no hidden legacy tool and no load_skill"
            if hidden_violation is None
            else f"turn {hidden_violation[0]}: {hidden_violation[1]}",
            turn_range="turns 1-7",
        ),
        _check(
            scenario,
            "tools",
            "local analysis graph file and RAG capabilities remain reachable",
            core_violation is None,
            "load_file, RAG, run_pandas and run_graph visible on every turn"
            if core_violation is None
            else f"turn {core_violation[0]}: {core_violation[1]}",
            turn_range="turns 1-7",
        ),
        _check(
            scenario,
            "tools",
            "EcoTaxa requests expose only the canonical cache discovery route",
            ecotaxa_expected <= ecotaxa_names
            and not (ecotaxa_names & hidden_legacy),
            f"turn_2={sorted(ecotaxa_names)}",
            turn_range="turn 2",
        ),
        _check(
            scenario,
            "tools",
            "explicit EcoPart enrichment exposes enrichment and preflight capabilities",
            {
                "enrich_ecotaxa_with_ecopart_remote",
                "find_ecopart_project_for_ecotaxa",
                "preview_ecopart_sample",
                "run_pandas",
                "run_graph",
            } <= ecopart_names,
            f"turn_4={sorted(ecopart_names)}",
            turn_range="turn 4",
        ),
        _check(
            scenario,
            "tools",
            "EcoPart return reaches the agent as visible content plus structured artifact",
            isinstance(ecopart_message, ToolMessage)
            and "Données EcoTaxa manquantes" in str(ecopart_message.content)
            and ecopart_artifact.status == "blocked"
            and ecopart_artifact.provenance.get("source") == "ecopart"
            and ecopart_artifact.data_ref is None
            and not ecopart_artifact.persisted,
            f"message_type={type(ecopart_message).__name__}; "
            f"status={ecopart_artifact.status}; "
            f"provenance={ecopart_artifact.provenance}",
            turn_range="offline tool call",
        ),
        _check(
            scenario,
            "tools",
            "explicit Bio-ORACLE enrichment adds its canonical tool without losing local tools",
            "enrich_with_bio_oracle" in bio_names
            and {"run_pandas", "run_graph"} <= bio_names,
            f"turn_5={sorted(bio_names)}",
            turn_range="turn 5",
        ),
        _check(
            scenario,
            "tools",
            "specialized enrichment does not leak into following unrelated turns",
            "enrich_with_bio_oracle" not in after_bio_names
            and "enrich_with_bio_oracle" not in graph_names,
            f"turn_6={sorted(after_bio_names)}; turn_7={sorted(graph_names)}",
            turn_range="turns 6-7",
        ),
        _check(
            scenario,
            "tools",
            "tool exposure adapts rather than accumulating monotonically",
            len(distinct_lists) >= 3,
            f"distinct_provider_tool_lists={len(distinct_lists)}",
            turn_range="turns 1-7",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "every ReAct provider call keeps a valid catalog-backed tool list",
            react_integrity is None,
            f"provider_calls={len(react_calls)}"
            if react_integrity is None
            else f"call {react_integrity[0]}: {react_integrity[1]}",
            turn_range="7 provider calls across 3 turns",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "hidden legacy tools stay absent after tool results and retries",
            react_hidden is None,
            "no hidden legacy tool and no load_skill on all ReAct calls"
            if react_hidden is None
            else f"call {react_hidden[0]}: forbidden={react_hidden[1]}",
            turn_range="7 provider calls across 3 turns",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "forced pandas recovery names a currently visible tool",
            forced_choices_valid
            and forced_tool_names == {"run_pandas"},
            f"forced_tools={sorted(forced_tool_names)}; "
            f"all_visible={forced_choices_valid}",
            turn_range="turn 1",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "graph capability remains visible throughout the graph turn",
            bool(tuple(capture for capture in react_calls if capture.turn == 2))
            and all(
                "run_graph" in capture.tool_names
                for capture in react_calls
                if capture.turn == 2
            ),
            "run_graph is provider-visible before and after graph execution",
            turn_range="turn 2",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "tool schemas remain stable during the same-turn pandas recovery",
            len(turn_one_lists) == 1,
            f"turn_1_provider_calls={sum(capture.turn == 1 for capture in react_calls)}; "
            f"distinct_tool_lists={len(turn_one_lists)}",
            turn_range="turn 1",
        ),
    ]


def campaign_thread_isolation(store: SessionStore) -> list[CampaignCheck]:
    """Interleave two checkpointed threads and reject context leakage."""

    scenario = "two-interleaved-checkpointed-threads"
    thread_a = f"{BASE_THREAD}-isolation-a"
    thread_b = f"{BASE_THREAD}-isolation-b"
    seed_six_dataframes(store, thread_a)
    seed_six_dataframes(store, thread_b)
    _seed_private_thread_dataframe(
        store, thread_a, "df_thread_a_private", "THREAD_A_ONLY"
    )
    _seed_private_thread_dataframe(
        store, thread_b, "df_thread_b_private", "THREAD_B_ONLY"
    )
    store.set(
        f"{thread_a}:last_graph_grounding", None, {"facts": "GRAPH_A_ONLY"}
    )
    store.set(
        f"{thread_b}:last_graph_grounding", None, {"facts": "GRAPH_B_ONLY"}
    )
    questions_a = tuple(
        f"A{turn:02d} — inspecte df_thread_a_private dans ce fil."
        for turn in range(1, 13)
    )
    questions_b = tuple(
        f"B{turn:02d} — inspecte df_thread_b_private dans ce fil."
        for turn in range(1, 13)
    )
    session_a = CheckpointedProjectionSession(
        store,
        thread_a,
        response_count=12 * agent_module._MAX_MODEL_CALLS_PER_TURN,
    )
    session_b = CheckpointedProjectionSession(
        store,
        thread_b,
        response_count=12 * agent_module._MAX_MODEL_CALLS_PER_TURN,
    )
    snapshots_a: list[TurnSnapshot] = []
    snapshots_b: list[TurnSnapshot] = []
    for question in questions_a[:6]:
        snapshots_a.append(session_a.invoke(question))
    for question in questions_b[:6]:
        snapshots_b.append(session_b.invoke(question))
    for question in questions_a[6:]:
        snapshots_a.append(session_a.invoke(question))
    for question in questions_b[6:]:
        snapshots_b.append(session_b.invoke(question))

    def first_leak(
        snapshots: Sequence[TurnSnapshot],
        required: Sequence[str],
        forbidden: Sequence[str],
    ) -> tuple[int, str] | None:
        for snapshot in snapshots:
            for call_index, capture in enumerate(snapshot.captures, start=1):
                text = capture.runtime_context
                missing = [marker for marker in required if marker not in text]
                leaked = [marker for marker in forbidden if marker in text]
                if missing or leaked:
                    return (
                        snapshot.turn,
                        f"provider_call={call_index}; missing={missing}; leaked={leaked}",
                    )
        return None

    def isolation_check(
        name: str,
        violation: tuple[int, str] | None,
        success: str,
    ) -> CampaignCheck:
        return _check(
            scenario,
            "thread_isolation",
            name,
            violation is None,
            success if violation is None else violation[1],
            turn_range=("turns 1-12" if violation is None else f"turn {violation[0]}"),
        )

    leak_a = first_leak(
        snapshots_a,
        ("df_thread_a_private", "THREAD_A_ONLY", "GRAPH_A_ONLY"),
        ("df_thread_b_private", "THREAD_B_ONLY", "GRAPH_B_ONLY"),
    )
    leak_b = first_leak(
        snapshots_b,
        ("df_thread_b_private", "THREAD_B_ONLY", "GRAPH_B_ONLY"),
        ("df_thread_a_private", "THREAD_A_ONLY", "GRAPH_A_ONLY"),
    )
    sequence_violation: tuple[int, str] | None = None
    if tuple(snapshot.turn for snapshot in snapshots_a) != tuple(range(1, 13)):
        sequence_violation = (1, "thread A local turn sequence is not 1..12")
    elif tuple(snapshot.turn for snapshot in snapshots_b) != tuple(range(1, 13)):
        sequence_violation = (1, "thread B local turn sequence is not 1..12")

    history_violation: tuple[int, str] | None = None
    for label, thread_id, snapshots, questions in (
        ("A", thread_a, snapshots_a, questions_a),
        ("B", thread_b, snapshots_b, questions_b),
    ):
        if len(snapshots) != 12:
            history_violation = (12, f"thread {label} snapshot_count={len(snapshots)}")
            break
        humans = tuple(
            message
            for message in snapshots[-1].checkpoint_messages
            if message.type == "human"
        )
        contents = tuple(_content_text(message) for message in humans)
        ids = tuple(message.id for message in humans)
        expected_ids = tuple(
            f"{thread_id}-human-{turn:03d}" for turn in range(1, 13)
        )
        if contents != questions or ids != expected_ids:
            history_violation = (
                12,
                f"thread {label} human_count={len(humans)}; exact_history=False",
            )
            break

    boundary_violation: tuple[int, str] | None = None
    all_snapshots = (*snapshots_a, *snapshots_b)
    systems = {
        capture.system
        for snapshot in all_snapshots
        for capture in snapshot.captures
    }
    if len(systems) != 1:
        boundary_violation = (1, f"permanent_system_variants={len(systems)}")
    else:
        for snapshot in all_snapshots:
            checkpoint_text = "\n".join(
                _content_text(message) for message in snapshot.checkpoint_messages
            )
            if "<application_turn_context>" in checkpoint_text:
                boundary_violation = (
                    snapshot.turn,
                    f"thread={snapshot.thread_id}; checkpoint contains transient context",
                )
                break

    return [
        isolation_check(
            "thread A exposes only its private dataframe and graph facts",
            leak_a,
            "A private markers present; B markers absent on all provider calls",
        ),
        isolation_check(
            "thread B exposes only its private dataframe and graph facts",
            leak_b,
            "B private markers present; A markers absent on all provider calls",
        ),
        isolation_check(
            "interleaving preserves independent local turn counters",
            sequence_violation,
            "both local turn sequences are exactly 1..12",
        ),
        isolation_check(
            "each final checkpoint contains only its exact twelve Human turns",
            history_violation,
            "both final checkpoints contain exact thread-owned IDs and contents",
        ),
        isolation_check(
            "system and transient checkpoint boundaries remain isolated",
            boundary_violation,
            "one permanent system; no checkpoint contains application context",
        ),
    ]


CAMPAIGNS: dict[str, Callable[[SessionStore], list[CampaignCheck]]] = {
    "current_task": campaign_current_task,
    "dataframes": campaign_dataframes,
    "frontier": campaign_frontier,
    "graph": campaign_graph,
    "history": campaign_history,
    "tools": campaign_tools,
    "long_turns": campaign_long_turns,
    "thread_isolation": campaign_thread_isolation,
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


_MAX_EVIDENCE_CHARS = 1_000


def _bounded_evidence(evidence: str) -> str:
    return evidence[:_MAX_EVIDENCE_CHARS]


def _print_text(results: Sequence[CampaignCheck]) -> None:
    current_facet = None
    for result in results:
        if result.facet != current_facet:
            current_facet = result.facet
            print(f"\n=== {current_facet.upper()} ===")
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.scenario} :: {result.name}")
        if not result.passed:
            print(f"       turn_range: {result.turn_range}")
            print(f"       violated_contract: {result.violated_contract}")
            print(f"       evidence: {_bounded_evidence(result.evidence)}")
    passed = sum(result.passed for result in results)
    failed = len(results) - passed
    print(f"\nSUMMARY: {passed} passed, {failed} failed, {len(results)} total")


def _print_json(results: Sequence[CampaignCheck]) -> None:
    checks = []
    for result in results:
        check = asdict(result)
        check["evidence"] = _bounded_evidence(result.evidence)
        checks.append(check)
    payload = {
        "offline": True,
        "llm_calls": 0,
        "network_calls": 0,
        "campaign": {
            "long_turn_count": LONG_TURN_COUNT,
            "offline": True,
        },
        "summary": {
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
            "total": len(results),
        },
        "checks": checks,
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
        help=(
            "Run one facet; repeat the option to run several. "
            "Default: all executable facets."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable report instead of terminal output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run_campaign(args.facet or DEFAULT_FACETS)
    if args.json:
        _print_json(results)
    else:
        _print_text(results)
    return int(any(not result.passed for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
