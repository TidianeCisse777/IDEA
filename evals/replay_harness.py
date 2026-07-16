"""Harness de replay local et live pour les trajectoires IDEA.

La piste offline est déterministe et adaptée à la CI. La piste live importe le
runtime uniquement après avoir isolé le store et coupé le tracing.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, ToolMessage

from tools.tool_result import success, validate_tool_artifact

Lane = Literal["offline", "live"]
ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = Path(__file__).with_name("scenarios") / "harness_reference.json"
FILE_TOOLS = frozenset({"load_file", "run_pandas", "run_graph", "filter_dataframe_by_zone"})
_ISOLATED_ENV = (
    "SESSION_STORE_DIR",
    "SESSION_STORE_DATABASE_URL",
    "CHECKPOINTS_DB",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY",
)


@dataclass(frozen=True)
class ScenarioTurn:
    name: str
    prompt: str
    expected_source: str
    expected_dataset_source_contains: str | None
    expected_dataset_source_family: str | None
    expect_file_use: bool
    forbidden_tools: tuple[str, ...]
    offline: dict[str, Any]


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    turns: tuple[ScenarioTurn, ...]


@dataclass(frozen=True)
class ReplayIsolation:
    root: Path
    session_store_dir: Path
    checkpoints_db: Path
    artifacts_dir: Path


class ToolExposureCapture(BaseCallbackHandler):
    """Capture les noms de tools réellement transmis à chaque appel modèle."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.calls: list[list[str]] = []

    def reset(self) -> None:
        self.names = []
        self.calls = []

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:  # noqa: ANN001
        invocation = kwargs.get("invocation_params") or {}
        raw_tools = invocation.get("tools") or kwargs.get("tools") or []
        discovered: list[str] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function") or {}
            name = function.get("name") if isinstance(function, dict) else None
            name = name or item.get("name")
            if name:
                discovered.append(str(name))
        current = list(dict.fromkeys(discovered))
        self.calls.append(current)
        self.names = list(dict.fromkeys((*self.names, *current)))


def load_reference_scenarios(path: Path = REFERENCE_PATH) -> dict[str, Scenario]:
    """Charge les scénarios versionnés et refuse les IDs dupliqués."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios: dict[str, Scenario] = {}
    for raw in payload["scenarios"]:
        scenario = Scenario(
            id=str(raw["id"]),
            description=str(raw["description"]),
            turns=tuple(
                ScenarioTurn(
                    name=str(turn["name"]),
                    prompt=str(turn["prompt"]),
                    expected_source=str(turn["expected_source"]),
                    expected_dataset_source_contains=(
                        str(turn["expected_dataset_source_contains"])
                        if turn.get("expected_dataset_source_contains")
                        else None
                    ),
                    expected_dataset_source_family=(
                        str(turn["expected_dataset_source_family"])
                        if turn.get("expected_dataset_source_family")
                        else None
                    ),
                    expect_file_use=bool(turn.get("expect_file_use", False)),
                    forbidden_tools=tuple(turn.get("forbidden_tools", ())),
                    offline=dict(turn["offline"]),
                )
                for turn in raw["turns"]
            ),
        )
        if scenario.id in scenarios:
            raise ValueError(f"Duplicate scenario id: {scenario.id}")
        scenarios[scenario.id] = scenario
    return scenarios


def _source_family(source: object) -> str:
    normalized = str(source or "").strip().lower().replace("-", "_")
    if normalized == "file" or normalized.startswith(("file:", "filter_by_zone", "local_", "uploaded_")):
        return "file"
    if normalized.startswith("bio_oracle"):
        return "bio_oracle"
    for family in ("ecotaxa", "ecopart", "amundsen", "ogsl", "sql"):
        if normalized.startswith(family):
            return family
    return normalized or "none"


def _tool_source_family(name: object) -> str | None:
    normalized = str(name or "").lower()
    if normalized in FILE_TOOLS:
        return "file"
    for family in ("bio_oracle", "ecotaxa", "ecopart", "amundsen", "ogsl", "sql"):
        if family in normalized:
            return family
    return None


def grade_turn(
    *,
    expected_source: str,
    forbidden_tools: tuple[str, ...],
    tool_calls: list[dict[str, Any]],
    dataset_after: dict[str, Any] | None,
    expected_dataset_source_contains: str | None = None,
    expected_dataset_source_family: str | None = None,
) -> dict[str, Any]:
    """Grade les invariants de visibilité/exécution et la trajectoire source."""
    names = [str(call.get("name") or "") for call in tool_calls]
    forbidden_called = sorted(set(names).intersection(forbidden_tools))
    raw_dataset_source = str((dataset_after or {}).get("source") or "")
    actual_source = _source_family(raw_dataset_source)
    tool_sources = {
        family
        for call in tool_calls
        for family in (_tool_source_family(call.get("name")),)
        if family is not None
    }
    source_matches = expected_source in ({actual_source} | tool_sources)
    dataset_matches = (
        (expected_dataset_source_contains is None
         or expected_dataset_source_contains.lower() in raw_dataset_source.lower())
        and (expected_dataset_source_family is None
             or actual_source == expected_dataset_source_family)
    )
    return {
        "level_1_passed": not forbidden_called,
        "level_2_passed": not forbidden_called and source_matches and dataset_matches,
        "forbidden_tools_called": forbidden_called,
        "expected_source": expected_source,
        "actual_source": actual_source,
        "tool_sources": sorted(tool_sources),
        "source_matches": source_matches,
        "dataset_matches": dataset_matches,
        "expected_dataset_source_contains": expected_dataset_source_contains,
        "expected_dataset_source_family": expected_dataset_source_family,
    }


def structured_tool_observation(message: ToolMessage) -> dict[str, Any]:
    """Read the machine outcome exclusively from ``ToolMessage.artifact``."""
    result = validate_tool_artifact(message.artifact)
    return {
        "status": result.status,
        "result": result.model_dump(mode="json"),
        "result_preview": str(message.content)[:1000],
    }


def _offline_tool_call(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize scripted calls to the same result contract as live calls."""
    call = copy.deepcopy(raw)
    artifact = call.get("result")
    if artifact is None:
        _, artifact = success(
            f"Résultat scripté offline : {call.get('name') or 'tool'}.",
            provenance={"source": "offline scripted fixture"},
            method="deterministic replay fixture",
        )
    result = validate_tool_artifact(artifact)
    call["result"] = result.model_dump(mode="json")
    call["status"] = result.status
    return call


