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


_VISUAL_PATTERN = re.compile(
    r"\b(graph(?:ique)?|carte|figure|visualis|plot|chart|map)\w*\b",
    re.IGNORECASE,
)
_FILE_PATTERN = re.compile(
    r"\b(export|t[ée]l[ée]charg|pdf|csv|xlsx|livrable|rapport)\w*\b",
    re.IGNORECASE,
)
_TABLE_PATTERN = re.compile(
    r"\b(tableau|table|liste|classement|r[ée]sum[ée])\w*\b",
    re.IGNORECASE,
)
_PLAN_HEADING_PATTERN = re.compile(
    r"(?im)^#{2,4}\s*plan(?:\s+d['’]action)?\s*$"
)
_PLAN_ITEM_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(?:\[[ xX]\]\s*)?(?P<item>.+?)\s*$"
)


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


def infer_deliverables(objective: str) -> tuple[ExplorationDeliverable, ...]:
    deliverables: list[ExplorationDeliverable] = [
        ExplorationDeliverable(kind="answer", description=objective or "Répondre à la demande")
    ]
    if _TABLE_PATTERN.search(objective):
        deliverables.append(
            ExplorationDeliverable(kind="table", description="Présenter les résultats structurés")
        )
    if _VISUAL_PATTERN.search(objective):
        deliverables.append(
            ExplorationDeliverable(kind="visualization", description="Produire la visualisation demandée")
        )
    if _FILE_PATTERN.search(objective):
        deliverables.append(
            ExplorationDeliverable(kind="file", description="Produire le fichier livrable demandé")
        )
    return tuple(deliverables)


