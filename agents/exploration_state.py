"""Checkpointed working state for adaptive data exploration.

The graph stores plain JSON-compatible dictionaries. Pydantic models define
and validate the contract at the boundary. Middleware owns planning updates;
data-producing tools can atomically merge compact resource metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, NotRequired

from langchain.agents import AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field

ExplorationCapability = Literal[
    "ground_method",
    "inspect_resources",
    "retrieve_data",
    "filter_data",
    "join_data",
    "compute_metric",
    "validate_data",
    "summarize_data",
    "compare_data",
    "visualize_data",
    "export_deliverable",
]
ExplorationStatus = Literal[
    "unplanned",
    "running",
    "waiting_confirmation",
    "complete",
    "failed",
]
StepStatus = Literal[
    "pending",
    "running",
    "complete",
    "failed",
    "blocked",
    "superseded",
]


def merge_exploration_state(
    current: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replace normal state updates; merge concurrent resource patches.

    Data-producing tools publish only JSON-safe resource metadata. The real
    DataFrames remain in ``SessionStore`` and never enter the checkpoint.
    """
    if not update:
        return dict(current or {})
    patch = update.get("__resource_patch__")
    if patch is None:
        return dict(update)
    merged = dict(current or {})
    resources = {
        str(item.get("resource_id")): item
        for item in merged.get("resources_available", [])
        if isinstance(item, dict) and item.get("resource_id")
    }
    for item in patch:
        if isinstance(item, dict) and item.get("resource_id"):
            resources[str(item["resource_id"])] = item
    merged["resources_available"] = list(resources.values())
    return merged


class IdeaAgentState(AgentState):
    """LangGraph state persisted by the configured checkpointer."""

    exploration: NotRequired[
        Annotated[dict[str, Any], merge_exploration_state]
    ]


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExplorationDeliverable(_StateModel):
    kind: Literal["answer", "table", "visualization", "file"]
    description: str
    required: bool = True


class ResourceColumnProfile(_StateModel):
    """Compact schema facts inferred from a currently available table."""

    name: str
    dtype: str
    missing_count: int = 0
    missing_fraction: float = 0.0
    distinct_sample: int | None = None
    semantic_role: Literal[
        "identifier",
        "time",
        "latitude",
        "longitude",
        "depth",
        "measure",
        "category",
        "text",
        "unknown",
    ] = "unknown"
    key_likelihood: Literal["none", "identifier", "sampled_unique", "declared"] = "none"


class ResourceJoinCandidate(_StateModel):
    """Sample-based relationship between two tables, never a certified join."""

    target_resource_id: str
    target_name: str
    columns: tuple[str, ...]
    left_coverage: float | None = None
    right_coverage: float | None = None
    confidence: Literal["name_only", "sampled", "declared"] = "name_only"


class ResourceRecord(_StateModel):
    resource_id: str
    kind: Literal["table", "selection", "external_source", "knowledge_base"]
    name: str
    source: str
    persisted: bool
    rows: int | None = None
    description: str | None = None
    columns: tuple[str, ...] = ()
    columns_truncated: bool = False
    grain: str | None = None
    identifiers: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    column_profiles: tuple[ResourceColumnProfile, ...] = ()
    key_candidates: tuple[str, ...] = ()
    join_candidates: tuple[ResourceJoinCandidate, ...] = ()
    freshness: str | None = None
    age_turns: int | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    capabilities: tuple[ExplorationCapability, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExplorationDependency(_StateModel):
    dependency_id: str
    step_id: str
    depends_on_step_id: str | None = None
    kind: Literal["step", "data"] = "step"
    status: Literal["pending", "satisfied", "blocked"] = "pending"
    description: str = ""
    resource_kind: Literal["table", "column"] | None = None
    resource_name: str | None = None
    canonical_name: str | None = None
    source_hint: str | None = None
    candidate_resources: tuple[str, ...] = ()
    diagnostic: str = ""
    resume_required: bool = False


class ExplorationStep(_StateModel):
    step_id: str
    capability: ExplorationCapability
    instruction: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    origin: Literal["planned", "observed"] = "observed"
    plan_position: int | None = None
    depends_on: tuple[str, ...] = ()
    expected_resources: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ("successful_status",)
    status: StepStatus = "pending"
    attempts: int = 0
    observation_refs: tuple[str, ...] = ()


class EvidenceValidation(_StateModel):
    check: str
    passed: bool
    detail: str = ""


class EvidenceRecord(_StateModel):
    evidence_id: str
    step_id: str
    tool_name: str
    tool_call_id: str
    status: str
    summary: str
    data_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    persisted: bool = False
    validation_results: tuple[EvidenceValidation, ...] = ()


class ExplorationCompletion(_StateModel):
    model_finalized: bool = False
    evidence_count: int = 0
    completed_step_count: int = 0
    failed_step_count: int = 0
    note: str = ""


class ExplorationRun(_StateModel):
    schema_version: Literal["exploration_run_v1"] = "exploration_run_v1"
    run_id: str
    request_fingerprint: str
    objective: str
    deliverables: tuple[ExplorationDeliverable, ...]
    resources_available: tuple[ResourceRecord, ...] = ()
    steps: tuple[ExplorationStep, ...] = ()
    dependencies: tuple[ExplorationDependency, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    active_step_id: str | None = None
    status: ExplorationStatus = "unplanned"
    completion: ExplorationCompletion = Field(default_factory=ExplorationCompletion)
    processed_tool_call_ids: tuple[str, ...] = ()
    processed_tool_message_ids: tuple[str, ...] = ()
    processed_plan_message_ids: tuple[str, ...] = ()
    plan_revision: int = 0
    forced_dependency_continuations: int = 0
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        return "\n".join(chunks).strip()
    return str(content or "").strip()


def latest_user_objective(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _current_turn_messages(messages: list[Any]) -> list[Any]:
    last_human_index = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, HumanMessage)
        ),
        default=-1,
    )
    return messages[last_human_index:] if last_human_index >= 0 else messages