def validate_run_count(lane: Lane, runs: int) -> None:
    if lane == "live" and runs < 5:
        raise ValueError("Le benchmark live exige au moins 5 runs par scénario")
    if runs < 1:
        raise ValueError("Le nombre de runs doit être positif")


@contextmanager
def isolated_replay_environment(base_dir: Path) -> Iterator[ReplayIsolation]:
    """Isole les écritures du replay et restaure exactement l'environnement."""
    root = Path(base_dir).resolve() / f"idea-replay-{uuid.uuid4().hex}"
    session_store_dir = root / "session_store"
    artifacts_dir = root / "artifacts"
    checkpoints_db = root / "checkpoints.sqlite"
    session_store_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)
    previous = {name: os.environ.get(name) for name in _ISOLATED_ENV}
    os.environ.update({
        "SESSION_STORE_DIR": str(session_store_dir),
        "SESSION_STORE_DATABASE_URL": "",
        "CHECKPOINTS_DB": str(checkpoints_db),
        "LANGCHAIN_TRACING_V2": "false",
        "LANGCHAIN_API_KEY": "",
        "LANGSMITH_API_KEY": "",
    })
    try:
        yield ReplayIsolation(root, session_store_dir, checkpoints_db, artifacts_dir)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@lru_cache(maxsize=1)
def _fixed_request_snapshot() -> dict[str, Any]:
    """Mesure le prompt et le catalogue actuels sans appeler de modèle."""
    from langchain_core.messages import SystemMessage

    from agent import _SYSTEM_PROMPT, _approx_tokens, _tool_schema_tokens
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("replay-offline-catalog")
    system_tokens = _approx_tokens([SystemMessage(content=_SYSTEM_PROMPT)])
    schema_tokens = _tool_schema_tokens(catalog.tools)
    return {
        "catalog_tools": sorted(catalog.names),
        "tools_by_name": {tool.name: tool for tool in catalog.tools},
        "system_prompt_tokens": system_tokens,
        "tool_schema_tokens": schema_tokens,
        "fixed_tokens": system_tokens + schema_tokens,
    }


