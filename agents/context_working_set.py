"""Fact-based selection of the DataFrames that deserve context detail.

This module deliberately does not infer an analytical plan from natural
language.  It only projects facts already present in the runtime: structured
tool artifacts, exact references to live DataFrame names, declared lineage,
and inventory recency.  Assistant prose is recorded only as a low-authority
reference and can never manufacture rows, scope, provenance, or lineage.

The module has no dependency on ``agents.exploration_state``.  Its public
``ResourceLike`` protocol accepts ``ResourceRecord`` instances without
creating an import cycle when the DataFrame renderer adopts this Interface.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, JsonValue

FactAuthority: TypeAlias = Literal[
    "tool",
    "user_reference",
    "resource",
    "assistant_reference",
]
ReferenceActor: TypeAlias = Literal["user", "assistant"]
WorkingSetRole: TypeAlias = Literal[
    "primary",
    "recent",
    "lineage_parent",
    "active_fallback",
]

_SUCCESS_STATUSES = frozenset({"success"})
_PARENT_RELATION_KINDS = frozenset(
    {
        "alias_of",
        "parent_variable",
        "parent_variables",
        "source_variable",
        "input_dataframes",
        "raw_export_variables",
    }
)


class ResourceLike(Protocol):
    """Structural Interface required from an inventory resource."""

    resource_id: str
    name: str
    kind: str
    source: str
    persisted: bool
    rows: int | None
    grain: str | None
    relations: tuple[str, ...]
    age_turns: int | None
    scope: Mapping[str, Any]
    provenance: Mapping[str, Any]


class _ContextModel(BaseModel):
    """Frozen base model for JSON-safe context projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceFact(_ContextModel):
    """Authoritative inventory metadata for one currently live resource."""

    resource_id: str
    data_ref: str
    kind: str
    source: str
    persisted: bool
    rows: int | None = None
    grain: str | None = None
    relations: tuple[str, ...] = ()
    age_turns: int | None = None
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    authority: Literal["resource"] = "resource"


class ToolFact(_ContextModel):
    """One actually returned tool result and its structured evidence."""

    fact_id: str
    sequence: int
    turn: int
    tool_call_id: str
    tool_name: str
    status: str
    summary: str = ""
    consumed_refs: tuple[str, ...] = ()
    produced_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    persisted: bool = False
    rows: int | None = None
    columns: int | None = None
    grain: str | None = None
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    method: str | None = None
    metrics: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    authority: Literal["tool"] = "tool"


class ReferenceFact(_ContextModel):
    """Exact mention of a live DataFrame name, without inferred meaning."""

    fact_id: str
    sequence: int
    turn: int
    actor: ReferenceActor
    data_refs: tuple[str, ...]
    authority: Literal["user_reference", "assistant_reference"]


class FactLedger(_ContextModel):
    """Serializable evidence ledger used to construct a turn working set.

    Tool facts are authoritative for outcomes and numerical metrics. Resource
    facts are authoritative for the current inventory. Assistant references
    only establish that an exact live name was mentioned; their prose is not
    retained as evidence.
    """

    schema_version: Literal["context_fact_ledger_v1"] = "context_fact_ledger_v1"
    current_turn: int
    resources: tuple[ResourceFact, ...] = ()
    tool_facts: tuple[ToolFact, ...] = ()
    references: tuple[ReferenceFact, ...] = ()


class WorkingSetEntry(_ContextModel):
    """One ordered DataFrame selected for a detailed context card."""

    resource_id: str
    data_ref: str
    role: WorkingSetRole
    pinned: bool
    authority: FactAuthority
    reasons: tuple[str, ...]


class WorkingSetProjection(_ContextModel):
    """Small typed Interface between factual state and context rendering."""

    schema_version: Literal["dataframe_working_set_v1"] = "dataframe_working_set_v1"
    ledger: FactLedger
    entries: tuple[WorkingSetEntry, ...]

    @property
    def ordered_names(self) -> tuple[str, ...]:
        """Return selected names in render order."""

        return tuple(entry.data_ref for entry in self.entries)

    @property
    def pinned_names(self) -> tuple[str, ...]:
        """Return names whose detail cards must survive context budgeting."""

        return tuple(entry.data_ref for entry in self.entries if entry.pinned)

    def names_for_role(self, role: WorkingSetRole) -> tuple[str, ...]:
        """Return selected names belonging to one factual role."""

        return tuple(entry.data_ref for entry in self.entries if entry.role == role)


@dataclass(frozen=True)
class _CallRecord:
    tool_name: str
    arguments: object
    sequence: int
    turn: int


@dataclass
class _SelectionDraft:
    resource: ResourceFact
    role: WorkingSetRole
    pinned: bool
    authority: FactAuthority
    reasons: list[str] = field(default_factory=list)