def request_fingerprint(objective: str) -> str:
    normalized = " ".join(objective.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def default_deliverables(objective: str) -> tuple[ExplorationDeliverable, ...]:
    """Start with an answer only; never infer intent from words in user prose."""
    return (
        ExplorationDeliverable(
            kind="answer",
            description=objective or "Répondre à la demande",
        ),
    )


def new_exploration_run(
    objective: str,
    resources: tuple[ResourceRecord, ...],
) -> dict[str, Any]:
    now = _now()
    run = ExplorationRun(
        run_id=f"explore-{uuid.uuid4().hex}",
        request_fingerprint=request_fingerprint(objective),
        objective=objective,
        deliverables=default_deliverables(objective),
        resources_available=resources,
        status="running",
        created_at=now,
        updated_at=now,
    )
    return run.model_dump(mode="json")


def validate_exploration_run(payload: object) -> ExplorationRun | None:
    if not isinstance(payload, dict):
        return None
    try:
        return ExplorationRun.model_validate(payload)
    except Exception:
        return None


_CAPABILITY_BY_TOOL: dict[str, ExplorationCapability] = {
    "load_file": "retrieve_data",
    "run_pandas": "compute_metric",
    "run_graph": "visualize_data",
    "query_copepod_knowledge_base": "ground_method",
    "lookup_marine_taxonomy": "retrieve_data",
    "export_deliverable": "export_deliverable",
    "list_ecotaxa_cache_tables": "inspect_resources",
    "describe_ecotaxa_cache_table": "inspect_resources",
    "query_ecotaxa_cache": "retrieve_data",
    "query_ecotaxa": "retrieve_data",
    "export_ecotaxa_samples": "retrieve_data",
    "preview_ecopart_sample": "inspect_resources",
    "find_ecopart_project_for_ecotaxa": "inspect_resources",
    "enrich_ecotaxa_with_ecopart_remote": "join_data",
    "query_amundsen_profiles_for_table": "retrieve_data",
    "find_amundsen_data_for_table": "inspect_resources",
    "enrich_with_amundsen_ctd": "join_data",
    "enrich_with_bio_oracle": "join_data",
    "enrich_with_ogsl": "join_data",
    "get_zone_info": "inspect_resources",
    "filter_dataframe_by_zone": "filter_data",
    "split_dataframe_by_zone": "filter_data",
    "list_sql_tables": "inspect_resources",
    "preview_sql_table": "inspect_resources",
    "copy_sql_query_to_workspace": "retrieve_data",
}


def capability_for_tool(tool_name: str) -> ExplorationCapability:
    """Classify only an exact executed tool name; never inspect user prose."""
    return _CAPABILITY_BY_TOOL.get(tool_name, "validate_data")


def _expected_evidence(tool_name: str) -> tuple[str, ...]:
    if tool_name in {"run_graph", "export_deliverable"}:
        return ("successful_status", "artifact_ref")
    return ("successful_status",)


def register_tool_steps(payload: object, messages: list[Any]) -> dict[str, Any] | None:
    run = validate_exploration_run(payload)
    if run is None:
        return None
    current_turn = _current_turn_messages(messages)
    latest_ai = next(
        (message for message in reversed(current_turn) if isinstance(message, AIMessage)),
        None,
    )
    if latest_ai is None:
        return run.model_dump(mode="json")
    processed = set(run.processed_tool_call_ids)
    new_calls = [
        call for call in (getattr(latest_ai, "tool_calls", None) or [])
        if str(call.get("id") or "") not in processed
    ]
    if not new_calls:
        return run.model_dump(mode="json")

    steps = list(run.steps)
    dependencies = list(run.dependencies)
    parent_step_id = run.active_step_id
    active_step_id = parent_step_id
    for call in new_calls:
        call_id = str(call.get("id") or uuid.uuid4().hex)
        tool_name = str(call.get("name") or "unknown")
        capability = capability_for_tool(tool_name)
        step_id = f"step-{call_id}"
        parent = next(
            (item for item in steps if item.step_id == parent_step_id),
            None,
        )
        depends_on = (
            (parent_step_id,)
            if parent_step_id and parent is not None and parent.status == "complete"
            else ()
        )
        steps.append(
            ExplorationStep(
                step_id=step_id,
                capability=capability,
                instruction=f"Exécuter l’action analytique {tool_name}",
                tool_name=tool_name,
                tool_call_id=call_id,
                depends_on=depends_on,
                expected_evidence=_expected_evidence(tool_name),
                status="running",
                attempts=1,
            )
        )
        if depends_on:
            dependency_status = (
                "satisfied"
                if parent is not None and parent.status == "complete"
                else "blocked"
                if parent is not None and parent.status in {"failed", "blocked"}
                else "pending"
            )
            dependencies.append(
                ExplorationDependency(
                    dependency_id=f"dep-{parent_step_id}-{step_id}",
                    step_id=step_id,
                    depends_on_step_id=parent_step_id,
                    status=dependency_status,
                    description="Cette action utilise le résultat de l’étape précédente.",
                )
            )
        processed.add(call_id)
        active_step_id = step_id

    updated = run.model_copy(
        update={
            "steps": tuple(steps),
            "dependencies": tuple(dependencies),
            "active_step_id": active_step_id,
            "processed_tool_call_ids": tuple(sorted(processed)),
            "status": "running",
            "updated_at": _now(),
        }
    )
    return updated.model_dump(mode="json")


def _validation_results(
    expected: tuple[str, ...],
    *,
    status: str,
    artifact_refs: tuple[str, ...],
) -> tuple[EvidenceValidation, ...]:
    results: list[EvidenceValidation] = []
    for check in expected:
        if check == "successful_status":
            passed = status == "success"
            detail = status
        elif check == "artifact_ref":
            passed = bool(artifact_refs)
            detail = f"{len(artifact_refs)} artefact(s)"
        else:
            passed = False
            detail = "Validation inconnue"
        results.append(EvidenceValidation(check=check, passed=passed, detail=detail))
    return tuple(results)


def _next_active_step(steps: list[ExplorationStep]) -> ExplorationStep | None:
    return next(
        (step for step in reversed(steps) if step.status == "running"),
        None,
    )


def ingest_tool_evidence(payload: object, messages: list[Any]) -> dict[str, Any] | None:
    run = validate_exploration_run(payload)
    if run is None:
        return None
    processed = set(run.processed_tool_message_ids)
    steps = list(run.steps)
    evidence = list(run.evidence)
    dependencies = list(run.dependencies)

    for message in _current_turn_messages(messages):
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(message.tool_call_id or "")
        message_key = str(getattr(message, "id", None) or f"tool:{call_id}:{message.name}")
        if message_key in processed:
            continue
        step_index = next(
            (index for index, step in enumerate(steps) if step.tool_call_id == call_id),
            None,
        )
        if step_index is None:
            processed.add(message_key)
            continue
        step = steps[step_index]
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        status = str(artifact.get("status") or getattr(message, "status", None) or "unknown")
        artifact_refs = tuple(str(item) for item in artifact.get("artifact_refs") or ())
        validations = _validation_results(
            step.expected_evidence,
            status=status,
            artifact_refs=artifact_refs,
        )
        evidence_id = f"evidence-{call_id}"
        evidence.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                step_id=step.step_id,
                tool_name=str(message.name or step.tool_name or "unknown"),
                tool_call_id=call_id,
                status=status,
                summary=str(artifact.get("summary") or message.content or "")[:2_000],
                data_ref=(str(artifact["data_ref"]) if artifact.get("data_ref") else None),
                artifact_refs=artifact_refs,
                provenance=dict(artifact.get("provenance") or {}),
                metrics=dict(artifact.get("metrics") or {}),
                persisted=bool(artifact.get("persisted", False)),
                validation_results=validations,
            )
        )
        metrics = dict(artifact.get("metrics") or {})
        requirement = metrics.get("dependency_requirement")
        if metrics.get("dependency_recovery") is True and isinstance(requirement, dict):
            dependency_id = f"data-dependency-{call_id}"
            if not any(item.dependency_id == dependency_id for item in dependencies):
                candidates = tuple(
                    str(item)
                    for item in requirement.get("candidate_resources") or ()
                    if item
                )
                dependencies.append(
                    ExplorationDependency(
                        dependency_id=dependency_id,
                        step_id=step.step_id,
                        kind="data",
                        status="satisfied" if candidates else "pending",
                        description=str(
                            requirement.get("description")
                            or "Une ressource de données manque pour reprendre cette étape."
                        ),
                        resource_kind=(
                            str(requirement.get("kind"))
                            if requirement.get("kind") in {"table", "column"}
                            else None
                        ),
                        resource_name=(
                            str(requirement.get("name"))
                            if requirement.get("name")
                            else None
                        ),
                        canonical_name=(
                            str(requirement.get("canonical_name"))
                            if requirement.get("canonical_name")
                            else None
                        ),
                        source_hint=(
                            str(requirement.get("source_hint"))
                            if requirement.get("source_hint")
                            else None
                        ),
                        candidate_resources=candidates,
                        diagnostic=str(requirement.get("diagnostic") or message.content or "")[:2_000],
                        resume_required=bool(candidates),
                    )
                )
        checks_passed = all(item.passed for item in validations)
        if status in {"blocked", "cancelled"}:
            step_status: StepStatus = "blocked"
        elif status == "error" or not checks_passed:
            step_status = "failed"
        else:
            step_status = "complete"
        steps[step_index] = step.model_copy(
            update={
                "status": step_status,
                "observation_refs": (*step.observation_refs, evidence_id),
            }
        )
        for index, dependency in enumerate(dependencies):
            if dependency.depends_on_step_id == step.step_id:
                dependencies[index] = dependency.model_copy(
                    update={"status": "satisfied" if step_status == "complete" else "blocked"}
                )
        processed.add(message_key)

    active_step = _next_active_step(steps)
    updated = run.model_copy(
        update={
            "steps": tuple(steps),
            "dependencies": tuple(dependencies),
            "evidence": tuple(evidence),
            "active_step_id": active_step.step_id if active_step else None,
            # Tool completion never decides that the user's request is done.
            # Only a tool-free final model response closes the exploration.
            "status": "running",
            "processed_tool_message_ids": tuple(sorted(processed)),
            "updated_at": _now(),
        }
    )
    return updated.model_dump(mode="json")