def _turn_record(
    turn: ScenarioTurn,
    fixed: dict[str, Any],
    *,
    file_loaded: bool,
) -> dict[str, Any]:
    from agent import _tool_schema_tokens
    from tools.source_scope import SourceDecision
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure
    from tools.turn_context import TurnContext

    observation = copy.deepcopy(turn.offline)
    calls = [
        _offline_tool_call(call)
        for call in observation.get("tool_calls", [])
    ]
    dataset_after = observation.get("dataset_after")
    expected = turn.expected_source
    authorized = (
        ("file",)
        if expected == "file"
        else (("file", expected) if file_loaded else (expected,))
    )
    source_decision = SourceDecision(
        primary_source="file" if file_loaded else expected,
        authorized_sources=authorized,
        explicit_sources=tuple(source for source in authorized if source != "file"),
        evidence="explicit_name" if expected != "file" else "loaded_file_default",
        needs_clarification=False,
        reason="deterministic offline reference",
    )
    turn_context = TurnContext(
        thread_id="offline-reference",
        file_loaded=file_loaded,
        active_variable="df_file_reference" if file_loaded else None,
        active_source="file:offline-reference" if file_loaded else None,
        derived_zone_subsets=(),
        authorized_sources=authorized,
        primary_source=source_decision.primary_source,
        explicit_sources=source_decision.explicit_sources,
        capsule="",
    )
    exposure = decide_tool_exposure(
        tuple(fixed["catalog_tools"]),
        TOOL_POLICIES,
        turn_context,
        source_decision,
        [HumanMessage(content=turn.prompt)],
    )
    exposed_tools = [
        fixed["tools_by_name"][name]
        for name in exposure.tool_names
        if name in fixed["tools_by_name"]
    ]
    schema_tokens_after = _tool_schema_tokens(exposed_tools)
    return {
        "name": turn.name,
        "prompt": turn.prompt,
        "tools_exposed": list(exposure.tool_names),
        "tool_exposure_calls": [list(exposure.tool_names)],
        "tool_calls": calls,
        "dataset_after": dataset_after,
        "refused": str(observation.get("final_answer", "")).lower().startswith("refus"),
        "final_answer": str(observation.get("final_answer", "")),
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": None},
        "context": {
            "system_prompt_tokens": fixed["system_prompt_tokens"],
            "tool_schema_tokens": schema_tokens_after,
            "fixed_tokens": fixed["system_prompt_tokens"] + schema_tokens_after,
            "tool_exposure_count": len(exposure.tool_names),
            "tool_exposure_alert": len(exposure.tool_names) >= 12,
            "tool_exposure_groups": list(exposure.active_groups),
            "tool_exposure_reasons": list(exposure.reasons),
            "policy_overflow": exposure.policy_overflow,
            "approx_tokens_tool_schemas_before": fixed["tool_schema_tokens"],
            "approx_tokens_tool_schemas_after": schema_tokens_after,
            "approx_tokens_tool_schemas_saved": max(
                0, fixed["tool_schema_tokens"] - schema_tokens_after
            ),
        },
        "grade": grade_turn(
            expected_source=turn.expected_source,
            forbidden_tools=turn.forbidden_tools,
            tool_calls=calls,
            dataset_after=dataset_after,
            expected_dataset_source_contains=turn.expected_dataset_source_contains,
            expected_dataset_source_family=turn.expected_dataset_source_family,
        ),
        "expects_file_use": turn.expect_file_use,
        "file_used": any(call.get("name") in FILE_TOOLS for call in calls),
    }