def new_exploration_run(
    objective: str,
    resources: tuple[ResourceRecord, ...],
) -> dict[str, Any]:
    now = _now()
    run = ExplorationRun(
        run_id=f"explore-{uuid.uuid4().hex}",
        request_fingerprint=request_fingerprint(objective),
        objective=objective,
        deliverables=infer_deliverables(objective),
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


def capability_for_tool(tool_name: str) -> ExplorationCapability:
    name = tool_name.casefold()
    if name == "query_copepod_knowledge_base":
        return "ground_method"
    if name == "run_graph":
        return "visualize_data"
    if name == "export_deliverable" or name.startswith("export_"):
        return "export_deliverable"
    if "join" in name or "couple" in name or "enrich" in name:
        return "join_data"
    if name.startswith(("filter_", "split_")):
        return "filter_data"
    if name == "run_pandas":
        return "compute_metric"
    if name.startswith(("compare_", "rank_", "group_", "count_")):
        return "compare_data"
    if name.startswith(("summarize_", "audit_")):
        return "summarize_data"
    if name.startswith(("list_", "preview_", "inspect_", "describe_", "find_", "get_", "resolve_")):
        return "inspect_resources"
    if name.startswith(("load_", "query_", "copy_")):
        return "retrieve_data"
    return "validate_data"


def _expected_evidence(tool_name: str) -> tuple[str, ...]:
    if tool_name == "run_graph" or tool_name.startswith("export_"):
        return ("successful_status", "artifact_ref")
    return ("successful_status",)


def _capability_for_instruction(instruction: str) -> ExplorationCapability:
    """Infer analytical intent from the already-visible human-readable plan."""
    text = instruction.casefold()
    patterns: tuple[tuple[ExplorationCapability, tuple[str, ...]], ...] = (
        ("export_deliverable", ("export", "livrable", "pdf", "csv", "xlsx", "télécharg")),
        ("visualize_data", ("grap", "visual", "figure", "carte", "plot", "chart", "map")),
        ("join_data", ("joint", "join", "merge", "coupl", "enrich", "relier", "combiner")),
        ("filter_data", ("filtr", "sous-ensemble", "sélectionner", "restreindre", "split")),
        ("retrieve_data", ("récup", "charger", "extraire", "interroger", "query", "télécharg")),
        ("inspect_resources", ("inspect", "schéma", "schema", "colonne", "source", "structure")),
        ("validate_data", ("vérif", "valid", "contrôl", "audit", "couverture")),
        ("compare_data", ("compar", "class", "rang", "différence")),
        ("summarize_data", ("résum", "synth", "décrire", "profil")),
        ("ground_method", ("rag", "méthod", "documentation", "connaissance")),
    )
    for capability, markers in patterns:
        if any(marker in text for marker in markers):
            return capability
    return "compute_metric"


def _extract_plan_items(message: AIMessage) -> tuple[str, ...]:
    text = _message_text(message)
    heading = _PLAN_HEADING_PATTERN.search(text)
    if heading is None:
        return ()
    items: list[str] = []
    for line in text[heading.end():].splitlines():
        if line.lstrip().startswith("#"):
            break
        match = _PLAN_ITEM_PATTERN.match(line)
        if match:
            item = re.sub(r"\s+", " ", match.group("item")).strip()
            if item:
                items.append(item[:500])
        elif items and line.strip():
            items[-1] = f"{items[-1]} {line.strip()}"[:500]
    return tuple(items[:6])


def _plan_message_id(message: AIMessage) -> str:
    explicit = getattr(message, "id", None)
    if explicit:
        return str(explicit)
    payload = {
        "content": _message_text(message),
        "tool_calls": getattr(message, "tool_calls", None) or [],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return f"plan-message-{digest}"


def _expected_resources_for_instruction(
    instruction: str,
    resources: tuple[ResourceRecord, ...],
) -> tuple[str, ...]:
    text = instruction.casefold()
    matched: list[str] = []
    for resource in resources:
        names = {resource.name.casefold(), resource.source.casefold()}
        if any(len(name) >= 3 and name in text for name in names):
            matched.append(resource.name)
    return tuple(dict.fromkeys(matched))


def capture_prospective_plan(
    payload: object,
    messages: list[Any],
) -> dict[str, Any] | None:
    """Persist the existing ``### Plan`` response without another model call."""
    run = validate_exploration_run(payload)
    if run is None:
        return None
    latest_ai = next(
        (
            message
            for message in reversed(_current_turn_messages(messages))
            if isinstance(message, AIMessage)
        ),
        None,
    )
    if latest_ai is None:
        return run.model_dump(mode="json")
    message_id = _plan_message_id(latest_ai)
    if message_id in run.processed_plan_message_ids:
        return run.model_dump(mode="json")
    items = _extract_plan_items(latest_ai)
    if not items:
        return run.model_dump(mode="json")

    revision = run.plan_revision + 1
    steps: list[ExplorationStep] = []
    for step in run.steps:
        if step.origin == "planned" and step.status in {"pending", "blocked"}:
            steps.append(step.model_copy(update={"status": "superseded"}))
        else:
            steps.append(step)

    dependencies = list(run.dependencies)
    anchor = next(
        (
            step.step_id
            for step in reversed(steps)
            if step.status == "complete"
        ),
        None,
    )
    previous_step_id = anchor
    first_step_id: str | None = None
    for position, instruction in enumerate(items, start=1):
        digest = hashlib.sha256(
            f"{run.request_fingerprint}:{revision}:{position}:{instruction}".encode("utf-8")
        ).hexdigest()[:12]
        step_id = f"plan-r{revision}-{digest}"
        if first_step_id is None:
            first_step_id = step_id
        capability = _capability_for_instruction(instruction)
        depends_on = (previous_step_id,) if previous_step_id else ()
        steps.append(
            ExplorationStep(
                step_id=step_id,
                capability=capability,
                instruction=instruction,
                origin="planned",
                plan_position=position,
                depends_on=depends_on,
                expected_resources=_expected_resources_for_instruction(
                    instruction,
                    run.resources_available,
                ),
                expected_evidence=(
                    ("successful_status", "artifact_ref")
                    if capability in {"visualize_data", "export_deliverable"}
                    else ("successful_status",)
                ),
                status="pending",
            )
        )
        if previous_step_id:
            parent = next(
                (step for step in steps if step.step_id == previous_step_id),
                None,
            )
            dependencies.append(
                ExplorationDependency(
                    dependency_id=f"dep-{previous_step_id}-{step_id}",
                    step_id=step_id,
                    depends_on_step_id=previous_step_id,
                    status=(
                        "satisfied"
                        if parent is not None and parent.status == "complete"
                        else "blocked"
                        if parent is not None and parent.status in {"failed", "blocked"}
                        else "pending"
                    ),
                    description="Cette étape planifiée dépend de l’étape précédente.",
                )
            )
        previous_step_id = step_id

    processed = (*run.processed_plan_message_ids, message_id)
    return run.model_copy(
        update={
            "steps": tuple(steps),
            "dependencies": tuple(dependencies),
            "active_step_id": first_step_id or run.active_step_id,
            "processed_plan_message_ids": tuple(dict.fromkeys(processed)),
            "plan_revision": revision,
            "status": "running",
            "updated_at": _now(),
        }
    ).model_dump(mode="json")


def _planned_step_for_call(
    steps: list[ExplorationStep],
    capability: ExplorationCapability,
    tool_name: str,
) -> int | None:
    completed = {step.step_id for step in steps if step.status == "complete"}
    compatible = {capability}
    if tool_name == "run_pandas":
        compatible.update(
            {
                "inspect_resources",
                "filter_data",
                "join_data",
                "validate_data",
                "summarize_data",
                "compare_data",
            }
        )
    for index, step in enumerate(steps):
        if (
            step.origin == "planned"
            and step.status in {"pending", "failed"}
            and step.capability in compatible
            and all(parent in completed for parent in step.depends_on)
        ):
            return index
    return None


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
        planned_index = _planned_step_for_call(steps, capability, tool_name)
        if planned_index is not None:
            planned = steps[planned_index]
            steps[planned_index] = planned.model_copy(
                update={
                    "tool_name": tool_name,
                    "tool_call_id": call_id,
                    "expected_evidence": _expected_evidence(tool_name),
                    "status": "running",
                    "attempts": planned.attempts + 1,
                }
            )
            processed.add(call_id)
            active_step_id = planned.step_id
            parent_step_id = planned.step_id
            continue
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
    running = next(
        (step for step in reversed(steps) if step.status == "running"),
        None,
    )
    if running is not None:
        return running
    completed = {step.step_id for step in steps if step.status == "complete"}
    ready = next(
        (
            step
            for step in steps
            if step.status == "pending"
            and all(parent in completed for parent in step.depends_on)
        ),
        None,
    )
    if ready is not None:
        return ready
    # A finished or failed step is evidence, not work still to execute. Keeping
    # the last completed step active made the model believe the plan was still
    # running and every extra tool call then became a new observed step.
    return None


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
    plan_complete = bool(steps) and all(
        step.status in {"complete", "superseded"} for step in steps
    )
    updated = run.model_copy(
        update={
            "steps": tuple(steps),
            "dependencies": tuple(dependencies),
            "evidence": tuple(evidence),
            "active_step_id": active_step.step_id if active_step else None,
            "status": "complete" if plan_complete else run.status,
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
    unresolved = active_data_dependencies(run.model_dump(mode="json"))
    completion = ExplorationCompletion(
        model_finalized=model_finalized,
        evidence_count=len(run.evidence),
        completed_step_count=completed,
        failed_step_count=failed,
        note=(
            "Fin décidée par le modèle; la suffisance globale sera validée par une étape ultérieure."
            if model_finalized and not unresolved
            else "Une dépendance de données reste à récupérer ou une analyse doit être reprise."
            if unresolved
            else "Exécution interrompue avant une réponse finale."
        ),
    )
    status: ExplorationStatus = "complete" if model_finalized and not unresolved else "failed"
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
    compact: dict[str, Any] = {}
    for key, value in scope.items():
        if isinstance(value, list):
            if key in {"project_ids"} and len(value) <= 6:
                compact[key] = value
            else:
                compact[key] = {"count": len(value)}
        else:
            compact[key] = value
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


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
    preferred_sources: tuple[str, ...] = (),
    primary_source: str | None = None,
    max_chars: int = 1_200,
) -> str:
    """Render turn facts; permanent planning rules stay in the system prompt."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    deliverables = ", ".join(item.kind for item in run.deliverables) or "answer"
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
        "\n\n## PLANNER DATASET CHOICE\n"
        "Application selection: none. Candidate choice and qualification remain "
        "the planner's responsibility under the permanent DataFrame contract."
        + source_line
    )
    return rendered[:max_chars]


def render_dataframe_context(
    payload: object,
    *,
    active_variable: str | None = None,
    max_chars: int = 12_000,
) -> str:
    """Present every live table by name, with bounded relevant details."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    objective = run.objective.casefold()
    tables = [
        item
        for item in run.resources_available
        if item.kind in {"table", "selection"}
    ]
    alphabetical_tables = sorted(
        tables,
        key=lambda item: (item.name.casefold(), item.source.casefold()),
    )
    objective_tokens = {
        token
        for token in re.findall(r"[a-zà-ÿ0-9_]+", objective)
        if len(token) >= 3
    }

    def detail_priority(
        resource: ResourceRecord,
    ) -> tuple[int, int, int, int, str, str]:
        searchable = " ".join([
            resource.name,
            resource.source,
            resource.description or "",
            resource.grain or "",
            *resource.columns,
        ]).casefold()
        overlap = sum(token in searchable for token in objective_tokens)
        return (
            0 if resource.name.casefold() in objective else 1,
            -overlap,
            0 if resource.name == active_variable else 1,
            resource.age_turns if resource.age_turns is not None else 0,
            resource.name.casefold(),
            resource.source.casefold(),
        )

    file_tables = sorted(
        (resource for resource in tables if _is_file_backed_resource(resource)),
        key=detail_priority,
    )
    non_file_source_anchors = sorted(
        (
            resource
            for resource in tables
            if _is_source_anchor_resource(resource)
            and not _is_file_backed_resource(resource)
        ),
        key=detail_priority,
    )
    anchors_by_name = {
        resource.name: resource for resource in non_file_source_anchors
    }

    def declared_parent_names(resource: ResourceRecord) -> tuple[str, ...]:
        names: list[str] = []
        for relation in resource.relations:
            _separator, _found, target = relation.partition(":")
            if target.startswith("df_") and target in anchors_by_name:
                names.append(target)
        return tuple(dict.fromkeys(names))

    selected_anchor_names: list[str] = []

    def add_anchor_with_parents(name: str) -> None:
        if name in selected_anchor_names or len(selected_anchor_names) >= 8:
            return
        selected_anchor_names.append(name)
        for parent in declared_parent_names(anchors_by_name[name]):
            add_anchor_with_parents(parent)

    for resource in non_file_source_anchors:
        add_anchor_with_parents(resource.name)
        if len(selected_anchor_names) >= 8:
            break
    detailed_non_file_anchors = [
        anchors_by_name[name] for name in selected_anchor_names
    ]
    archived_source_anchors = [
        resource
        for resource in non_file_source_anchors
        if resource.name not in selected_anchor_names
    ]
    source_anchor_tables = sorted(
        [*file_tables, *detailed_non_file_anchors],
        key=detail_priority,
    )
    request_relevant_tables = sorted(
        (resource for resource in tables if not _is_source_anchor_resource(resource)),
        key=detail_priority,
    )[:8]
    header_lines = [
        "\n\n## AVAILABLE DATAFRAMES (current session)",
        "All live names are indexed; detailed cards are relevance-bounded.",
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
        "DATAFRAME DECISION BOARD (files + selected source anchors + relevant intermediates):"
    )

    entry_blocks: list[str] = []
    remaining_for_cards = max_chars - len("\n".join(rendered_blocks)) - 600
    anchor_card_budget = (
        max(220, min(900, remaining_for_cards // len(source_anchor_tables)))
        if source_anchor_tables
        else 0
    )
    for resource in source_anchor_tables:
        renderer = (
            _render_file_resource_block
            if _is_file_backed_resource(resource)
            else _render_source_anchor_block
        )
        entry_blocks.append(renderer(
            resource,
            active_variable=active_variable,
            max_chars=anchor_card_budget,
        ))

    for resource in request_relevant_tables:
        schema, shown = _render_resource_schema(resource)
        total_columns = len(resource.columns)
        partial = resource.columns_truncated or shown < total_columns
        description = resource.description or (
            f"Persisted {resource.kind} from {resource.source}; no richer "
            "description was supplied by the producing operation."
        )
        status = "active" if resource.name == active_variable else "available"
        entry_blocks.append(
            "\n".join([
                f"- {resource.name}",
                f"  status={status}; kind={resource.kind}; source={resource.source}; "
                f"last_used={_usage_label(resource)}; "
                f"rows={resource.rows if resource.rows is not None else 'unknown'}",
                f"  description={description}",
                f"  grain={resource.grain or 'not established'}",
                f"  schema_by_role={schema}",
                f"  schema_visibility={shown}/{total_columns}"
                + (" (partial; inspect the persisted table for omitted columns)" if partial else " (complete)"),
                "  keys=" + (",".join(resource.key_candidates[:8]) or "not established"),
                f"  scope={_render_scope(resource.scope)}",
                "  lineage=" + (" | ".join(resource.relations[:8]) or "not declared"),
            ])
        )

    for block in entry_blocks:
        candidate = "\n".join([*rendered_blocks, block])
        if len(candidate) + 600 > max_chars:
            break
        rendered_blocks.append(block)

    expanded_count = sum(block in rendered_blocks for block in entry_blocks)
    if archived_source_anchors:
        rendered_blocks.append(
            f"* {len(archived_source_anchors)} durable source anchors are index-only "
            "in this turn; cite an exact name to reactivate its detailed card."
        )
    if len(tables) > expanded_count:
        rendered_blocks.append(
            f"* {len(tables) - expanded_count} indexed DataFrames are not expanded; "
            "their exact names above remain available."
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


def render_exploration_frontier(payload: object, *, max_chars: int = 4_500) -> str:
    """Render only live progress, dependencies and evidence."""
    run = validate_exploration_run(payload)
    if run is None:
        return ""
    steps = [
        {
            "id": item.step_id,
            "instruction": item.instruction[:240],
            "capability": item.capability,
            "origin": item.origin,
            "position": item.plan_position,
            "depends_on": list(item.depends_on),
            "expected_resources": list(item.expected_resources),
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
    rendered = (
        "\n\n## EXPLORATION FRONTIER (checkpointed working memory)\n"
        f"Run status: {run.status}; plan_revision={run.plan_revision}; "
        f"active_step={run.active_step_id or 'none'}\n"
        "Steps and dependencies: "
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