def reconcile_data_dependencies(payload: object) -> dict[str, Any] | None:
    """Resolve data requirements from the current inventory and later evidence."""
    run = validate_exploration_run(payload)
    if run is None:
        return None
    step_indexes = {step.step_id: index for index, step in enumerate(run.steps)}
    dependencies: list[ExplorationDependency] = []
    for dependency in run.dependencies:
        if dependency.kind != "data":
            dependencies.append(dependency)
            continue
        origin_index = step_indexes.get(dependency.step_id, -1)
        origin_step = next(
            (step for step in run.steps if step.step_id == dependency.step_id),
            None,
        )
        resumed_origin_succeeded = bool(
            origin_step is not None
            and origin_step.status == "complete"
            and origin_step.attempts > 1
        )
        later_compute_succeeded = any(
            index > origin_index
            and step.capability == "compute_metric"
            and step.status == "complete"
            for index, step in enumerate(run.steps)
        )
        if resumed_origin_succeeded or later_compute_succeeded:
            dependencies.append(
                dependency.model_copy(
                    update={"status": "satisfied", "resume_required": False}
                )
            )
            continue

        requested_names = {
            value.casefold()
            for value in (dependency.resource_name, dependency.canonical_name)
            if value
        }
        candidates = list(dependency.candidate_resources)
        for resource in run.resources_available:
            if dependency.resource_kind == "column":
                if any(str(column).casefold() in requested_names for column in resource.columns):
                    candidates.append(resource.name)
            elif dependency.resource_kind == "table":
                resource_names = {
                    resource.name.casefold(),
                    resource.resource_id.casefold(),
                }
                if requested_names & resource_names:
                    candidates.append(resource.name)
        if dependency.resource_kind == "table" and not candidates:
            later_step_ids = {
                step.step_id
                for index, step in enumerate(run.steps)
                if index > origin_index
                and step.capability == "retrieve_data"
                and step.status == "complete"
            }
            candidates.extend(
                item.data_ref
                for item in run.evidence
                if item.step_id in later_step_ids and item.data_ref
            )
        candidates = list(dict.fromkeys(candidates))
        status = "satisfied" if candidates else dependency.status
        dependencies.append(
            dependency.model_copy(
                update={
                    "status": status,
                    "candidate_resources": tuple(candidates),
                    "resume_required": bool(candidates),
                }
            )
        )
    return run.model_copy(
        update={"dependencies": tuple(dependencies), "updated_at": _now()}
    ).model_dump(mode="json")