def _aggregate_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [turn for run in runs for turn in run["turns"]]
    lab_expected = [
        turn for run in runs if run["scenario_id"] == "SC-LAB"
        for turn in run["turns"] if turn["expects_file_use"]
    ]
    lab_good = [
        turn for turn in lab_expected
        if (
            turn["file_used"]
            and turn["grade"]["actual_source"] == "file"
            and turn["grade"].get("dataset_matches", True)
        )
    ]
    count = max(1, len(turns))
    costs = [
        float(turn.get("usage", {}).get("cost_usd"))
        for turn in turns
        if turn.get("usage", {}).get("cost_usd") is not None
    ]
    exposure_calls = [
        call
        for turn in turns
        for call in turn.get("tool_exposure_calls", [])
    ]
    return {
        "scenario_runs": len(runs),
        "turns": len(turns),
        "level_1_pass_rate": sum(t["grade"]["level_1_passed"] for t in turns) / count,
        "level_2_pass_rate": sum(t["grade"]["level_2_passed"] for t in turns) / count,
        "sc_lab_good_file_rate": len(lab_good) / max(1, len(lab_expected)),
        "mean_tools_per_turn": sum(len(t["tool_calls"]) for t in turns) / count,
        "mean_tools_exposed_per_turn": sum(len(t["tools_exposed"]) for t in turns) / count,
        "max_tools_exposed_per_model_call": max(
            (len(call) for call in exposure_calls),
            default=0,
        ),
        "fixed_tokens": max(
            (turn.get("context", {}).get("fixed_tokens", 0) for turn in turns),
            default=0,
        ),
        "input_tokens": sum(int(turn.get("usage", {}).get("input_tokens", 0) or 0) for turn in turns),
        "output_tokens": sum(int(turn.get("usage", {}).get("output_tokens", 0) or 0) for turn in turns),
        "cost_usd": sum(costs) if costs else None,
    }


def _rubric() -> dict[str, Any]:
    return {
        "level_1": {
            "automated": True,
            "criteria": ["aucun tool interdit exécuté", "aucune dépendance externe en offline"],
        },
        "level_2": {
            "automated": True,
            "criteria": ["source attendue utilisée", "trajectoire et densité de tools capturées"],
        },
        "level_3": {
            "automated": False,
            "criteria": [
                "exactitude scientifique des tableaux et métriques",
                "provenance complète",
                "absence d'interprétation non demandée",
                "ton clinique et concision",
            ],
            "calibration": "grader LLM avec revue humaine périodique; à implémenter après l'étape 0",
        },
    }


def build_offline_report(*, runs: int = 1) -> dict[str, Any]:
    """Construit la référence déterministe à partir des scénarios versionnés."""
    validate_run_count("offline", runs)
    scenarios = load_reference_scenarios()
    fixed = _fixed_request_snapshot()
    records: list[dict[str, Any]] = []
    for scenario in scenarios.values():
        for run_index in range(runs):
            file_loaded = False
            turn_records = []
            for turn in scenario.turns:
                turn_records.append(
                    _turn_record(turn, fixed, file_loaded=file_loaded)
                )
                file_loaded = file_loaded or any(
                    call.get("name") == "load_file"
                    for call in turn.offline.get("tool_calls", [])
                )
            records.append({
                "scenario_id": scenario.id,
                "run_id": f"offline-{scenario.id.lower()}-{run_index + 1}",
                "turns": turn_records,
            })
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lane": "offline",
        "model": "scripted-reference",
        "external_dependencies": [],
        "runtime_configuration": {
            "tool_count": len(fixed["catalog_tools"]),
            "max_tools_per_model_call": 15,
            "sql_tools_exposed": False,
            "observations": "scripted fixtures; dynamic per-turn tool policy and schemas measured from current code",
        },
        "run_count_per_scenario": runs,
        "scenarios": records,
        "metrics": _aggregate_metrics(records),
        "rubric": _rubric(),
    }


def _live_turn_record(turn: ScenarioTurn, observation: dict[str, Any]) -> dict[str, Any]:
    calls = list(observation.get("tool_calls", []))
    dataset_after = observation.get("dataset_after")
    answer = str(observation.get("final_answer", ""))
    tools_exposed = sorted(set(observation.get("tools_exposed", [])))
    return {
        "name": turn.name,
        "prompt": turn.prompt,
        "tools_exposed": tools_exposed,
        "tool_exposure_calls": list(observation.get("tool_exposure_calls") or []),
        "tool_exposure_capture_complete": bool(observation.get("tool_exposure_capture_complete", True)),
        "tool_calls": calls,
        "dataset_after": dataset_after,
        "refused": bool(observation.get("refused", answer.lower().startswith("refus"))),
        "final_answer": answer,
        "usage": dict(observation.get("usage") or {}),
        "context": dict(observation.get("context") or {}),
        "grade": grade_turn(
            expected_source=turn.expected_source,
            forbidden_tools=turn.forbidden_tools,
            tool_calls=calls,
            dataset_after=dataset_after,
            expected_dataset_source_contains=turn.expected_dataset_source_contains,
            expected_dataset_source_family=turn.expected_dataset_source_family,
        ),
        "expects_file_use": turn.expect_file_use,
        "file_used": any(call.get("name") in FILE_TOOLS for call in calls),
    }