def _is_identifier_character(character: str) -> bool:
    return character == "_" or character.isalnum()


def _exact_reference_position(text: str, name: str) -> int | None:
    """Locate a complete identifier without interpreting surrounding prose."""

    start = 0
    while True:
        position = text.find(name, start)
        if position < 0:
            return None
        before_ok = position == 0 or not _is_identifier_character(text[position - 1])
        end = position + len(name)
        after_ok = end == len(text) or not _is_identifier_character(text[end])
        if before_ok and after_ok:
            return position
        start = position + 1


def _ordered_exact_references(text: str, live_names: Iterable[str]) -> tuple[str, ...]:
    positions = [
        (position, -len(name), name)
        for name in live_names
        if (position := _exact_reference_position(text, name)) is not None
    ]
    positions.sort()
    return tuple(dict.fromkeys(name for _, _, name in positions))


def _content_text(content: object) -> str:
    """Flatten only textual message blocks; ignore opaque binary content."""

    if isinstance(content, str):
        return content
    if not isinstance(content, Sequence) or isinstance(content, (bytes, bytearray)):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
            parts.append(str(item["text"]))
    return "\n".join(parts)


def _primitive_strings(value: object) -> Iterable[str]:
    """Yield strings from JSON-like tool arguments without parsing code intent."""

    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _primitive_strings(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _primitive_strings(item)


def _references_in_arguments(arguments: object, live_names: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for text in _primitive_strings(arguments):
        found.extend(_ordered_exact_references(text, live_names))
    return tuple(dict.fromkeys(found))


def _compact_json(value: object, *, depth: int = 0) -> JsonValue:
    """Bound structured evidence while preserving scalar facts exactly."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:497] + "..."
    if depth >= 5:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        items = list(value.items())
        compact = {
            str(key): _compact_json(item, depth=depth + 1)
            for key, item in items[:40]
        }
        if len(items) > 40:
            compact["_omitted_keys"] = len(items) - 40
        return compact
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
        compact_items = [_compact_json(item, depth=depth + 1) for item in items[:40]]
        if len(items) > 40:
            compact_items.append({"_omitted_items": len(items) - 40})
        return compact_items
    return str(value)[:500]


def _compact_mapping(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        return {}
    compact = _compact_json(value)
    return compact if isinstance(compact, dict) else {}


def _fact_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _message_identity(message: BaseMessage, sequence: int) -> str:
    return str(getattr(message, "id", None) or f"sequence:{sequence}")


def _resource_fact(resource: ResourceLike) -> ResourceFact:
    return ResourceFact(
        resource_id=str(resource.resource_id),
        data_ref=str(resource.name),
        kind=str(resource.kind),
        source=str(resource.source),
        persisted=bool(resource.persisted),
        rows=resource.rows,
        grain=resource.grain,
        relations=tuple(str(item) for item in resource.relations),
        age_turns=resource.age_turns,
        scope=_compact_mapping(resource.scope),
        provenance=_compact_mapping(resource.provenance),
    )


def build_fact_ledger(
    resources: Iterable[ResourceLike],
    messages: Iterable[BaseMessage],
) -> FactLedger:
    """Build a compact factual ledger from current inventory and messages.

    Only returned ``ToolMessage`` objects become tool facts. An AI tool call
    without a corresponding result is therefore never presented as executed.
    Tool arguments are inspected solely for exact names from the live resource
    inventory; no analytical purpose is inferred from their text.

    Args:
        resources: Current resource inventory, normally ``ResourceRecord`` values.
        messages: Available structured LangChain message history.

    Returns:
        A JSON-serializable ledger with tool, resource, and exact-reference facts.
    """

    resource_facts = tuple(_resource_fact(resource) for resource in resources)
    live_names = tuple(item.data_ref for item in resource_facts)
    message_list = list(messages)
    current_turn = 0
    turn_by_sequence: dict[int, int] = {}
    calls: dict[str, _CallRecord] = {}

    for sequence, message in enumerate(message_list):
        if isinstance(message, HumanMessage):
            current_turn += 1
        turn_by_sequence[sequence] = current_turn
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or ():
            call_id = str(call.get("id") or "")
            if not call_id:
                continue
            calls[call_id] = _CallRecord(
                tool_name=str(call.get("name") or "unknown"),
                arguments=call.get("args") or {},
                sequence=sequence,
                turn=current_turn,
            )

    tool_facts: list[ToolFact] = []
    references: list[ReferenceFact] = []
    for sequence, message in enumerate(message_list):
        turn = turn_by_sequence[sequence]
        if isinstance(message, ToolMessage):
            call_id = str(message.tool_call_id or "")
            call = calls.get(call_id)
            artifact = message.artifact if isinstance(message.artifact, Mapping) else {}
            data_ref = str(artifact.get("data_ref")) if artifact.get("data_ref") else None
            status = str(artifact.get("status") or getattr(message, "status", None) or "unknown")
            consumed_refs = _references_in_arguments(
                call.arguments if call is not None else {},
                live_names,
            )
            artifact_refs = tuple(
                str(item) for item in artifact.get("artifact_refs") or () if item
            )
            metrics = _compact_mapping(artifact.get("metrics"))
            provenance = _compact_mapping(artifact.get("provenance"))
            rows_value = metrics.get("rows")
            columns_value = metrics.get("columns")
            grain_value = metrics.get("grain") or provenance.get("grain")
            scope_value = metrics.get("scope") or provenance.get("scope")
            tool_facts.append(
                ToolFact(
                    fact_id=_fact_id("tool", call_id, _message_identity(message, sequence)),
                    sequence=sequence,
                    turn=turn,
                    tool_call_id=call_id,
                    tool_name=str(message.name or (call.tool_name if call else "unknown")),
                    status=status,
                    summary=str(artifact.get("summary") or "")[:500],
                    consumed_refs=consumed_refs,
                    produced_ref=data_ref,
                    artifact_refs=artifact_refs,
                    persisted=bool(artifact.get("persisted", False)),
                    rows=(
                        int(rows_value)
                        if isinstance(rows_value, (int, float))
                        and not isinstance(rows_value, bool)
                        else None
                    ),
                    columns=(
                        int(columns_value)
                        if isinstance(columns_value, (int, float))
                        and not isinstance(columns_value, bool)
                        else None
                    ),
                    grain=str(grain_value)[:160] if grain_value else None,
                    scope=(scope_value if isinstance(scope_value, dict) else {}),
                    method=(
                        str(artifact.get("method"))[:240]
                        if artifact.get("method")
                        else None
                    ),
                    metrics=metrics,
                    provenance=provenance,
                )
            )
            continue

        if not isinstance(message, (HumanMessage, AIMessage)):
            continue
        exact_refs = _ordered_exact_references(_content_text(message.content), live_names)
        if not exact_refs:
            continue
        actor: ReferenceActor = "user" if isinstance(message, HumanMessage) else "assistant"
        authority: Literal["user_reference", "assistant_reference"] = (
            "user_reference" if actor == "user" else "assistant_reference"
        )
        references.append(
            ReferenceFact(
                fact_id=_fact_id(
                    "reference",
                    actor,
                    _message_identity(message, sequence),
                    *exact_refs,
                ),
                sequence=sequence,
                turn=turn,
                actor=actor,
                data_refs=exact_refs,
                authority=authority,
            )
        )

    return FactLedger(
        current_turn=current_turn,
        resources=resource_facts,
        tool_facts=tuple(tool_facts),
        references=tuple(references),
    )


def _declared_parents(
    resource: ResourceFact,
    resources_by_name: Mapping[str, ResourceFact],
) -> tuple[str, ...]:
    parents: list[str] = []
    for relation in resource.relations:
        relation_kind, separator, target = relation.partition(":")
        if not separator or relation_kind not in _PARENT_RELATION_KINDS:
            continue
        if target in resources_by_name and target != resource.data_ref:
            parents.append(target)
    return tuple(dict.fromkeys(parents))


def build_working_set(
    resources: Iterable[ResourceLike],
    messages: Iterable[BaseMessage],
    *,
    active_variable: str | None = None,
    max_recent: int = 4,
    max_lineage_parents: int = 6,
) -> WorkingSetProjection:
    """Select and order context resources without semantic classification.

    Only explicit current-turn evidence can select a primary resource. Results
    from earlier turns remain recent factual candidates so the model can reuse
    them, but they never carry primary focus into a new user request. A resource
    selected by tool evidence remains ahead of one found only in assistant
    prose. Exact user references are treated as direct instructions, not as
    inferred semantics.

    Args:
        resources: Current live resource inventory.
        messages: Structured message history available to the model call.
        active_variable: Legacy active DataFrame pointer used only as fallback.
        max_recent: Maximum non-primary recent resources to pin.
        max_lineage_parents: Maximum declared parents to pin.

    Returns:
        Ordered entries and the serializable ledger that justifies each choice.

    Raises:
        ValueError: If either selection limit is negative.
    """

    if max_recent < 0 or max_lineage_parents < 0:
        raise ValueError("Working-set limits must be non-negative")

    ledger = build_fact_ledger(resources, messages)
    resources_by_name = {item.data_ref: item for item in ledger.resources}
    drafts: dict[str, _SelectionDraft] = {}
    ordered_names: list[str] = []

    def select(
        name: str | None,
        *,
        role: WorkingSetRole,
        pinned: bool,
        authority: FactAuthority,
        reason: str,
    ) -> None:
        if not name or name not in resources_by_name:
            return
        existing = drafts.get(name)
        if existing is not None:
            if reason not in existing.reasons:
                existing.reasons.append(reason)
            return
        drafts[name] = _SelectionDraft(
            resource=resources_by_name[name],
            role=role,
            pinned=pinned,
            authority=authority,
            reasons=[reason],
        )
        ordered_names.append(name)

    current_turn = ledger.current_turn
    current_user_refs = [
        fact
        for fact in ledger.references
        if fact.actor == "user" and fact.turn == current_turn
    ]
    current_successes = [
        fact
        for fact in ledger.tool_facts
        if fact.turn == current_turn and fact.status in _SUCCESS_STATUSES
    ]

    for fact in reversed(current_successes):
        select(
            fact.produced_ref,
            role="primary",
            pinned=True,
            authority="tool",
            reason="current_tool_output",
        )
    for fact in reversed(current_user_refs):
        for name in fact.data_refs:
            select(
                name,
                role="primary",
                pinned=True,
                authority="user_reference",
                reason="current_user_exact_reference",
            )

    # Keep exact names from the preceding answer available, but never let
    # assistant prose choose the primary DataFrame. Primary focus must come
    # from current evidence, a successful tool result, or the live inventory.
    latest_assistant_reference = next(
        (
            fact
            for fact in reversed(ledger.references)
            if fact.actor == "assistant" and fact.turn < current_turn
        ),
        None,
    )

    recent_tool_candidates: list[tuple[str, FactAuthority, str]] = []
    for fact in reversed(ledger.tool_facts):
        if fact.produced_ref:
            recent_tool_candidates.append(
                (fact.produced_ref, "tool", "recent_tool_output")
            )
        recent_tool_candidates.extend(
            (name, "tool", "recent_tool_input") for name in fact.consumed_refs
        )
    if latest_assistant_reference is not None:
        recent_tool_candidates.extend(
            (name, "assistant_reference", "last_answer_exact_reference")
            for name in latest_assistant_reference.data_refs
        )
    for fact in reversed(ledger.references):
        if fact.actor != "assistant" or fact is latest_assistant_reference:
            continue
        recent_tool_candidates.extend(
            (name, "assistant_reference", "assistant_exact_reference")
            for name in fact.data_refs
        )
    selected_recent = sum(
        draft.role == "recent" for draft in drafts.values()
    )
    for name, authority, reason in recent_tool_candidates:
        if selected_recent >= max_recent:
            break
        before = len(ordered_names)
        select(
            name,
            role="recent",
            pinned=True,
            authority=authority,
            reason=reason,
        )
        if len(ordered_names) > before:
            selected_recent += 1

    lineage_queue = list(ordered_names)
    lineage_count = 0
    visited_lineage: set[str] = set()
    while lineage_queue and lineage_count < max_lineage_parents:
        seed_name = lineage_queue.pop(0)
        if seed_name in visited_lineage:
            continue
        visited_lineage.add(seed_name)
        if lineage_count >= max_lineage_parents:
            break
        seed = resources_by_name[seed_name]
        for parent_name in _declared_parents(seed, resources_by_name):
            if lineage_count >= max_lineage_parents:
                break
            before = len(ordered_names)
            select(
                parent_name,
                role="lineage_parent",
                pinned=True,
                authority="resource",
                reason=f"declared_parent_of:{seed_name}",
            )
            if len(ordered_names) > before:
                lineage_count += 1
                lineage_queue.append(parent_name)

    if selected_recent < max_recent:
        metadata_recent = sorted(
            ledger.resources,
            key=lambda item: (
                item.age_turns is None,
                item.age_turns if item.age_turns is not None else 10**9,
                item.data_ref.casefold(),
            ),
        )
        for resource in metadata_recent:
            if selected_recent >= max_recent:
                break
            before = len(ordered_names)
            select(
                resource.data_ref,
                role="recent",
                pinned=True,
                authority="resource",
                reason="inventory_recency",
            )
            if len(ordered_names) > before:
                selected_recent += 1

    select(
        active_variable,
        role="active_fallback",
        pinned=False,
        authority="resource",
        reason="legacy_active_fallback",
    )

    entries = tuple(
        WorkingSetEntry(
            resource_id=drafts[name].resource.resource_id,
            data_ref=name,
            role=drafts[name].role,
            pinned=drafts[name].pinned,
            authority=drafts[name].authority,
            reasons=tuple(drafts[name].reasons),
        )
        for name in ordered_names
    )
    return WorkingSetProjection(ledger=ledger, entries=entries)


__all__ = [
    "FactLedger",
    "ReferenceFact",
    "ResourceFact",
    "ResourceLike",
    "ToolFact",
    "WorkingSetEntry",
    "WorkingSetProjection",
    "WorkingSetRole",
    "build_fact_ledger",
    "build_working_set",
]