def active_data_dependencies(payload: object) -> tuple[ExplorationDependency, ...]:
    run = validate_exploration_run(payload)
    if run is None:
        return ()
    return tuple(
        dependency
        for dependency in run.dependencies
        if dependency.kind == "data"
        and (dependency.status == "pending" or dependency.resume_required)
    )


def recovery_tool_names(payload: object) -> tuple[str, ...]:
    """Return safe capability choices; source policy remains the final guard."""
    dependencies = active_data_dependencies(payload)
    if not dependencies:
        return ()
    names = ["run_pandas"]
    sources = {item.source_hint for item in dependencies if item.source_hint}
    if "ecotaxa" in sources:
        names.extend(
            (
                "list_ecotaxa_cache_tables",
                "describe_ecotaxa_cache_table",
                "query_ecotaxa_cache",
            )
        )
    if "sql" in sources:
        names.extend(("list_sql_tables", "preview_sql_table", "copy_sql_query_to_workspace"))
    if "ecopart" in sources:
        names.extend(("find_ecopart_project_for_ecotaxa", "preview_ecopart_sample"))
    if "amundsen" in sources:
        names.extend(("find_amundsen_data_for_table", "enrich_with_amundsen_ctd"))
    if "bio_oracle" in sources:
        names.append("enrich_with_bio_oracle")
    if "ogsl" in sources:
        names.append("enrich_with_ogsl")
    return tuple(dict.fromkeys(names))


def increment_forced_dependency_continuation(payload: object) -> dict[str, Any] | None:
    run = validate_exploration_run(payload)
    if run is None:
        return None
    return run.model_copy(
        update={
            "forced_dependency_continuations": run.forced_dependency_continuations + 1,
            "status": "running",
            "updated_at": _now(),
        }
    ).model_dump(mode="json")


def refresh_exploration_resources(
    payload: object,
    resources: tuple[ResourceRecord, ...],
) -> dict[str, Any] | None:
    run = validate_exploration_run(payload)
    if run is None:
        return None
    return run.model_copy(
        update={"resources_available": resources, "updated_at": _now()}
    ).model_dump(mode="json")