def build_live_report(
    *,
    runs: int,
    executor: Any | None = None,
    scenarios: dict[str, Scenario] | None = None,
    allow_external_sources: bool = False,
    progress: Callable[[str], None] | None = None,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    """Exécute la piste live; l'exécuteur injectable garde les tests offline."""
    validate_run_count("live", runs)
    selected = scenarios or load_reference_scenarios()
    if executor is None:
        if not allow_external_sources:
            raise ValueError("Le live des trois scénarios exige l'autorisation des sources externes")
        executor = LangGraphLiveExecutor()
    model = str(getattr(executor, "model", "unknown"))
    dependencies = list(getattr(executor, "external_dependencies", []))
    records: list[dict[str, Any]] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    if checkpoint_path and checkpoint_path.exists():
        previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if previous.get("lane") != "live" or previous.get("run_count_per_scenario") != runs:
            raise ValueError("Checkpoint live incompatible avec ce benchmark")
        if previous.get("model") != model:
            raise ValueError("Checkpoint live produit avec un autre modèle")
        records = list(previous.get("scenarios") or [])
        generated_at = str(previous.get("generated_at") or generated_at)
    completed = {
        (str(record.get("scenario_id")), int(record.get("run_index", -1)))
        for record in records
    }

    def current_report(status: str) -> dict[str, Any]:
        exposed = (
            records[0]["turns"][0]["tools_exposed"]
            if records and records[0]["turns"]
            else []
        )
        return {
            "schema_version": "1.0",
            "generated_at": generated_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "lane": "live",
            "model": model,
            "external_dependencies": dependencies,
            "runtime_configuration": {
                "tool_count": len(exposed),
                "max_tools_per_model_call": 15,
                "sql_tools_exposed": any(name.startswith(("list_sql", "preview_sql", "copy_sql")) for name in exposed),
                "observations": "real model trajectory; source adapters listed as external dependencies",
            },
            "run_count_per_scenario": runs,
            "completed_scenario_runs": len(records),
            "target_scenario_runs": len(selected) * runs,
            "scenarios": records,
            "metrics": _aggregate_metrics(records),
            "rubric": _rubric(),
        }

    if checkpoint_path:
        write_report(current_report("in_progress"), checkpoint_path)
    for scenario in selected.values():
        for run_index in range(runs):
            if (scenario.id, run_index) in completed:
                if progress:
                    progress(f"{scenario.id} — run {run_index + 1}/{runs} déjà sauvegardé")
                continue
            if progress:
                progress(f"{scenario.id} — run {run_index + 1}/{runs}")
            run_context = executor.start_run(scenario, run_index)
            turn_records = []
            for turn in scenario.turns:
                if progress:
                    progress(f"{scenario.id} — run {run_index + 1}/{runs} — {turn.name}")
                turn_records.append(
                    _live_turn_record(turn, executor.run_turn(run_context, turn))
                )
            records.append({
                "scenario_id": scenario.id,
                "run_index": run_index,
                "run_id": f"live-{scenario.id.lower()}-{uuid.uuid4().hex}",
                "turns": turn_records,
            })
            completed.add((scenario.id, run_index))
            if checkpoint_path:
                write_report(current_report("in_progress"), checkpoint_path)
    report = current_report("complete")
    if checkpoint_path:
        write_report(report, checkpoint_path)
    return report


class LangGraphLiveExecutor:
    """Adaptateur du vrai agent, sans changement dans `agent.py`."""

    external_dependencies = ["LLM provider", "EcoTaxa", "Amundsen CTD", "Bio-ORACLE"]

    def __init__(self) -> None:
        # Imports tardifs : SESSION_STORE_DIR et tracing doivent être isolés avant.
        import agent as agent_module
        from tools.session_store import default_store
        from tools.tool_catalog import build_tool_catalog

        self._agent_module = agent_module
        self._store = default_store
        self._catalog_names = sorted(build_tool_catalog("replay-live-catalog").names)
        self.model = os.getenv("LLM_MODEL", "gpt-5.4-mini")

    def start_run(self, scenario: Scenario, run_index: int) -> dict[str, Any]:
        thread_id = f"replay-{scenario.id.lower()}-{uuid.uuid4().hex}"
        user_id = f"replay-user-{uuid.uuid4().hex}"
        capture = ToolExposureCapture()
        graph = self._agent_module.make_agent(thread_id, user_id=user_id)
        return {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent": graph,
            "capture": capture,
            "config": {
                "configurable": {"thread_id": thread_id},
                "metadata": {"user_id": user_id, "eval": "replay-harness", "scenario": scenario.id},
                "callbacks": [capture],
                "recursion_limit": 40,
            },
        }

    @staticmethod
    def _usage(messages: list[Any]) -> dict[str, Any]:
        input_tokens = 0
        output_tokens = 0
        cost = 0.0
        cost_seen = False
        for message in messages:
            usage = getattr(message, "usage_metadata", None) or {}
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            response = getattr(message, "response_metadata", None) or {}
            for key in ("cost_usd", "total_cost"):
                if response.get(key) is not None:
                    cost += float(response[key])
                    cost_seen = True
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost if cost_seen else None,
        }

    @staticmethod
    def _inferred_source(calls: list[dict[str, Any]]) -> str | None:
        for call in reversed(calls):
            name = str(call.get("name") or "").lower()
            for family in ("bio_oracle", "amundsen", "ecopart", "ecotaxa", "ogsl", "sql"):
                if family in name:
                    return f"{family}_tool_result"
            if name in FILE_TOOLS:
                return "file_tool_result"
        return None

    def _dataset_snapshot(self, thread_id: str, calls: list[dict[str, Any]]) -> dict[str, Any] | None:
        entry = self._store.get(thread_id) or {}
        dataframe = entry.get("df")
        meta = dict(entry.get("meta") or {})
        source = meta.get("source") or self._inferred_source(calls)
        if not source and dataframe is None:
            return None
        return {
            "source": source,
            "variable_name": meta.get("variable_name"),
            "rows": len(dataframe) if dataframe is not None else None,
            "columns": list(map(str, dataframe.columns)) if dataframe is not None else [],
        }

    def run_turn(self, run_context: dict[str, Any], turn: ScenarioTurn) -> dict[str, Any]:
        from langchain_core.messages import AIMessage, ToolMessage

        graph = run_context["agent"]
        config = run_context["config"]
        capture: ToolExposureCapture = run_context["capture"]
        self._agent_module.repair_invalid_tool_history(graph, config)
        snapshot = graph.get_state(config)
        existing = list((getattr(snapshot, "values", {}) or {}).get("messages") or [])
        seen = len(existing)
        capture.reset()
        new_messages: list[Any] = []
        for state in graph.stream(
            {"messages": [{"role": "user", "content": turn.prompt}]},
            config=config,
            stream_mode="values",
        ):
            messages = list(state.get("messages") or [])
            if len(messages) > seen:
                new_messages.extend(messages[seen:])
                seen = len(messages)

        calls: list[dict[str, Any]] = []
        calls_by_id: dict[str, dict[str, Any]] = {}
        final_answer = ""
        for message in new_messages:
            if isinstance(message, AIMessage):
                if getattr(message, "content", None):
                    final_answer = str(message.content)
                for raw in getattr(message, "tool_calls", None) or []:
                    call = {
                        "name": str(raw.get("name") or ""),
                        "arguments": dict(raw.get("args") or {}),
                        "status": None,
                        "result": None,
                        "result_preview": None,
                    }
                    calls.append(call)
                    if raw.get("id"):
                        calls_by_id[str(raw["id"])] = call
            elif isinstance(message, ToolMessage):
                call = calls_by_id.get(str(message.tool_call_id))
                if call is not None:
                    call.update(structured_tool_observation(message))

        exposed = capture.names or self._catalog_names
        audit = self._agent_module.get_context_audit(run_context["thread_id"])
        context = {
            "system_prompt_tokens": audit.get("approx_tokens_base_system", 0),
            "tool_schema_tokens": audit.get("approx_tokens_tool_schemas", 0),
            "fixed_tokens": (
                audit.get("approx_tokens_base_system", 0)
                + audit.get("approx_tokens_tool_schemas", 0)
            ),
            "approx_tokens_model_request": audit.get("approx_tokens_model_request", 0),
            "tool_exposure_count": audit.get("tool_exposure_count", 0),
            "tool_exposure_alert": bool(audit.get("tool_exposure_alert", False)),
            "tool_exposure_groups": list(audit.get("tool_exposure_groups") or []),
            "tool_exposure_reasons": list(audit.get("tool_exposure_reasons") or []),
            "policy_overflow": bool(audit.get("policy_overflow", False)),
            "approx_tokens_tool_schemas_before": audit.get(
                "approx_tokens_tool_schemas_before", 0
            ),
            "approx_tokens_tool_schemas_after": audit.get(
                "approx_tokens_tool_schemas_after", 0
            ),
            "approx_tokens_tool_schemas_saved": audit.get(
                "approx_tokens_tool_schemas_saved", 0
            ),
        }
        return {
            "tools_exposed": exposed,
            "tool_exposure_calls": list(capture.calls),
            "tool_exposure_capture_complete": bool(capture.names),
            "tool_calls": calls,
            "dataset_after": self._dataset_snapshot(run_context["thread_id"], calls),
            "final_answer": final_answer,
            "refused": final_answer.strip().lower().startswith(("refus", "impossible")),
            "usage": self._usage(new_messages),
            "context": context,
        }


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Retire uniquement les champs non déterministes d'un rapport."""
    normalized = copy.deepcopy(report)
    normalized.pop("generated_at", None)
    for run in normalized.get("scenarios", []):
        if str(run.get("run_id", "")).startswith("live-"):
            run["run_id"] = "live-normalized"
    return normalized


