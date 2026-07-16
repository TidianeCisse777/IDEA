"""Deterministic per-turn tool exposure policy (harness step 6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Collection, Mapping

from tools.output_intent import successful_calls_in_current_turn
from tools.source_scope import SourceDecision, latest_user_text
from tools.tool_catalog import ToolExposureGroup, ToolPolicy
from tools.turn_context import TurnContext

_CORE_TOOL_NAMES = (
    "load_file",
    "load_skill",
    "query_copepod_knowledge_base",
)
_ENRICHMENT_GROUP_BY_SOURCE: dict[str, ToolExposureGroup] = {
    "ecopart": "enrichment_ecopart",
    "amundsen": "enrichment_amundsen",
    "bio_oracle": "enrichment_bio_oracle",
    "ogsl": "enrichment_ogsl",
}
_ENRICHMENT_PATTERN = re.compile(
    r"\b(?:enrich\w*|enrichis\w*|enrichir|enrichment|coupl\w*|compl[eè]te\w*)\b",
    re.IGNORECASE,
)
_GEOGRAPHY_PATTERN = re.compile(
    r"\b(?:zone|r[eé]gion|spatial\w*|g[eé]ograph\w*|latitude|longitude|bbox|"
    r"labrador|baffin|arctique|arctic)\b",
    re.IGNORECASE,
)
_TAXONOMY_PATTERN = re.compile(
    r"\b(?:taxon\w*|taxa|taxonomi\w*|esp[eè]ce\w*|species)\b",
    re.IGNORECASE,
)
_SQL_COPY_PATTERN = re.compile(
    r"\b(?:copie\w*|copy|export\w*|analyse\w*|analy[sz]\w*)\b",
    re.IGNORECASE,
)
_ECOTAXA_INTENT_PATTERNS: tuple[tuple[ToolExposureGroup, re.Pattern[str]], ...] = (
    (
        "ecotaxa_export",
        re.compile(
            r"\b(?:export\w*|t[eé]l[eé]charg\w*|download\w*|extra\w*|charge\s+les\s+donn[eé]es)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ecotaxa_schema",
        re.compile(
            r"\b(?:sch[eé]ma|schema|colonne\w*|column\w*|type\w*|compatib\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ecotaxa_audit",
        re.compile(
            r"\b(?:audit\w*|couverture|coverage|disponibilit[eé]|availability|"
            r"synth[eè]se\w*|r[eé]sum\w*|summar\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ecotaxa_taxonomy",
        re.compile(
            r"\b(?:taxon\w*|taxa|taxonomi\w*|esp[eè]ce\w*|species|compte\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ecotaxa_geo_time",
        re.compile(
            r"\b(?:zone|r[eé]gion|spatial\w*|ann[eé]e\w*|year\w*|p[eé]riode\w*|"
            r"date\w*|station\w*|labrador|baffin|arctique|arctic)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ecotaxa_samples",
        re.compile(
            r"\b(?:sample\w*|[eé]chantillon\w*|d[eé]ploiement\w*|deployment\w*)\b",
            re.IGNORECASE,
        ),
    ),
)
_GROUP_ORDER: tuple[ToolExposureGroup, ...] = (
    "core",
    "file_analysis",
    "geography",
    "taxonomy",
    "visualization",
    "deliverable",
    "enrichment_ecopart",
    "enrichment_amundsen",
    "enrichment_bio_oracle",
    "enrichment_ogsl",
    "sql_workspace",
    "ecotaxa_discovery",
    "ecotaxa_samples",
    "ecotaxa_geo_time",
    "ecotaxa_taxonomy",
    "ecotaxa_schema",
    "ecotaxa_audit",
    "ecotaxa_export",
)


@dataclass(frozen=True)
class TurnSignals:
    """Locally-derived signals used only inside an authorized source scope."""

    latest_user_text: str
    enrichment_requested: bool
    geography_requested: bool
    taxonomy_requested: bool
    sql_copy_requested: bool
    successful_tools_this_turn: tuple[str, ...]
    successful_skills_this_turn: tuple[str, ...]
    ecotaxa_intents: tuple[ToolExposureGroup, ...]


@dataclass(frozen=True)
class ToolExposureDecision:
    """Stable allowlist and audit explanation for one model call."""

    tool_names: tuple[str, ...]
    active_groups: tuple[ToolExposureGroup, ...]
    reasons: tuple[str, ...]
    dropped_tool_names: tuple[str, ...]
    source_decision: SourceDecision
    max_tools: int
    policy_overflow: bool = False


def build_turn_signals(messages: list[Any]) -> TurnSignals:
    """Extract deterministic intent and successful current-turn workflow state."""

    text = latest_user_text(messages)
    calls = successful_calls_in_current_turn(messages)
    skills = tuple(
        str(call.args.get("skill_name") or "")
        for call in calls
        if call.name == "load_skill"
    )
    ecotaxa_intents = tuple(
        group for group, pattern in _ECOTAXA_INTENT_PATTERNS if pattern.search(text)
    )[:2]
    return TurnSignals(
        latest_user_text=text,
        enrichment_requested=bool(_ENRICHMENT_PATTERN.search(text)),
        geography_requested=bool(_GEOGRAPHY_PATTERN.search(text)),
        taxonomy_requested=bool(_TAXONOMY_PATTERN.search(text)),
        sql_copy_requested=bool(_SQL_COPY_PATTERN.search(text)),
        successful_tools_this_turn=tuple(call.name for call in calls),
        successful_skills_this_turn=skills,
        ecotaxa_intents=ecotaxa_intents,
    )


def _ordered_names(
    available_names: tuple[str, ...],
    policies: Mapping[str, ToolPolicy],
    active_groups: Collection[ToolExposureGroup],
) -> tuple[str, ...]:
    available = set(available_names)
    selected: list[str] = [name for name in _CORE_TOOL_NAMES if name in available]
    for group in _GROUP_ORDER:
        if group == "core" or group not in active_groups:
            continue
        selected.extend(
            name
            for name in available_names
            if name not in selected
            and name in policies
            and policies[name].exposure_group == group
        )
    return tuple(selected)


def decide_tool_exposure(
    available_names: Collection[str],
    policies: Mapping[str, ToolPolicy],
    turn_context: TurnContext,
    source_decision: SourceDecision,
    messages: list[Any],
    *,
    max_tools: int = 15,
) -> ToolExposureDecision:
    """Return the deterministic tool allowlist for the current model call."""

    names = tuple(dict.fromkeys(str(name) for name in available_names if name in policies))
    signals = build_turn_signals(messages)
    groups: list[ToolExposureGroup] = ["core"]
    reasons = ["permanent core"]

    if turn_context.file_loaded:
        groups.append("file_analysis")
        reasons.append("active dataset")
    if signals.geography_requested:
        groups.append("geography")
        reasons.append("geography requested")
    if signals.taxonomy_requested and "ecotaxa" not in source_decision.authorized_sources:
        groups.append("taxonomy")
        reasons.append("taxonomy requested")

    skills = signals.successful_skills_this_turn
    if len(skills) >= 2 and skills[-2:] == ("graph_planner", "graph_writer"):
        groups.append("visualization")
        reasons.append("graph planner and writer succeeded this turn")
    if skills and skills[-1] == "deliverable_writer":
        groups.append("deliverable")
        reasons.append("deliverable writer succeeded this turn")

    authorized = set(source_decision.authorized_sources)
    if turn_context.file_loaded and signals.enrichment_requested:
        for source in ("ecopart", "amundsen", "bio_oracle", "ogsl"):
            if source in authorized:
                groups.append(_ENRICHMENT_GROUP_BY_SOURCE[source])
                reasons.append(f"explicit {source} enrichment")

    if "sql" in authorized:
        groups.append("sql_workspace")
        reasons.append(
            "explicit SQL copy" if signals.sql_copy_requested else "authorized SQL workspace"
        )

    if "ecotaxa" in authorized:
        ecotaxa_groups = signals.ecotaxa_intents or ("ecotaxa_discovery",)
        groups.extend(ecotaxa_groups)
        reasons.append("authorized EcoTaxa intent")

    active_groups = tuple(dict.fromkeys(groups))
    selected = _ordered_names(names, policies, active_groups)
    overflow = len(selected) > max_tools
    if overflow:
        fallback_groups: tuple[ToolExposureGroup, ...] = ("core",)
        discovery_fallback = _ordered_names(
            names, policies, ("core", "ecotaxa_discovery")
        )
        if "ecotaxa" in authorized and len(discovery_fallback) <= max_tools:
            fallback_groups = ("core", "ecotaxa_discovery")
            selected = discovery_fallback
        else:
            selected = _ordered_names(names, policies, fallback_groups)
        active_groups = fallback_groups
        reasons.append("policy overflow fallback")

    selected_set = set(selected)
    return ToolExposureDecision(
        tool_names=selected,
        active_groups=active_groups,
        reasons=tuple(reasons),
        dropped_tool_names=tuple(name for name in names if name not in selected_set),
        source_decision=source_decision,
        max_tools=max_tools,
        policy_overflow=overflow,
    )