def finish_exploration_run(payload: object, messages: list[Any]) -> dict[str, Any] | None:
    run = validate_exploration_run(payload)
    if run is None:
        return None
    latest_ai = next(
        (message for message in reversed(messages) if isinstance(message, AIMessage)),
        None,
    )
    model_finalized = bool(latest_ai and not (getattr(latest_ai, "tool_calls", None) or []))
    completed = sum(step.status == "complete" for step in run.steps)
    failed = sum(step.status in {"failed", "blocked"} for step in run.steps)
    completion = ExplorationCompletion(
        model_finalized=model_finalized,
        evidence_count=len(run.evidence),
        completed_step_count=completed,
        failed_step_count=failed,
        note=(
            "Réponse finale produite par le modèle."
            if model_finalized
            else "Exécution interrompue avant une réponse finale."
        ),
    )
    status: ExplorationStatus = "complete" if model_finalized else "failed"
    return run.model_copy(
        update={
            "status": status,
            "completion": completion,
            "active_step_id": None if model_finalized else run.active_step_id,
            "updated_at": _now(),
        }
    ).model_dump(mode="json")


_SCHEMA_GROUP_ORDER = (
    "keys",
    "sample",
    "time",
    "space",
    "depth",
    "taxon",
    "measures",
    "categories",
    "text",
    "other",
)
_SCHEMA_GROUP_LIMITS = {
    "keys": 6,
    "sample": 6,
    "time": 4,
    "space": 4,
    "depth": 4,
    "taxon": 5,
    "measures": 6,
    "categories": 4,
    "text": 2,
    "other": 2,
}
_SAMPLE_COLUMN_MARKERS = (
    "sample",
    "profile",
    "station",
    "deployment",
    "cast",
    "analysis",
    "object",
    "net",
)
_TAXON_COLUMN_MARKERS = (
    "taxon",
    "species",
    "genus",
    "family",
    "stage",
    "annotation_category",
)


def _schema_group(column: ResourceColumnProfile) -> str:
    """Map one profiled column to a compact scientific role."""
    name = column.name.casefold().replace("-", "_").replace(" ", "_")
    if column.semantic_role == "identifier":
        return "keys"
    if column.semantic_role == "time":
        return "time"
    if column.semantic_role in {"latitude", "longitude"}:
        return "space"
    if column.semantic_role == "depth":
        return "depth"
    if any(marker in name for marker in _TAXON_COLUMN_MARKERS):
        return "taxon"
    if any(marker in name for marker in _SAMPLE_COLUMN_MARKERS):
        return "sample"
    if column.semantic_role == "measure":
        return "measures"
    if column.semantic_role == "category":
        return "categories"
    if column.semantic_role == "text":
        return "text"
    return "other"


def _render_resource_schema(resource: ResourceRecord) -> tuple[str, int]:
    """Render a bounded schema while retaining every useful column family."""
    grouped: dict[str, list[str]] = {name: [] for name in _SCHEMA_GROUP_ORDER}
    for column in resource.column_profiles:
        group = _schema_group(column)
        grouped[group].append(f"{column.name}:{column.dtype}")

    rendered: list[str] = []
    shown = 0
    for group in _SCHEMA_GROUP_ORDER:
        values = grouped[group][:_SCHEMA_GROUP_LIMITS[group]]
        if not values:
            continue
        shown += len(values)
        rendered.append(f"{group}=[{','.join(values)}]")

    if not rendered and resource.columns:
        fallback = list(resource.columns[:16])
        shown = len(fallback)
        rendered.append("columns=[" + ",".join(fallback) + "]")
    return "; ".join(rendered) or "unknown", shown


def _render_scope(scope: dict[str, Any]) -> str:
    """Keep scope useful without injecting long identifier lists."""
    if not scope:
        return "not declared"
    filters = {
        key: value
        for key, value in scope.items()
        if str(key).startswith("filter.")
    }
    compact: dict[str, Any] = {}
    for key, value in scope.items():
        if key in {
            "scope_basis",
            "scope_columns",
            "time_columns",
            "declared_conflicts",
        } or str(key).startswith("filter."):
            continue
        if key.endswith("_count") and key[:-6] in scope:
            continue
        if isinstance(value, list):
            if key in {"project_ids"} and len(value) <= 6:
                compact[key] = value
            else:
                compact[key] = {"count": len(value)}
        else:
            compact[key] = value
    rendered_filters = (
        json.dumps(filters, ensure_ascii=False, separators=(",", ":"))
        if filters
        else ""
    )
    rendered_observed = (
        json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if compact
        else ""
    )
    if rendered_filters and rendered_observed:
        return f"{rendered_filters}; observed={rendered_observed}"
    return rendered_filters or rendered_observed or "not established"


_PARENT_RELATION_KINDS = frozenset({
    "alias_of",
    "parent_variable",
    "parent_variables",
    "source_variable",
    "input_dataframes",
    "raw_export_variables",
})


def _resource_parents(resource: ResourceRecord) -> tuple[str, ...]:
    """Return explicit parent table names without exposing relation syntax."""
    parents: list[str] = []
    for relation in resource.relations:
        kind, separator, target = relation.partition(":")
        if separator and kind in _PARENT_RELATION_KINDS and target:
            parents.append(target)
    return tuple(dict.fromkeys(parents))