def regrade_report(
    report: dict[str, Any],
    scenarios: dict[str, Scenario] | None = None,
) -> dict[str, Any]:
    """Recalcule les graders depuis les observations sauvegardées, sans LLM."""
    updated = copy.deepcopy(report)
    reference = scenarios or load_reference_scenarios()
    for run in updated.get("scenarios", []):
        scenario = reference.get(str(run.get("scenario_id")))
        if scenario is None:
            continue
        turns_by_name = {turn.name: turn for turn in scenario.turns}
        for observed in run.get("turns", []):
            expected = turns_by_name.get(str(observed.get("name")))
            if expected is None:
                continue
            calls = list(observed.get("tool_calls") or [])
            observed["grade"] = grade_turn(
                expected_source=expected.expected_source,
                expected_dataset_source_contains=expected.expected_dataset_source_contains,
                expected_dataset_source_family=expected.expected_dataset_source_family,
                forbidden_tools=expected.forbidden_tools,
                tool_calls=calls,
                dataset_after=observed.get("dataset_after"),
            )
            observed["expects_file_use"] = expected.expect_file_use
            observed["file_used"] = any(call.get("name") in FILE_TOOLS for call in calls)
            observed.setdefault("tools_exposed", [])
            observed.setdefault("context", {})
    updated["metrics"] = _aggregate_metrics(list(updated.get("scenarios") or []))
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    return updated


