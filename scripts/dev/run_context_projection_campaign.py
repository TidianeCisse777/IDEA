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
    "continuity", "cache", "budget", "tools", "memory", "long_turns",
    "thread_isolation",
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
CONTINUITY_RAW = "df_ecotaxa_cache_result_neolabs_candidates_5h"
CONTINUITY_DERIVED = "df_derived_neolabs_ecotaxa_matched_deployments_5h"
CONTINUITY_STALE_ACTIVE = "df_derived_vertical_object_environment_14844"
CONTINUITY_TOTAL = 14
CONTINUITY_EXPANDED = 12
CONTINUITY_INDEX_ONLY = CONTINUITY_TOTAL - CONTINUITY_EXPANDED
HISTORY_REPLAY_UVP = "df_file_fichier_sample"
HISTORY_REPLAY_ABUNDANCE = "df_file_neolabs_abundance"
HISTORY_REPLAY_MATCHES = "df_derived_uvp_filet_ecart_10h"
HISTORY_REPLAY_BAD_JOIN = (
    "df_derived_reprise_comparaison_uvp_filet_abondance_copepoda"
)
HISTORY_REPLAY_FOLLOWUPS = (
    "Présente les stations dans le même ordre.",
    "Ajoute une ligne Total à la fin.",
    "Indique aussi le nombre de profils.",
    "Affiche les résultats avec des valeurs arrondies.",
    "Continue avec ce qu'on avait demandé.",
    "Donne maintenant la réponse finale.",
)


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
            "turn facts are projected without duplicating permanent rules",
            "Required deliverables: answer" in task
            and "## PLANNER DATASET CHOICE" in task
            and "Application selection: none" in task
            and "DATA SELECTION CONTRACT:" not in task
            and "Qualification is conditional, not a ritual" in capture.system,
            task[:700],
        ),
        _check(
            scenario,
            "current_task",
            "qualification is conditional and evidence-driven",
            "Qualification is conditional, not a ritual" in capture.system
            and "only for a material unknown" in capture.system
            and "directly answers a simple list, lookup" in capture.system
            and "wait for that tool result" in capture.system,
            "known evidence -> operate; material uncertainty -> qualify once -> operate",
        ),
        _check(
            scenario,
            "current_task",
            "source route is a non-blocking hint",
            "Preferred source route:" in task
            and "primary=file" in task,
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
            "factual inventory order does not promote the stale active pointer",
            details[0] == "df_ecotaxa_cache_query"
            and details[0] != "df_uvp_net_candidates"
            and set(details) == set(DATAFRAME_NAMES),
            f"details={details}",
        ),
        _check(
            "six-dataframes-misleading-active",
            "dataframes",
            "wide schema keeps useful roles and declares truncation",
            "schema_visibility=10/78 partial" in six.dataset_context
            and any(
                f"DEPLOYMENT_DATE_START:{dtype}" in six.dataset_context
                for dtype in ("object", "str", "string")
            )
            and any(
                f"DEPLOYMENT_TIME_START:{dtype}" in six.dataset_context
                for dtype in ("object", "str", "string")
            )
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
            "explicit intermediate leads the factual working set",
            bool(explicit_details) and explicit_details[0] == "df_old_plot",
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
            "explicit derived target precedes fallback file resources",
            mixed_details[0] == mixed_target
            and set(mixed_file_names) <= set(mixed_details),
            f"details={mixed_details}",
        ),
        _check(
            "mixed-file-and-derived-dataframes",
            "dataframes",
            "working-set expansion uses one shared twelve-card budget",
            len(mixed_details) == 12
            and len(mixed_non_file_details) == 10
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
            "detail cards are capped while the complete index remains available",
            len(many_details) == 12
            and int(many.audit.get("dataframe_catalog_total") or 0) == 26
            and int(many.audit.get("dataframe_catalog_expanded") or 0) == 12
            and int(many.audit.get("dataframe_catalog_index_only") or 0) == 14,
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
            len(many.dataset_context) <= 9_000,
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
            "all source and enrichment resources remain discoverable in the index",
            set(anchor_names) <= set(_index_names(anchor_capture.dataset_context))
            and anchor_details[0] == anchor_target,
            f"anchor_details={anchor_details}",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "intermediate expansion remains bounded and fact-ranked",
            len(expanded_intermediates) <= 12
            and expanded_intermediates
            and expanded_intermediates[0] == anchor_target,
            f"intermediates={expanded_intermediates}",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "selected enrichment lineage remains visible on the working set",
            "source_variable:df_ecotaxa_ecopart_42" in anchor_capture.dataset_context,
            "selected Amundsen parent variable is visible",
        ),
        _check(
            "source-export-enrichment-anchors",
            "dataframes",
            "decision board remains within configured budget",
            len(anchor_capture.dataset_context) <= 9_000,
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
            "durable source detail cards share the bounded working-set budget",
            len(aged_details) == 12
            and int(aged_capture.audit.get("dataframe_catalog_index_only") or 0) == 0,
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
            len(revived_capture.dataset_context) <= 9_000,
            f"characters={len(revived_capture.dataset_context)}",
        ),
    ])
    return checks