def _is_file_backed_resource(resource: ResourceRecord) -> bool:
    """Return whether a table is a canonical DataFrame loaded from a file."""
    source = resource.source.casefold()
    provenance_source = str(resource.provenance.get("source") or "").casefold()
    return (
        resource.name.casefold().startswith("df_file_")
        or source == "file"
        or source.startswith("file:")
        or provenance_source == "file"
        or provenance_source.startswith("file:")
    )


_SOURCE_ANCHOR_PREFIXES = (
    "ecotaxa",
    "ecopart",
    "join:ecotaxa",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
)


def _is_source_anchor_resource(resource: ResourceRecord) -> bool:
    """Return whether a table must stay explicit for dataset selection."""
    if _is_file_backed_resource(resource):
        return True
    source_values = (
        resource.source.casefold(),
        str(resource.provenance.get("source") or "").casefold(),
    )
    return any(
        value.startswith(prefix)
        for value in source_values
        for prefix in _SOURCE_ANCHOR_PREFIXES
    )


def _bounded_inline(value: object, limit: int) -> str:
    """Render one compact single-line value within a strict character budget."""
    text = " ".join(str(value or "not established").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _usage_label(resource: ResourceRecord) -> str:
    if resource.age_turns is None:
        return "unknown"
    if resource.age_turns == 0:
        return "current"
    return f"{resource.age_turns}_turns_ago"


def _render_file_resource_block(
    resource: ResourceRecord,
    *,
    active_variable: str | None,
    max_chars: int,
) -> str:
    """Render a bounded but useful card for a canonical uploaded-file table."""
    schema, shown = _render_resource_schema(resource)
    total_columns = len(resource.columns)
    partial = resource.columns_truncated or shown < total_columns
    value_budget = max(40, max_chars - len(resource.name) - 165)
    source_budget = max(12, value_budget * 18 // 100)
    grain_budget = max(16, value_budget * 20 // 100)
    description_budget = max(20, value_budget * 28 // 100)
    schema_budget = max(24, value_budget - source_budget - grain_budget - description_budget)
    status = "active" if resource.name == active_variable else "available"
    return "\n".join([
        f"- {resource.name}",
        "  file_source="
        f"{_bounded_inline(resource.source, source_budget)}; status={status}; "
        f"last_used={_usage_label(resource)}; "
        f"rows={resource.rows if resource.rows is not None else 'unknown'}; "
        f"grain={_bounded_inline(resource.grain, grain_budget)}; "
        f"description={_bounded_inline(resource.description, description_budget)}; "
        f"schema_by_role={_bounded_inline(schema, schema_budget)}; "
        f"schema_visibility={shown}/{total_columns}"
        f"{' partial' if partial else ' complete'}; "
        f"keys={','.join(resource.key_candidates[:8]) or 'not established'}",
    ])


def _render_source_anchor_block(
    resource: ResourceRecord,
    *,
    active_variable: str | None,
    max_chars: int,
) -> str:
    """Render one bounded export/cache/enrichment card used for selection."""
    schema, shown = _render_resource_schema(resource)
    total_columns = len(resource.columns)
    partial = resource.columns_truncated or shown < total_columns
    status = "active" if resource.name == active_variable else "available"
    value_budget = max(100, max_chars - len(resource.name) - 230)
    description_budget = max(28, value_budget * 28 // 100)
    schema_budget = max(40, value_budget * 32 // 100)
    lineage_budget = max(24, value_budget * 20 // 100)
    scope_budget = max(
        20,
        value_budget - description_budget - schema_budget - lineage_budget,
    )
    return "\n".join([
        f"- {resource.name}",
        f"  source_anchor={_bounded_inline(resource.source, 90)}; "
        f"status={status}; last_used={_usage_label(resource)}; "
        f"rows={resource.rows if resource.rows is not None else 'unknown'}; "
        f"grain={_bounded_inline(resource.grain, 100)}",
        f"  description={_bounded_inline(resource.description, description_budget)}",
        f"  schema_by_role={_bounded_inline(schema, schema_budget)}; "
        f"schema_visibility={shown}/{total_columns}"
        f"{' partial' if partial else ' complete'}; "
        f"keys={','.join(resource.key_candidates[:8]) or 'not established'}",
        f"  scope={_bounded_inline(_render_scope(resource.scope), scope_budget)}; "
        f"lineage={_bounded_inline(' | '.join(resource.relations[:8]), lineage_budget)}",
    ])


def render_task_context(
    payload: object,
    *,
    messages: tuple[Any, ...] | list[Any] = (),
    preferred_sources: tuple[str, ...] = (),
    primary_source: str | None = None,
    max_chars: int = 2_600,
) -> str:
    """Render the current request plus a bounded user-only continuity capsule."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    deliverables = ", ".join(item.kind for item in run.deliverables) or "answer"
    human_instructions = [
        " ".join(_message_text(message).split())[:360]
        for message in messages
        if isinstance(message, HumanMessage) and _message_text(message).strip()
    ]
    prior_instructions = human_instructions[:-1][-4:]
    continuity = ""
    if prior_instructions:
        continuity = (
            "\nRecent user instructions (oldest to newest; context only, "
            "the current objective wins):\n"
            + "\n".join(f"- {instruction}" for instruction in prior_instructions)
        )
    source_line = ""
    if preferred_sources or primary_source:
        source_line = (
            "\nPreferred source route: "
            + (",".join(preferred_sources) or "none")
            + f"; primary={primary_source or 'none'}."
        )
    rendered = (
        "\n\n## CURRENT TASK (authoritative for this turn)\n"
        f"Objective: {run.objective}\n"
        f"Required deliverables: {deliverables}\n"
        + continuity
        + "\n\n## PLANNER DATASET CHOICE\n"
        "Application selection: none. Candidate choice and qualification remain "
        "the planner's responsibility under the permanent DataFrame contract."
        + source_line
    )
    return rendered[:max_chars]


def render_dataframe_context(
    payload: object,
    *,
    active_variable: str | None = None,
    messages: tuple[Any, ...] | list[Any] = (),
    max_chars: int = 9_000,
) -> str:
    """Render the factual working set plus a complete compact table index."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    tables = [
        item
        for item in run.resources_available
        if item.kind in {"table", "selection"}
    ]
    alphabetical_tables = sorted(
        tables,
        key=lambda item: (item.name.casefold(), item.source.casefold()),
    )

    from agents.context_working_set import build_working_set

    working_set = build_working_set(
        tables,
        messages,
        active_variable=active_variable,
    )
    resources_by_name = {resource.name: resource for resource in tables}
    entries_by_name = {entry.data_ref: entry for entry in working_set.entries}
    latest_tool_fact_by_name = {
        fact.produced_ref: fact
        for fact in working_set.ledger.tool_facts
        if fact.produced_ref and fact.status == "success"
    }
    ordered_names = list(working_set.ordered_names)
    remaining = sorted(
        (resource for resource in tables if resource.name not in ordered_names),
        key=lambda resource: (
            resource.age_turns is None,
            resource.age_turns if resource.age_turns is not None else 10**9,
            resource.name.casefold(),
            resource.source.casefold(),
        ),
    )
    ordered_names.extend(resource.name for resource in remaining)
    detailed_names = ordered_names[: min(12, len(ordered_names))]
    header_lines = [
        "\n\n## AVAILABLE DATAFRAMES (current session)",
        "Structured tool facts override resource metadata; resource metadata "
        "overrides older assistant prose.",
        "The working set uses exact references, executed tools and declared "
        "lineage; no lexical plan ranking is used.",
        "DATAFRAME INDEX (all live resources):",
    ]
    full_index_lines = [f"* {resource.name}" for resource in alphabetical_tables]
    rendered_blocks = [*header_lines, *full_index_lines]
    if len("\n".join(rendered_blocks)) > max_chars - 600:
        rendered_blocks = [
            *header_lines,
            "* " + " | ".join(resource.name for resource in alphabetical_tables),
        ]
    rendered_blocks.append(
        "DATAFRAME WORKING SET (pinned facts first, then inventory recency):"
    )

    remaining_for_cards = max_chars - len("\n".join(rendered_blocks)) - 500
    card_budget = (
        max(300, min(700, remaining_for_cards // len(detailed_names)))
        if detailed_names
        else 0
    )
    entry_blocks: list[tuple[str, str]] = []
    for name in detailed_names:
        resource = resources_by_name[name]
        entry = entries_by_name.get(name)
        tool_fact = latest_tool_fact_by_name.get(name)
        schema, shown = _render_resource_schema(resource)
        total_columns = len(resource.columns)
        partial = resource.columns_truncated or shown < total_columns
        description = (
            (tool_fact.summary if tool_fact and tool_fact.summary else None)
            or resource.description
            or (
                f"Persisted {resource.kind} from {resource.source}; no richer "
                "description was supplied by the producing operation."
            )
        )
        rows = tool_fact.rows if tool_fact and tool_fact.rows is not None else resource.rows
        grain = tool_fact.grain if tool_fact and tool_fact.grain else resource.grain
        scope = tool_fact.scope if tool_fact and tool_fact.scope else resource.scope
        source = (
            str(tool_fact.provenance.get("source"))
            if tool_fact and tool_fact.provenance.get("source")
            else resource.source
        )
        status = "active" if resource.name == active_variable else "available"
        focus = entry.role if entry is not None else "inventory"
        authority = entry.authority if entry is not None else "resource"
        pinned = bool(entry and entry.pinned)
        reasons = ",".join(entry.reasons) if entry is not None else "inventory_recency"
        parents = _resource_parents(resource)
        value_budget = max(80, card_budget - len(resource.name) - 290)
        description_budget = max(24, value_budget * 24 // 100)
        schema_budget = (
            max(300, value_budget * 45 // 100)
            if partial
            else max(80, value_budget * 35 // 100)
        )
        scope_budget = max(20, value_budget * 18 // 100)
        lineage_budget = max(
            24,
            value_budget - description_budget - schema_budget - scope_budget,
        )
        block = "\n".join([
            f"- {resource.name}",
            f"  status={status}; focus={focus}; pinned={str(pinned).lower()}; "
            f"authority={authority}; reasons={_bounded_inline(reasons, 100)}",
            f"  kind={resource.kind}; source={_bounded_inline(source, 80)}; "
            f"parents={','.join(parents) or 'none'}; "
            f"last_used={_usage_label(resource)}; "
            f"rows={rows if rows is not None else 'unknown'}; "
            f"grain={_bounded_inline(grain, 90)}",
            f"  description={_bounded_inline(description, description_budget)}",
            f"  schema_by_role={_bounded_inline(schema, schema_budget)}; "
            f"schema_visibility={shown}/{total_columns}"
            f"{' partial' if partial else ' complete'}; "
            "identifiers_present="
            f"{','.join(resource.identifiers[:12]) or 'none'}; "
            "keys="
            f"{','.join(resource.key_candidates[:8]) or 'not established'}",
            f"  scope={_bounded_inline(_render_scope(scope), scope_budget)}; "
            "lineage="
            f"{_bounded_inline(' | '.join(resource.relations[:8]), lineage_budget)}",
        ])
        entry_blocks.append((name, block))

    expanded_names: list[str] = []
    for name, block in entry_blocks:
        candidate = "\n".join([*rendered_blocks, block])
        if len(candidate) + 350 > max_chars:
            # One unusual wide card must not hide every smaller card after it.
            continue
        rendered_blocks.append(block)
        expanded_names.append(name)

    expanded_count = len(expanded_names)
    index_only_count = len(tables) - expanded_count
    rendered_blocks.append(
        "DATAFRAME CATALOG COUNTS: "
        f"total={len(tables)}; expanded={expanded_count}; "
        f"index_only={index_only_count}."
    )
    if index_only_count:
        rendered_blocks.append(
            "INDEX-ONLY DATAFRAMES: "
            + " | ".join(
                resource.name
                for resource in alphabetical_tables
                if resource.name not in expanded_names
            )
        )

    other_resources = [
        item
        for item in run.resources_available
        if item.kind not in {"table", "selection"}
    ]
    if other_resources:
        other_lines = ["OTHER AVAILABLE RESOURCES:"]
        for resource in other_resources[:12]:
            other_lines.append(
                f"- {resource.name}: kind={resource.kind}; source={resource.source}; "
                f"capabilities={','.join(resource.capabilities) or 'not declared'}"
            )
        other_block = "\n".join(other_lines)
        if len("\n".join([*rendered_blocks, other_block])) <= max_chars:
            rendered_blocks.append(other_block)
    return "\n".join(rendered_blocks)[:max_chars]


def dataframe_context_metrics(context: str) -> dict[str, int]:
    """Read the renderer's explicit catalog counts for audit telemetry."""

    match = re.search(
        r"DATAFRAME CATALOG COUNTS: total=(\d+); expanded=(\d+); "
        r"index_only=(\d+)\.",
        context,
    )
    if match is None:
        return {
            "dataframe_catalog_total": 0,
            "dataframe_catalog_expanded": 0,
            "dataframe_catalog_index_only": 0,
        }
    total, expanded, index_only = (int(value) for value in match.groups())
    return {
        "dataframe_catalog_total": total,
        "dataframe_catalog_expanded": expanded,
        "dataframe_catalog_index_only": index_only,
    }


def render_exploration_frontier(payload: object, *, max_chars: int = 4_500) -> str:
    """Render factual tool progress, dependencies and evidence only."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    steps = [
        {
            "id": item.step_id,
            "tool": item.tool_name,
            "status": item.status,
            "evidence": list(item.observation_refs),
        }
        for item in run.steps[-12:]
    ]
    evidence = [
        {
            "id": item.evidence_id,
            "step": item.step_id,
            "status": item.status,
            "data_ref": item.data_ref,
            "artifacts": list(item.artifact_refs),
            "summary": item.summary[:240],
        }
        for item in run.evidence[-10:]
    ]
    data_dependencies = [
        {
            "id": item.dependency_id,
            "kind": item.resource_kind,
            "name": item.resource_name,
            "canonical_name": item.canonical_name,
            "source": item.source_hint,
            "status": item.status,
            "candidate_resources": list(item.candidate_resources),
            "resume_step": item.step_id,
            "resume_required": item.resume_required,
        }
        for item in run.dependencies
        if item.kind == "data"
        and (item.status == "pending" or item.resume_required)
    ]
    lifecycle = (
        "tool_running"
        if run.active_step_id
        else "awaiting_model"
        if run.status == "running"
        else run.status
    )
    rendered = (
        "\n\n## EXPLORATION FRONTIER (checkpointed working memory)\n"
        f"Lifecycle: {lifecycle}; active_call={run.active_step_id or 'none'}\n"
        "Actual tool calls: "
        + json.dumps(steps, ensure_ascii=False, separators=(",", ":"))
        + "\nEvidence collected: "
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        + "\nData dependencies: "
        + json.dumps(data_dependencies, ensure_ascii=False, separators=(",", ":"))
    )
    if data_dependencies:
        rendered += (
            "\nResolve every pending data dependency from the available resources, "
            "then rerun the failed analytical step before answering."
        )
    return rendered[:max_chars]


def render_exploration_context(payload: object, *, max_chars: int = 19_000) -> str:
    """Compatibility renderer for callers that still need the complete projection."""
    rendered = (
        render_task_context(payload)
        + render_dataframe_context(payload)
        + render_exploration_frontier(payload)
    )
    return rendered[:max_chars]