def serialize_report(report: dict[str, Any]) -> str:
    """Sérialise le schéma public; aucun environnement n'est inclus."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialize_report(report), encoding="utf-8")
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("offline", "live"), default="offline")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-external-sources",
        action="store_true",
        help="Autorise les intégrations réelles pour SC-ENRICH et SC-ECOTAXA.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        validate_run_count(args.lane, args.runs)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    default_name = (
        f"baseline_live_{datetime.now():%Y-%m-%d}.json"
        if args.lane == "live"
        else "baseline_offline_2026-07-15.json"
    )
    output = (args.output or ROOT / "evals" / default_name).resolve()
    with tempfile.TemporaryDirectory(prefix="idea-replay-") as tmp:
        with isolated_replay_environment(Path(tmp)):
            if args.lane == "live":
                from dotenv import load_dotenv

                load_dotenv(ROOT / ".env", override=False)
                if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")):
                    raise SystemExit("Clé OpenRouter/OpenAI absente; benchmark live non exécuté.")
                report = build_live_report(
                    runs=args.runs,
                    allow_external_sources=args.allow_external_sources,
                    progress=lambda message: print(message, flush=True),
                    checkpoint_path=output,
                )
            else:
                report = build_offline_report(runs=args.runs)
    write_report(report, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