def _seed_context_continuity_dataframes(
    store: SessionStore,
    thread_id: str,
) -> tuple[str, ...]:
    """Seed the 14-resource shape from the observed NeoLabs/EcoTaxa failure."""

    file_frame = pd.DataFrame({
        "deployment_id": ["NET-001", "NET-002"],
        "station": ["Hebron", "Sentinel"],
    })
    for name in ("df_file_neolabs_samples", "df_file_neolabs_abundance"):
        store_dataset(
            store,
            thread_id,
            file_frame.copy(),
            variable_name=name,
            meta={
                "source": f"file:/uploads/{name}.csv",
                "description": f"Canonical uploaded fixture {name}.",
                "grain": "one row per NeoLabs deployment",
                "primary_key": "deployment_id",
            },
            set_active=False,
        )

    raw = pd.DataFrame({
        "deployment_id": [f"NET-{index % 222:03d}" for index in range(1_632)],
        "profile_id": [f"UVP-{index:04d}" for index in range(1_632)],
        "time_delta_hours": [float(index % 11) for index in range(1_632)],
        "match_status": ["candidate"] * 1_632,
    })
    store_dataset(
        store,
        thread_id,
        raw,
        variable_name=CONTINUITY_RAW,
        meta={
            "source": "ecotaxa_cache_result",
            "description": (
                "Raw NeoLabs-to-EcoTaxa candidates before the matched-only and "
                "five-hour filters."
            ),
            "grain": "one candidate EcoTaxa profile per NeoLabs deployment",
            "primary_keys": ["deployment_id", "profile_id"],
            "filters": {"station_exact_normalized": True},
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "project_id": [14844],
            "profile_count": [1_632],
        }),
        variable_name="df_ecotaxa_cache_project_14844",
        meta={
            "source": "ecotaxa_cache_result",
            "description": "Durable project-level EcoTaxa cache summary.",
            "grain": "one row per EcoTaxa project",
            "primary_key": "project_id",
        },
        set_active=False,
    )

    matched = raw.iloc[:222].copy()
    matched["match_status"] = "matched"
    store_dataset(
        store,
        thread_id,
        matched,
        variable_name=CONTINUITY_DERIVED,
        meta={
            "source": "analysis:derived",
            "description": (
                "Matched NeoLabs deployments and EcoTaxa UVP profiles within "
                "the verified five-hour window."
            ),
            "grain": "one matched candidate per NeoLabs deployment",
            "primary_keys": ["deployment_id", "profile_id"],
            "parent_variable": CONTINUITY_RAW,
            "filters": {
                "instrument_like": "UVP%",
                "time_window_hours": 5,
                "match_status": "matched",
            },
        },
        set_active=False,
    )

    filler_names = tuple(
        f"df_derived_context_fixture_{index:02d}" for index in range(8)
    )
    filler_frame = pd.DataFrame({"profile_id": ["UVP-0001"], "value": [1.0]})
    for name in filler_names:
        store_dataset(
            store,
            thread_id,
            filler_frame.copy(),
            variable_name=name,
            meta={
                "source": "analysis:derived",
                "description": f"Unrelated persisted analysis fixture {name}.",
                "grain": "one row per profile",
                "primary_key": "profile_id",
            },
            set_active=False,
        )
    store_dataset(
        store,
        thread_id,
        filler_frame.copy(),
        variable_name=CONTINUITY_STALE_ACTIVE,
        meta={
            "source": "analysis:derived",
            "description": "Older vertical environment result from another task.",
            "grain": "one row per profile and depth",
            "primary_key": "profile_id",
        },
    )
    names = (
        "df_file_neolabs_samples",
        "df_file_neolabs_abundance",
        CONTINUITY_RAW,
        "df_ecotaxa_cache_project_14844",
        CONTINUITY_DERIVED,
        *filler_names,
        CONTINUITY_STALE_ACTIVE,
    )
    if len(names) != CONTINUITY_TOTAL:
        raise AssertionError(f"continuity fixture has {len(names)} resources")
    return names


def _continuity_history(question: str) -> list[BaseMessage]:
    """Return factual tool evidence followed by a generic, name-free follow-up."""

    prior_question = "Compare les déploiements NeoLabs aux profils UVP disponibles."
    return [
        HumanMessage(content=prior_question, id="continuity-human-1"),
        AIMessage(
            content="",
            id="continuity-ai-tool",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = matched_candidates.copy()"},
                "id": "continuity-tool-call",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=(
                "status=success; rows=222; grain=one matched candidate per "
                "NeoLabs deployment; persisted=true"
            ),
            name="run_pandas",
            tool_call_id="continuity-tool-call",
            id="continuity-tool-result",
            artifact={
                "status": "success",
                "persisted": True,
                "data_ref": CONTINUITY_DERIVED,
                "rows": 222,
                "grain": "one matched candidate per NeoLabs deployment",
                "provenance": {
                    "source": "analysis:derived",
                    "parent_variable": CONTINUITY_RAW,
                },
            },
        ),
        AIMessage(
            content="La comparaison demandée est prête.",
            id="continuity-ai-final",
        ),
        HumanMessage(content=question, id="continuity-human-2"),
    ]


def _catalog_audit_counts(capture: ModelCapture) -> tuple[int, int, int]:
    return (
        int(capture.audit.get("dataframe_catalog_total") or 0),
        int(capture.audit.get("dataframe_catalog_expanded") or 0),
        int(capture.audit.get("dataframe_catalog_index_only") or 0),
    )


def _seed_uvp_net_history_replay(store: SessionStore, thread_id: str) -> None:
    """Seed the four factual tables involved in the observed failed dialogue."""

    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "sample_profileid": ["UVP-01", "UVP-02"],
            "sample_stationid": ["M1b", "M2b"],
            "object_annotation_hierarchy": ["Copepoda", "Copepoda"],
        }),
        variable_name=HISTORY_REPLAY_UVP,
        meta={
            "source": "file:/uploads/Fichier sample.tsv",
            "description": "Objets EcoTaxa exportés avec profil et station.",
            "grain": "une ligne par objet EcoTaxa",
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "SAMPLE_ID": [8001, 8002],
            "STATION_NAME": ["101", "102"],
            "TAXON_ID": ["Copepoda", "Copepoda"],
            "ALL_STAGES_ABUND": [12.0, 8.0],
        }),
        variable_name=HISTORY_REPLAY_ABUNDANCE,
        meta={
            "source": "file:/uploads/neolabs_abundance.csv",
            "description": "Abondances NeoLabs par taxon et analyse.",
            "grain": "une ligne par taxon et analyse NeoLabs",
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "sample_profileid": ["UVP-01", "UVP-02"],
            "sample_stationid": ["M1b", "M2b"],
            "sample_id": [49342, 49373],
            "ecart_heures": [3.7, 4.2],
        }),
        variable_name=HISTORY_REPLAY_MATCHES,
        meta={
            "source": "analysis:derived",
            "description": "Profils UVP et prélèvements filet appariés par station et temps.",
            "grain": "une ligne par profil UVP et prélèvement filet correspondant",
            "parent_variables": [HISTORY_REPLAY_UVP],
            "filters": {"time_delta_max_hours": 10},
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({
            "sample_profileid": ["UVP-01", "UVP-02"],
            "sample_stationid": ["M1b", "M2b"],
            "abondance_copepoda": [pd.NA, pd.NA],
        }),
        variable_name=HISTORY_REPLAY_BAD_JOIN,
        meta={
            "source": "analysis:derived",
            "description": "Tentative de jointure dont l'abondance est absente.",
            "grain": "une ligne par correspondance UVP-filet",
            "parent_variables": [
                HISTORY_REPLAY_MATCHES,
                HISTORY_REPLAY_ABUNDANCE,
            ],
        },
    )


def _uvp_net_history_replay_messages() -> dict[str, list[BaseMessage]]:
    """Build three checkpoints from the observed correction sequence."""

    match_call = "history-replay-match-call"
    join_call = "history-replay-join-call"
    shared: list[BaseMessage] = [
        HumanMessage(
            content=(
                "Prends l'export EcoTaxa et identifie les profils filet qui "
                "correspondent par station et proximité temporelle."
            ),
            id="history-replay-human-match",
        ),
        AIMessage(
            content="",
            id="history-replay-ai-match",
            tool_calls=[{
                "name": "run_pandas",
                "args": {
                    "code": (
                        f"result = {HISTORY_REPLAY_UVP}.copy()  # "
                        f"persist as {HISTORY_REPLAY_MATCHES}"
                    )
                },
                "id": match_call,
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content="2 correspondances station-temps persistées.",
            name="run_pandas",
            tool_call_id=match_call,
            id="history-replay-tool-match",
            artifact={
                "status": "success",
                "persisted": True,
                "data_ref": HISTORY_REPLAY_MATCHES,
                "summary": "2 correspondances station-temps",
            },
        ),
        AIMessage(
            content=f"Correspondances conservées dans `{HISTORY_REPLAY_MATCHES}`.",
            id="history-replay-ai-match-final",
        ),
        HumanMessage(
            content=(
                "Par station, compare le nombre d'objets Copepoda EcoTaxa et "
                "l'abondance Copepoda filet."
            ),
            id="history-replay-human-compare",
        ),
        AIMessage(
            content="",
            id="history-replay-ai-join",
            tool_calls=[{
                "name": "run_pandas",
                "args": {
                    "code": (
                        f"result = {HISTORY_REPLAY_MATCHES}.merge("
                        f"{HISTORY_REPLAY_ABUNDANCE}, how='left')"
                    )
                },
                "id": join_call,
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=(
                "Jointure persistée mais abondance entièrement absente.\n"
                + "x" * 16_000
            ),
            name="run_pandas",
            tool_call_id=join_call,
            id="history-replay-tool-join",
            artifact={
                "status": "success",
                "persisted": True,
                "data_ref": HISTORY_REPLAY_BAD_JOIN,
                "summary": "2 lignes; abondance Copepoda absente",
            },
        ),
        AIMessage(
            content=(
                f"La jointure `{HISTORY_REPLAY_BAD_JOIN}` ne retrouve aucune "
                "abondance. " + "J" * 8_000
            ),
            id="history-replay-ai-join-final",
        ),
    ]
    no_join = HumanMessage(
        content=(
            "Ne fais pas de jointure : calcule deux tableaux séparés et "
            "présente-les en parallèle."
        ),
        id="history-replay-human-no-join",
    )
    limit_scope = HumanMessage(
        content=(
            "Limite-les bien aux profils et aux stations sur lesquels on travaille."
        ),
        id="history-replay-human-limit",
    )
    make_tables = HumanMessage(
        content="Fais maintenant les deux tableaux.",
        id="history-replay-human-make",
    )
    no_join_history = [*shared, no_join]
    limit_history = [
        *no_join_history,
        AIMessage(
            content="Compris : deux tableaux séparés. " + "S" * 8_000,
            id="history-replay-ai-no-join-final",
        ),
        limit_scope,
    ]
    make_history = [
        *limit_history,
        AIMessage(
            content="Périmètre limité. " + "P" * 8_000,
            id="history-replay-ai-limit-final",
        ),
        make_tables,
    ]
    return {
        "sans jointure": no_join_history,
        "périmètre limité": limit_history,
        "deux tableaux": make_history,
    }


def _campaign_uvp_net_history_replay(
    store: SessionStore,
) -> list[CampaignCheck]:
    """Replay the failed dialogue and inspect only the provider-bound context."""

    scenario = "uvp-net-separate-tables-history-replay"
    thread_id = f"{BASE_THREAD}-uvp-net-history-replay"
    _seed_uvp_net_history_replay(store, thread_id)
    histories = _uvp_net_history_replay_messages()
    captures = {
        label: _capture(
            store,
            thread_id,
            _content_text(messages[-1]),
            f"history-replay-{index}",
            input_messages=messages,
        )
        for index, (label, messages) in enumerate(histories.items(), start=1)
    }
    final = captures["deux tableaux"]
    raw_history = final.messages[1:-1]
    raw_history_text = "\n".join(_content_text(message) for message in raw_history)
    snapshots = {
        label: {
            "history_shape": ">".join(
                f"{message.type}:{len(_content_text(message))}"
                for message in capture.messages
            ),
            "objective": next(
                (
                    line.removeprefix("Objective: ")
                    for line in capture.task_context.splitlines()
                    if line.startswith("Objective: ")
                ),
                "",
            ),
            "details": _detail_names(capture.dataset_context),
            "has_primary": "focus=primary" in capture.dataset_context,
        }
        for label, capture in captures.items()
    }
    all_required_resources = {
        HISTORY_REPLAY_UVP,
        HISTORY_REPLAY_ABUNDANCE,
        HISTORY_REPLAY_MATCHES,
        HISTORY_REPLAY_BAD_JOIN,
    }
    evolution_messages = list(histories["deux tableaux"])
    evolution_captures: list[ModelCapture] = []
    for index, question in enumerate(HISTORY_REPLAY_FOLLOWUPS, start=6):
        evolution_messages.extend([
            AIMessage(
                content="Réponse intermédiaire détaillée. " + "R" * 8_000,
                id=f"history-replay-ai-followup-{index}",
            ),
            HumanMessage(
                content=question,
                id=f"history-replay-human-followup-{index}",
            ),
        ])
        evolution_captures.append(
            _capture(
                store,
                thread_id,
                question,
                f"history-replay-followup-{index}",
                input_messages=evolution_messages,
            )
        )
    evolution = {
        str(index): {
            "objective": next(
                (
                    line.removeprefix("Objective: ")
                    for line in capture.task_context.splitlines()
                    if line.startswith("Objective: ")
                ),
                "",
            ),
            "remembered": [
                label
                for label, text in {
                    "initial": "Prends l'export EcoTaxa",
                    "comparison": "compare le nombre d'objets Copepoda",
                    "no_join": "Ne fais pas de jointure",
                    "scope": "Limite-les bien aux profils",
                }.items()
                if text in capture.task_context
            ],
            "dataframes": len(_detail_names(capture.dataset_context)),
        }
        for index, capture in enumerate(evolution_captures, start=6)
    }
    final_evolution = evolution_captures[-1]
    return [
        _check(
            scenario,
            "continuity",
            "cumulative user instructions survive raw-history collapse",
            len(raw_history) < len(histories["deux tableaux"]) - 1
            and "Prends l'export EcoTaxa" not in raw_history_text
            and "Ne fais pas de jointure" not in raw_history_text
            and "Ne fais pas de jointure" in final.task_context
            and "Limite-les bien aux profils" in final.task_context
            and "Objective: Fais maintenant les deux tableaux." in final.task_context,
            json.dumps(
                {
                    "final": snapshots["deux tableaux"],
                    "raw_messages_retained": len(raw_history),
                    "original_messages_before_current": (
                        len(histories["deux tableaux"]) - 1
                    ),
                    "capsule_has": [
                        "objectif initial",
                        "comparaison",
                        "sans jointure",
                        "périmètre limité",
                    ],
                },
                ensure_ascii=False,
                default=str,
            ),
            turn_range="correction turns 3-5",
        ),
        _check(
            scenario,
            "continuity",
            "previous-turn tool results never remain primary",
            all(
                "focus=primary" not in capture.dataset_context
                for capture in captures.values()
            )
            and all(
                re.search(
                    rf"^- {re.escape(HISTORY_REPLAY_BAD_JOIN)}$\n"
                    rf"  status=.*focus=recent;",
                    capture.dataset_context,
                    re.MULTILINE,
                )
                for capture in captures.values()
            ),
            json.dumps(
                {
                    label: {
                        "has_primary": snapshot["has_primary"],
                        "bad_join_focus": "recent",
                    }
                    for label, snapshot in snapshots.items()
                },
                ensure_ascii=False,
            ),
            turn_range="correction turns 3-5",
        ),
        _check(
            scenario,
            "continuity",
            "matching scope and both independent measure sources stay visible",
            all(
                all_required_resources <= set(_detail_names(capture.dataset_context))
                for capture in captures.values()
            ),
            json.dumps(
                {
                    label: snapshot["details"]
                    for label, snapshot in snapshots.items()
                },
                ensure_ascii=False,
            ),
            turn_range="correction turns 3-5",
        ),
        _check(
            scenario,
            "continuity",
            "critical user instructions survive six short follow-ups",
            "Prends l'export EcoTaxa" in final_evolution.task_context
            and "compare le nombre d'objets Copepoda" in final_evolution.task_context
            and "Ne fais pas de jointure" in final_evolution.task_context
            and "Limite-les bien aux profils" in final_evolution.task_context,
            json.dumps(evolution, ensure_ascii=False),
            turn_range="follow-up turns 6-11",
        ),
        _check(
            scenario,
            "continuity",
            "working dataframes survive six short follow-ups",
            all_required_resources
            <= set(_detail_names(final_evolution.dataset_context)),
            json.dumps(evolution, ensure_ascii=False),
            turn_range="follow-up turns 6-11",
        ),
    ]


def campaign_continuity(store: SessionStore) -> list[CampaignCheck]:
    """Replay the real derived-table disappearance without lexical hints."""

    scenario = "fourteen-dataframe-working-set-continuity"
    thread_id = f"{BASE_THREAD}-continuity"
    expected_names = _seed_context_continuity_dataframes(store, thread_id)
    generic_questions = (
        "Continue avec ce résultat.",
        "ZXQ-17.",
    )
    captures = tuple(
        _capture(
            store,
            thread_id,
            question,
            f"continuity-{index}",
            input_messages=_continuity_history(question),
        )
        for index, question in enumerate(generic_questions, start=1)
    )
    indexes = tuple(_index_names(capture.dataset_context) for capture in captures)
    details = tuple(_detail_names(capture.dataset_context) for capture in captures)
    audit_counts = tuple(_catalog_audit_counts(capture) for capture in captures)
    central_positions = tuple(
        cards.index(CONTINUITY_DERIVED) if CONTINUITY_DERIVED in cards else -1
        for cards in details
    )
    stale_positions = tuple(
        cards.index(CONTINUITY_STALE_ACTIVE)
        if CONTINUITY_STALE_ACTIVE in cards else len(cards)
        for cards in details
    )

    oversized_thread = f"{BASE_THREAD}-oversized-card"
    long_columns = {
        f"sample_{index:02d}_" + ("x" * 1_500): [index]
        for index in range(8)
    }
    store_dataset(
        store,
        oversized_thread,
        pd.DataFrame(long_columns),
        variable_name="df_a_oversized_active_card",
        meta={
            "source": "analysis:derived",
            "description": "Intentionally oversized schema card.",
            "grain": "one row per synthetic sample",
        },
    )
    store_dataset(
        store,
        oversized_thread,
        pd.DataFrame({"sample_id": [1], "value": [2.0]}),
        variable_name="df_z_small_card_after_oversized",
        meta={
            "source": "analysis:derived",
            "description": "Small card that must survive an earlier oversized card.",
            "grain": "one row per sample",
            "primary_key": "sample_id",
        },
        set_active=False,
    )
    oversized = _capture(
        store,
        oversized_thread,
        "Continue.",
        "oversized-card",
    )
    oversized_details = _detail_names(oversized.dataset_context)

    checks = [
        _check(
            scenario,
            "continuity",
            "all fourteen live resources remain indexed on generic follow-ups",
            all(
                len(index) == CONTINUITY_TOTAL
                and set(index) == set(expected_names)
                for index in indexes
            ),
            f"indexed_counts={tuple(map(len, indexes))}",
            turn_range="two generic follow-ups",
        ),
        _check(
            scenario,
            "continuity",
            "the 222-row derived result stays detailed with its 1632-row parent",
            all(
                CONTINUITY_DERIVED in cards and CONTINUITY_RAW in cards
                for cards in details
            )
            and all(
                "rows=222" in capture.dataset_context
                and "rows=1632" in capture.dataset_context
                for capture in captures
            ),
            f"details={details}",
            turn_range="two generic follow-ups",
        ),
        _check(
            scenario,
            "continuity",
            "stale active metadata never outranks the latest successful work result",
            all(
                central >= 0 and central < stale
                for central, stale in zip(
                    central_positions, stale_positions, strict=True
                )
            ),
            f"central_positions={central_positions}; stale_positions={stale_positions}",
            turn_range="two generic follow-ups",
        ),
        _check(
            scenario,
            "continuity",
            "catalog accounting is exact and mutually exclusive",
            all(
                counts == (
                    CONTINUITY_TOTAL,
                    CONTINUITY_EXPANDED,
                    CONTINUITY_INDEX_ONLY,
                )
                for counts in audit_counts
            )
            and all(
                len(index) == len(cards) + CONTINUITY_INDEX_ONLY
                and set(cards) <= set(index)
                for index, cards in zip(indexes, details, strict=True)
            ),
            f"audit_counts={audit_counts}; expanded={tuple(map(len, details))}",
            turn_range="two generic follow-ups",
        ),
        _check(
            scenario,
            "continuity",
            "resource focus is invariant to unrelated lexical content",
            len(details) == 2
            and details[0] == details[1]
            and CONTINUITY_DERIVED not in " ".join(generic_questions)
            and CONTINUITY_RAW not in " ".join(generic_questions),
            f"questions={generic_questions}; details_equal={details[0] == details[1]}",
            turn_range="two generic follow-ups",
            violated_contract="working-set selection must use factual references, not lexical ranking",
        ),
        _check(
            "oversized-card-packing",
            "continuity",
            "one oversized card cannot block later selected cards",
            "df_z_small_card_after_oversized" in oversized_details,
            f"expanded={oversized_details}; chars={len(oversized.dataset_context)}",
        ),
    ]
    checks.extend(_campaign_uvp_net_history_replay(store))
    return checks


def _current_tool_turn_messages(question: str) -> list[BaseMessage]:
    return [
        HumanMessage(content=question, id="cache-human-tool-turn"),
        AIMessage(
            content="",
            id="cache-ai-tool-turn",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df_single_sample.copy()"},
                "id": "cache-tool-call",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content="status=success; persisted=true; data_ref=df_single_sample",
            name="run_pandas",
            tool_call_id="cache-tool-call",
            id="cache-tool-result",
            artifact={
                "status": "success",
                "persisted": True,
                "data_ref": "df_single_sample",
            },
        ),
    ]


def _capture_cache_enabled_request(
    store: SessionStore,
    thread_id: str,
    question: str,
    message_id: str,
    *,
    input_messages: Sequence[BaseMessage] | None = None,
) -> ModelCapture:
    """Capture the real middleware with its explicit cache breakpoint enabled."""

    spy = _SpyChatModel(responses=[AIMessage(content="cache capture complete")])
    with patch("tools.session_store.default_store", store):
        catalog = build_tool_catalog(thread_id)
        graph = create_agent(
            spy,
            list(catalog.tools),
            system_prompt=agent_module._SYSTEM_PROMPT,
            middleware=[
                ModelCallLimitMiddleware(
                    run_limit=agent_module._MAX_MODEL_CALLS_PER_TURN,
                    exit_behavior="end",
                ),
                ExplorationStateMiddleware(thread_id=thread_id),
                agent_module._ContextMiddleware(
                    user_id="context-cache-harness",
                    thread_id=thread_id,
                    catalog_names=catalog.names,
                    prompt_cache_enabled=True,
                ),
            ],
            state_schema=IdeaAgentState,
            store=InMemoryStore(),
        )
        graph_input: dict[str, Any] = {
            "messages": list(input_messages)
            if input_messages is not None
            else [HumanMessage(content=question, id=message_id)]
        }
        result = graph.invoke(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
        )
    return ModelCapture(
        system=str(spy.capture.get("system") or ""),
        messages=tuple(spy.capture.get("messages") or ()),
        tool_names=tuple(spy.capture.get("tool_names") or ()),
        tool_choice=spy.capture.get("tool_choice"),
        audit=agent_module.get_context_audit(thread_id),
        state_messages=tuple(result.get("messages") or ()),
        tool_definitions=tuple(spy.capture.get("tool_definitions") or ()),
    )


def campaign_cache(store: SessionStore) -> list[CampaignCheck]:
    """Verify the stable cache prefix and the variable suffix independently."""

    scenario = "three-call-cache-and-suffix-accounting"
    thread_id = f"{BASE_THREAD}-cache"
    _seed_one_dataframe(store, thread_id)
    first_question = "Prépare le tableau disponible."
    tool_question = "Affiche maintenant le résultat."
    final_question = "Continue."
    first = _capture_cache_enabled_request(
        store, thread_id, first_question, "cache-turn-1"
    )
    tool_turn_messages = _current_tool_turn_messages(tool_question)
    tool_turn = _capture_cache_enabled_request(
        store,
        thread_id,
        tool_question,
        "cache-turn-2",
        input_messages=tool_turn_messages,
    )
    final_history = [
        *tool_turn_messages,
        AIMessage(content="Résultat affiché.", id="cache-ai-final"),
        HumanMessage(content=final_question, id="cache-human-final"),
    ]
    return _finish_cache_campaign(
        store=store,
        thread_id=thread_id,
        final_question=final_question,
        final_history=final_history,
        first=first,
        tool_turn=tool_turn,
        scenario=scenario,
    )


def _budget_tool_exchange(
    index: int,
    tool_name: str,
    *,
    data_ref: str | None = None,
) -> tuple[AIMessage, ToolMessage]:
    """Build one successful structural tool exchange for the cost campaign."""

    call_id = f"budget-call-{index}"
    artifact: dict[str, Any] = {
        "status": "success",
        "persisted": bool(data_ref),
        "rows": 12,
    }
    if data_ref:
        artifact["data_ref"] = data_ref
    return (
        AIMessage(
            content="",
            id=f"budget-ai-{index}",
            tool_calls=[{
                "name": tool_name,
                "args": {"campaign_probe": index},
                "id": call_id,
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=f"status=success; tool={tool_name}; rows=12",
            name=tool_name,
            tool_call_id=call_id,
            id=f"budget-tool-{index}",
            status="success",
            artifact=artifact,
        ),
    )


def campaign_budget(store: SessionStore) -> list[CampaignCheck]:
    """Verify the live five-call and run_pandas cost contract offline."""

    scenario = "five-model-call-two-pandas-budget"
    thread_id = f"{BASE_THREAD}-budget"
    _seed_one_dataframe(store, thread_id)
    question = "Produis le résultat demandé à partir des données disponibles."
    first = _capture(store, thread_id, question, "budget-first")

    history: list[BaseMessage] = [
        HumanMessage(content=question, id="budget-human"),
    ]
    for exchange in (
        _budget_tool_exchange(
            1,
            "query_ecotaxa_cache",
            data_ref="df_ecotaxa_cache_result_budget",
        ),
        _budget_tool_exchange(
            2,
            "run_pandas",
            data_ref="df_derived_budget_qualification",
        ),
        _budget_tool_exchange(
            3,
            "run_pandas",
            data_ref="df_derived_budget_result",
        ),
    ):
        history.extend(exchange)
    fourth = _capture(
        store,
        thread_id,
        question,
        "budget-fourth",
        input_messages=history,
    )

    history.extend(
        _budget_tool_exchange(4, "run_graph")
    )
    fifth = _capture(
        store,
        thread_id,
        question,
        "budget-fifth",
        input_messages=history,
    )

    first_audit = first.audit
    fourth_audit = fourth.audit
    fifth_audit = fifth.audit
    return [
        _check(
            scenario,
            "budget",
            "permanent prompt defines an economical five-call target and two run_pandas calls",
            "within about five model calls" in first.system
            and "at most two `run_pandas` calls" in first.system,
            "system cost contract present",
            turn_range="permanent system",
        ),
        _check(
            scenario,
            "budget",
            "first provider call receives the live budget",
            first_audit.get("model_call_number_current_turn") == 1
            and first_audit.get("target_model_calls_per_turn") == 5
            and first_audit.get("max_model_calls_per_turn") == 10
            and first_audit.get("target_run_pandas_calls_per_turn") == 2
            and "Model call: 1; economy target" in first.runtime_context,
            str({
                "call": first_audit.get("model_call_number_current_turn"),
                "max": first_audit.get("max_model_calls_per_turn"),
                "pandas_target": first_audit.get(
                    "target_run_pandas_calls_per_turn"
                ),
            }),
            turn_range="model call 1",
        ),
        _check(
            scenario,
            "budget",
            "two actual run_pandas results spend the normal budget",
            fourth_audit.get("model_call_number_current_turn") == 4
            and fourth_audit.get("run_pandas_attempts_current_turn") == 2
            and fourth_audit.get("run_pandas_successes_current_turn") == 2
            and "normal run_pandas budget is already spent"
            in fourth.runtime_context,
            str({
                "call": fourth_audit.get("model_call_number_current_turn"),
                "pandas_attempts": fourth_audit.get(
                    "run_pandas_attempts_current_turn"
                ),
                "pandas_successes": fourth_audit.get(
                    "run_pandas_successes_current_turn"
                ),
            }),
            turn_range="model call 4",
        ),
        _check(
            scenario,
            "budget",
            "fifth call strongly signals economy without disabling tools",
            fifth_audit.get("model_call_number_current_turn") == 5
            and fifth_audit.get("economy_target_reached") is True
            and fifth.tool_choice != "none"
            and "ECONOMY TARGET REACHED" in fifth.runtime_context,
            str({
                "call": fifth_audit.get("model_call_number_current_turn"),
                "economy_target_reached": fifth_audit.get("economy_target_reached"),
                "tool_choice": fifth.tool_choice,
            }),
            turn_range="model call 5",
        ),
        _check(
            scenario,
            "budget",
            "budget remains variable suffix context and does not alter cache prefix",
            "execution_budget"
            in (fifth_audit.get("dynamic_context_tokens_by_block") or {})
            and fifth_audit.get("cacheable_prefix_tokens")
            == first_audit.get("cacheable_prefix_tokens"),
            "execution_budget is separately metered; prefix token count is stable",
            turn_range="model calls 1–5",
        ),
    ]


def _finish_cache_campaign(
    *,
    store: SessionStore,
    thread_id: str,
    final_question: str,
    final_history: Sequence[BaseMessage],
    first: ModelCapture,
    tool_turn: ModelCapture,
    scenario: str,
) -> list[CampaignCheck]:
    """Complete cache assertions after building the three provider requests."""

    final = _capture_cache_enabled_request(
        store,
        thread_id,
        final_question,
        "cache-turn-3",
        input_messages=final_history,
    )
    captures = (first, tool_turn, final)
    audits = tuple(capture.audit for capture in captures)
    prefix_tokens = tuple(
        int(audit.get("cacheable_prefix_tokens") or 0) for audit in audits
    )
    block_tokens = tuple(
        audit.get("dynamic_context_tokens_by_block") for audit in audits
    )
    current_tool_tokens = tuple(
        int(audit.get("current_turn_tool_tokens") or 0) for audit in audits
    )
    cache_keys = tuple(
        str(audit.get("prompt_cache_contract_key") or "") for audit in audits
    )

    def projected_ledger_tokens(capture: ModelCapture) -> dict[str, int]:
        return {
            str(item.get("name")): int(item.get("projected_tokens") or 0)
            for item in capture.context_ledger
        }

    return [
        _check(
            scenario,
            "cache",
            "cacheable prefix is exactly the breakpointed permanent system",
            all(value > 0 for value in prefix_tokens)
            and all(
                value == int(audit.get("approx_tokens_base_system") or 0)
                for value, audit in zip(prefix_tokens, audits, strict=True)
            ),
            f"prefix_tokens={prefix_tokens}; base_system="
            f"{tuple(audit.get('approx_tokens_base_system') for audit in audits)}",
            turn_range="three provider calls",
        ),
        _check(
            scenario,
            "cache",
            "cache prefix and versioned contract key stay stable across suffix changes",
            len(set(prefix_tokens)) == 1
            and len(set(cache_keys)) == 1
            and bool(cache_keys[0])
            and len({capture.system for capture in captures}) == 1,
            f"prefixes={prefix_tokens}; distinct_keys={len(set(cache_keys))}",
            turn_range="three provider calls",
        ),
        _check(
            scenario,
            "cache",
            "dynamic suffix tokens are reported for every projected block",
            all(isinstance(item, dict) and item for item in block_tokens)
            and all(
                all(
                    int(item.get(name) or 0) == tokens
                    for name, tokens in projected_ledger_tokens(capture).items()
                )
                and set(item) <= {
                    *projected_ledger_tokens(capture),
                    "__wrapper_and_separators__",
                }
                and sum(int(value or 0) for value in item.values())
                == int(capture.audit.get("dynamic_context_tokens") or 0)
                for item, capture in zip(block_tokens, captures, strict=True)
                if isinstance(item, dict)
            ),
            f"block_tokens={block_tokens}",
            turn_range="three provider calls",
        ),
        _check(
            scenario,
            "cache",
            "current-turn tool tokens are isolated from history and cacheable prefix",
            current_tool_tokens[0] == 0
            and current_tool_tokens[1] > 0
            and current_tool_tokens[2] == 0
            and prefix_tokens[0] == prefix_tokens[1] == prefix_tokens[2],
            f"current_tool_tokens={current_tool_tokens}; prefixes={prefix_tokens}",
            turn_range="plain turn, tool continuation, following turn",
        ),
        _check(
            scenario,
            "cache",
            "variable suffix accounting fits inside every estimated request",
            all(
                prefix + sum(int(value or 0) for value in blocks.values())
                + current_tool
                <= int(audit.get("approx_tokens_model_request") or 0)
                for prefix, blocks, current_tool, audit in zip(
                    prefix_tokens,
                    block_tokens,
                    current_tool_tokens,
                    audits,
                    strict=True,
                )
                if isinstance(blocks, dict)
            ),
            "prefix + projected blocks + current tool turn <= request on all calls",
            turn_range="three provider calls",
        ),
    ]


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
        if contains_graph_fact:
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
        audit = snapshot.capture.audit
        ledger = snapshot.capture.context_ledger
        ledger_names = tuple(item.get("name") for item in ledger)
        projection_tokens = int(audit.get("context_projection_tokens") or 0)
        projection_budget = int(
            audit.get("context_projection_budget_tokens") or 0
        )
        request_tokens = int(audit.get("approx_tokens_model_request") or 0)
        request_budget = int(audit.get("max_context_tokens") or 0)
        if (
            dataframe_chars > 12_000
            or frontier_chars > 4_500
            or projection_tokens > projection_budget
            or request_tokens > request_budget
            or len(ledger_names) != len(set(ledger_names))
        ):
            budget_violation = (
                turn,
                f"dataset_chars={dataframe_chars}; frontier_chars={frontier_chars}; "
                f"projection={projection_tokens}/{projection_budget}; "
                f"request={request_tokens}/{request_budget}; ledger={ledger_names}",
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
            "irrelevant last graph facts stay out of later turns",
            graph_violation,
            success_evidence="turns 4-50 omit graph facts when no graph is referenced",
        ),
        check(
            "pending frontier persists before resolving on turn 25",
            frontier_violation,
            success_evidence="turns 20-24 pending; turn 25 has Data dependencies: []",
        ),
        check(
            "structured projection and complete request remain within budget",
            budget_violation,
            success_evidence=(
                "all 50 calls have unique ledger entries, bounded blocks and a "
                "complete request under MAX_CONTEXT_TOKENS"
            ),
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
    tool_search_active = bool(
        captures[0].audit.get("openai_tool_search_enabled")
    )
    namespace_names = {
        "ecotaxa",
        "ecopart",
        "geography",
        "environmental_enrichment",
        "deliverable",
    }
    provider_builtin_names = namespace_names | {"tool_search"}
    valid_provider_names = catalog_names | (
        provider_builtin_names if tool_search_active else set()
    )

    def namespace_members(capture: ModelCapture, namespace_name: str) -> set[str]:
        for definition in capture.tool_definitions:
            if not isinstance(definition, dict):
                continue
            if definition.get("type") != "namespace":
                continue
            if definition.get("name") != namespace_name:
                continue
            return {
                str(member.get("name") or "")
                for member in definition.get("tools") or []
                if isinstance(member, dict)
            }
        return set()

    def declared_function_names(capture: ModelCapture) -> set[str]:
        names = set(capture.tool_names) & catalog_names
        for namespace_name in namespace_names:
            names.update(namespace_members(capture, namespace_name))
        return names

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
        and set(capture.tool_names) <= valid_provider_names
        and declared_function_names(capture) <= catalog_names,
        lambda capture: (
            f"count={len(capture.tool_names)}; "
            f"unique={len(set(capture.tool_names))}; "
            f"unknown={sorted(set(capture.tool_names) - valid_provider_names)}"
        ),
    )
    hidden_violation = first_call_violation(
        lambda capture: not (declared_function_names(capture) & hidden_legacy)
        and "load_skill" not in declared_function_names(capture),
        lambda capture: (
            "forbidden="
            f"{sorted((declared_function_names(capture) & hidden_legacy) | ({'load_skill'} & declared_function_names(capture)))}"
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

    ecotaxa_cache_expected = {
        "query_ecotaxa_cache",
        "list_ecotaxa_cache_tables",
        "describe_ecotaxa_cache_table",
    }
    ecotaxa_namespace_expected = {
        "query_ecotaxa",
        "export_ecotaxa_samples",
        *ecotaxa_cache_expected,
    }
    ecotaxa_names = (
        namespace_members(captures[1], "ecotaxa")
        if tool_search_active else set(captures[1].tool_names)
    )
    ecopart_names = (
        namespace_members(captures[3], "ecopart")
        if tool_search_active else set(captures[3].tool_names)
    )
    bio_names = (
        namespace_members(captures[4], "environmental_enrichment")
        if tool_search_active else set(captures[4].tool_names)
    )
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
            (index, sorted(declared_function_names(capture) & hidden_legacy))
            for index, capture in enumerate(react_calls, start=1)
            if declared_function_names(capture) & hidden_legacy
            or "load_skill" in declared_function_names(capture)
        ),
        None,
    )
    react_integrity = next(
        (
            (
                index,
                f"count={len(capture.tool_names)}; "
                f"unique={len(set(capture.tool_names))}; "
                f"unknown={sorted(set(capture.tool_names) - valid_provider_names)}",
            )
            for index, capture in enumerate(react_calls, start=1)
            if not capture.tool_names
            or len(capture.tool_names) != len(set(capture.tool_names))
            or not set(capture.tool_names) <= valid_provider_names
            or not declared_function_names(capture) <= catalog_names
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
    turn_one_captures = tuple(
        capture for capture in react_calls if capture.turn == 1
    )
    shortest_turn_one_surface = set(
        min(turn_one_lists, key=len) if turn_one_lists else ()
    )
    expected_recovery_lifts = {
        "list_ecotaxa_cache_tables",
        "describe_ecotaxa_cache_table",
        "query_ecotaxa_cache",
    }
    recovery_lifts_are_bounded = bool(turn_one_captures) and all(
        set(capture.tool_names) - shortest_turn_one_surface
        <= expected_recovery_lifts
        and not (
            (set(capture.tool_names) & catalog_names)
            & set().union(*(
                namespace_members(capture, namespace_name)
                for namespace_name in namespace_names
            ))
        )
        for capture in turn_one_captures
    )
    from core.llm_config import openai_prompt_cache_key

    react_contract_keys = {
        openai_prompt_cache_key(
            model=os.getenv("LLM_MODEL", "gpt-5.6-luna"),
            system_prompt=capture.system,
            tools=capture.tool_definitions,
        )
        for capture in react_calls
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
            "every provider surface is unique and catalog or OpenAI backed",
            integrity_violation is None,
            "all functions are catalog-backed; namespaces and Tool Search are OpenAI built-ins"
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
            "EcoTaxa exposes only its canonical route for the active strategy",
            (
                ecotaxa_namespace_expected == ecotaxa_names
                if tool_search_active
                else ecotaxa_cache_expected <= ecotaxa_names
            )
            and not (ecotaxa_names & hidden_legacy),
            f"ecotaxa_members={sorted(ecotaxa_names)}",
            turn_range="turn 2",
        ),
        _check(
            scenario,
            "tools",
            "EcoPart namespace contains enrichment and preflight capabilities",
            {
                "enrich_ecotaxa_with_ecopart_remote",
                "find_ecopart_project_for_ecotaxa",
                "preview_ecopart_sample",
            } <= ecopart_names,
            f"ecopart_members={sorted(ecopart_names)}",
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
            "environmental namespace includes canonical Bio-ORACLE enrichment",
            "enrich_with_bio_oracle" in bio_names
            and {"run_pandas", "run_graph"} <= set(captures[4].tool_names),
            f"environmental_members={sorted(bio_names)}",
            turn_range="turn 5",
        ),
        _check(
            scenario,
            "tools",
            "provider route either defers namespaces or exposes the full canonical catalog",
            (
                "enrich_with_bio_oracle" not in after_bio_names
                and "enrich_with_bio_oracle" not in graph_names
                and all(
                    "environmental_enrichment" in capture.tool_names
                    for capture in captures
                )
                if tool_search_active
                else all(set(capture.tool_names) == catalog_names for capture in captures)
            ),
            f"turn_6={sorted(after_bio_names)}; turn_7={sorted(graph_names)}",
            turn_range="turns 6-7",
        ),
        _check(
            scenario,
            "tools",
            "provider surface stays cache-stable across turns",
            len(distinct_lists) == 1,
            f"distinct_provider_tool_lists={len(distinct_lists)}",
            turn_range="turns 1-7",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "every ReAct provider call keeps a valid searchable tool surface",
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
            "same-turn recovery preserves the exact provider tool surface",
            (
                len({capture.tool_names for capture in react_calls}) == 1
                if tool_search_active
                else len(turn_one_lists) == 1
            ),
            f"turn_1_provider_calls={sum(capture.turn == 1 for capture in react_calls)}; "
            f"distinct_tool_lists={len(turn_one_lists)}; "
            f"surfaces={sorted(turn_one_lists)}",
            turn_range="turn 1",
        ),
        _check(
            "three-turn-react-tool-exposure",
            "tools",
            "cache contract fingerprint is stable across turns and ReAct recovery",
            len(react_contract_keys) == 1 and "" not in react_contract_keys,
            f"distinct_cache_contracts={len(react_contract_keys)}; "
            f"keys={sorted(react_contract_keys)}",
            turn_range="7 provider calls across 3 turns",
        ),
    ]


def campaign_memory(store: SessionStore) -> list[CampaignCheck]:
    """Validate that durable user memories are no longer read by the runtime."""

    scenario = "long-term-memory-disabled"
    thread_id = f"{BASE_THREAD}-memory"
    user_id = "memory-user"
    memory_store = InMemoryStore()
    relevant = "LONG_TERM_MEMORY_MUST_NOT_APPEAR"
    memory_store.put(
        ("memories", user_id),
        "relevant",
        {"kind": "preference", "content": {"content": relevant}},
    )
    memory_store.put(
        (user_id, "memories"),
        "legacy-reversed",
        {"content": "REVERSED_NAMESPACE_MUST_NOT_APPEAR"},
    )
    memory_store.put(
        ("memories", "other-user"),
        "private",
        {"content": {"content": "OTHER_USER_MEMORY_MUST_NOT_APPEAR"}},
    )
    catalog = build_tool_catalog(thread_id)
    spy = _SpyChatModel(responses=[AIMessage(content="Réponse hors ligne.")])
    graph = create_agent(
        spy,
        list(catalog.tools),
        system_prompt=agent_module._SYSTEM_PROMPT,
        middleware=[
            ExplorationStateMiddleware(thread_id=thread_id),
            agent_module._ContextMiddleware(
                user_id=user_id,
                thread_id=thread_id,
                catalog_names=catalog.names,
            ),
        ],
        state_schema=IdeaAgentState,
        store=memory_store,
    )
    with patch("tools.session_store.default_store", store):
        graph.invoke({
            "messages": [HumanMessage(
                content="Crée un graphique avec un titre en français.",
                id="memory-current-user",
            )]
        })
    capture = replace(
        _capture_from_model_call(spy.calls[-1]),
        audit=agent_module.get_context_audit(thread_id),
    )
    runtime = capture.runtime_context
    memory_ledger = next(
        (item for item in capture.context_ledger if item.get("name") == "memory"),
        {},
    )
    return [
        _check(
            scenario,
            "memory",
            "durable user memory is not injected into provider context",
            relevant not in runtime
            and int(capture.audit.get("memories_found") or 0) == 0
            and int(capture.audit.get("memories_selected") or 0) == 0,
            f"memories_found={capture.audit.get('memories_found')}; "
            f"selected={capture.audit.get('memories_selected')}",
        ),
        _check(
            scenario,
            "memory",
            "all user-memory namespaces are ignored",
            "REVERSED_NAMESPACE_MUST_NOT_APPEAR" not in runtime
            and "OTHER_USER_MEMORY_MUST_NOT_APPEAR" not in runtime,
            "no durable-memory marker in provider context",
        ),
        _check(
            scenario,
            "memory",
            "context ledger has no long-term-memory block",
            not memory_ledger
            and not capture.audit.get("memory_injected")
            and int(capture.audit.get("memory_chars") or 0) == 0,
            f"ledger={memory_ledger}; memory_chars={capture.audit.get('memory_chars')}",
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
        ("df_thread_a_private", "THREAD_A_ONLY"),
        ("df_thread_b_private", "THREAD_B_ONLY", "GRAPH_A_ONLY", "GRAPH_B_ONLY"),
    )
    leak_b = first_leak(
        snapshots_b,
        ("df_thread_b_private", "THREAD_B_ONLY"),
        ("df_thread_a_private", "THREAD_A_ONLY", "GRAPH_A_ONLY", "GRAPH_B_ONLY"),
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
            "thread A exposes only its relevant private context",
            leak_a,
            "A private markers present; B markers absent on all provider calls",
        ),
        isolation_check(
            "thread B exposes only its relevant private context",
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
    "continuity": campaign_continuity,
    "cache": campaign_cache,
    "budget": campaign_budget,
    "frontier": campaign_frontier,
    "graph": campaign_graph,
    "history": campaign_history,
    "tools": campaign_tools,
    "memory": campaign_memory,
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
