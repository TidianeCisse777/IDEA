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
    "run_pandas",
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
_TAXONOMY_PATTERN = re.compile(
    r"\b(?:taxon\w*|taxa|taxonomi\w*|esp[eè]ce\w*|species)\b",
    re.IGNORECASE,
)
_SQL_COPY_PATTERN = re.compile(
    r"\b(?:copie\w*|copy|export\w*|analyse\w*|analy[sz]\w*)\b",
    re.IGNORECASE,
)
# A negated export ("sans l'exporter", "ne pas exporter", "without exporting")
# must NOT trigger the export intent — otherwise object-browse requests that
# explicitly refuse export get routed to the heavy export path.
_EXPORT_NEGATION = re.compile(
    r"\b(?:sans|pas|non|jamais|without|no)\b[^.]{0,25}?"
    r"\b(?:export\w*|t[eé]l[eé]charg\w*|download\w*)\b",
    re.IGNORECASE,
)
# "Prépare l'export ... sans télécharger" is a safe dry-run request, not a
# refusal to export. It must keep the export tool visible so the agent can
# call it with confirmed=False and return its plan.
_EXPORT_PLANNING = re.compile(
    r"\b(?:pr[eé]par\w*|plan\w*|dry[- ]?run)\b",
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
        "ecotaxa_samples",
        re.compile(
            r"\b(?:sample\w*|[eé]chantillon\w*|d[eé]ploiement\w*|deployment\w*)\b",
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
            r"\b(?:taxon\w*|taxa|taxonomi\w*|esp[eè]ce\w*|species|"
            r"compte\w*|combien|how\s+many)\b",
            re.IGNORECASE,
        ),
    ),
)
_ECOTAXA_GEO_TERMS = (
    "zone", "région", "region", "baie", "bassin", "station", "carte",
    "latitude", "longitude", "coordonnée", "coordonne", "géographique",
    "geographique", "labrador", "baffin", "ungava", "hudson",
)
_GROUP_PRIORITY_NAMES: dict[ToolExposureGroup, tuple[str, ...]] = {
    "file_analysis": (
        "run_pandas", "find_uvp_matches_for_net_table", "split_dataframe_by_zone",
    ),
    "ecotaxa_discovery": (
        "query_ecotaxa_cache", "list_ecotaxa_cache_tables",
        "describe_ecotaxa_cache_table",
    ),
    "ecotaxa_geo_time": (
        "find_ecotaxa_samples_in_region", "combine_ecotaxa_selections",
        "group_ecotaxa_samples_by_year",
        "find_ecotaxa_projects_in_region", "group_ecotaxa_project_samples_by_region",
        "rank_ecotaxa_samples_by_region",
    ),
    "ecotaxa_samples": (
        "summarize_ecotaxa_sample_deployment",
    ),
}
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
    "ecotaxa_export",
    "ecotaxa_samples",
    "ecotaxa_objects",
    "ecotaxa_geo_time",
    "ecotaxa_taxonomy",
    "ecotaxa_schema",
    "ecotaxa_audit",
)


@dataclass(frozen=True)
class TurnSignals:
    """Locally-derived signals used only inside an authorized source scope."""

    latest_user_text: str
    enrichment_requested: bool
    taxonomy_requested: bool
    sql_copy_requested: bool
    geographic_requested: bool
    successful_tools_this_turn: tuple[str, ...]
    successful_skills_this_turn: tuple[str, ...]
    ecotaxa_intents: tuple[ToolExposureGroup, ...]
    previous_visual_artifact: bool
    regional_ranking_requested: bool
    multi_zone_requested: bool
    cross_source_compare_requested: bool


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
    previous_visual_artifact = any(
        "![" in str(getattr(message, "content", ""))
        and "/graphs/" in str(getattr(message, "content", ""))
        for message in messages
    )
    skills = tuple(
        str(call.args.get("skill_name") or "")
        for call in calls
        if call.name == "load_skill"
    )
    normalized_text = text.casefold()
    regional_ranking_requested = (
        "classe" in normalized_text
        and ("zone" in normalized_text or "écorégion" in normalized_text or "ecoregion" in normalized_text)
        and ("sample" in normalized_text or "échantillon" in normalized_text)
        and ("nombre" in normalized_text or "moins" in normalized_text or "plus" in normalized_text)
    )
    multi_zone_requested = (
        any(term in normalized_text for term in _ECOTAXA_GEO_TERMS)
        and (" et " in normalized_text or "plusieurs" in normalized_text)
    )
    cross_source_compare_requested = (
        "fichier" in normalized_text
        and any(term in normalized_text for term in ("correspond", "compar", "match"))
    )
    export_requested = bool(_ECOTAXA_INTENT_PATTERNS[0][1].search(text))
    export_dry_run_requested = export_requested and bool(_EXPORT_PLANNING.search(text))
    export_negated = not export_dry_run_requested and (
        bool(_EXPORT_NEGATION.search(text))
        or any(
            phrase in normalized_text
            for phrase in ("aucun export", "aucune exportation", "no export")
        )
    )
    ecotaxa_intents = tuple(
        group for group, pattern in _ECOTAXA_INTENT_PATTERNS
        if pattern.search(text)
        and not (group == "ecotaxa_export" and export_negated)
    )
    if "ecotaxa_export" in ecotaxa_intents:
        # An export request takes precedence over page-by-page object browsing.
        ecotaxa_intents = tuple(
            group for group in ecotaxa_intents if group != "ecotaxa_objects"
        )
    return TurnSignals(
        latest_user_text=text,
        enrichment_requested=bool(_ENRICHMENT_PATTERN.search(text)),
        taxonomy_requested=bool(_TAXONOMY_PATTERN.search(text)),
        sql_copy_requested=bool(_SQL_COPY_PATTERN.search(text)),
        geographic_requested=any(term in normalized_text for term in _ECOTAXA_GEO_TERMS),
        successful_tools_this_turn=tuple(call.name for call in calls),
        successful_skills_this_turn=skills,
        ecotaxa_intents=ecotaxa_intents,
        previous_visual_artifact=previous_visual_artifact,
        regional_ranking_requested=regional_ranking_requested,
        multi_zone_requested=multi_zone_requested,
        cross_source_compare_requested=cross_source_compare_requested,
    )


def _ordered_names(
    available_names: tuple[str, ...],
    policies: Mapping[str, ToolPolicy],
    active_groups: Collection[ToolExposureGroup],
    group_limits: Mapping[ToolExposureGroup, int] | None = None,
) -> tuple[str, ...]:
    available = set(available_names)
    selected: list[str] = [name for name in _CORE_TOOL_NAMES if name in available]
    for group in _GROUP_ORDER:
        if group == "core" or group not in active_groups:
            continue
        group_names = [
            name for name in available_names
            if name not in selected
            and name in policies
            and policies[name].exposure_group == group
        ]
        priorities = _GROUP_PRIORITY_NAMES.get(group, ())
        group_names.sort(key=lambda name: priorities.index(name) if name in priorities else len(priorities))
        if group_limits and group in group_limits:
            group_names = group_names[:group_limits[group]]
        selected.extend(group_names)
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
    groups: list[ToolExposureGroup] = ["core", "geography"]
    reasons = ["permanent core", "permanent geographic capabilities"]

    if turn_context.file_loaded:
        groups.append("file_analysis")
        reasons.append("active dataset")
    if signals.taxonomy_requested and "ecotaxa" not in source_decision.authorized_sources:
        groups.append("taxonomy")
        reasons.append("taxonomy requested")

    skills = signals.successful_skills_this_turn
    if turn_context.output_intent == "visual":
        groups.append("visualization")
        reasons.append("semantic visual output requested")
    elif len(skills) >= 2 and skills[-2:] == ("graph_planner", "graph_writer"):
        groups.append("visualization")
        reasons.append("graph planner and writer succeeded this turn")
    elif signals.previous_visual_artifact:
        groups.append("visualization")
        reasons.append("previous visual artifact available for follow-up")
    if skills and skills[-1] == "deliverable_writer":
        groups.append("deliverable")
        reasons.append("deliverable writer succeeded this turn")

    authorized = set(source_decision.authorized_sources)
    explicit_enrichment_sources = tuple(
        source
        for source in _ENRICHMENT_GROUP_BY_SOURCE
        if source in source_decision.explicit_sources
    )
    focused_enrichment = bool(
        turn_context.file_loaded
        and signals.enrichment_requested
        and explicit_enrichment_sources
    )
    if turn_context.file_loaded and signals.enrichment_requested:
        enrichment_sources = explicit_enrichment_sources or tuple(
            source for source in _ENRICHMENT_GROUP_BY_SOURCE if source in authorized
        )
        for source in enrichment_sources:
            if source in authorized:
                groups.append(_ENRICHMENT_GROUP_BY_SOURCE[source])
                reasons.append(f"current explicit {source} enrichment")

    if "sql" in authorized and not focused_enrichment:
        groups.append("sql_workspace")
        reasons.append(
            "explicit SQL copy" if signals.sql_copy_requested else "authorized SQL workspace"
        )

    if "ecotaxa" in authorized and not focused_enrichment:
        ecotaxa_groups = ["ecotaxa_discovery"]
        if signals.geographic_requested:
            ecotaxa_groups.append("ecotaxa_geo_time")
        ecotaxa_groups.extend(signals.ecotaxa_intents)
        groups.extend(ecotaxa_groups)
        reasons.append("authorized EcoTaxa intent")
    # Keep the dedicated comparison route visible from the wording itself. A
    # file may be present in the session capsule even when the active source
    # snapshot was replaced by a preceding EcoTaxa query.
    if signals.cross_source_compare_requested:
        groups.append("file_analysis")
        reasons.append("cross-source file/EcoTaxa comparison")

    active_groups = tuple(dict.fromkeys(groups))
    selected = _ordered_names(names, policies, active_groups)
    overflow = len(selected) > max_tools
    if overflow:
        if "visualization" in active_groups:
            geo_visual_fallback = ("ecotaxa_geo_time",) if signals.geographic_requested else ()
            fallback_groups = (
                "core",
                "file_analysis" if signals.cross_source_compare_requested else "geography",
                "geography", "visualization", "ecotaxa_discovery",
                *geo_visual_fallback,
                *signals.ecotaxa_intents,
            )
        elif "ecotaxa" in authorized:
            geo_fallback = ("ecotaxa_geo_time",) if signals.geographic_requested else ()
            fallback_groups = tuple(
                group for group in (
                    "core", "file_analysis", "geography", "ecotaxa_discovery",
                    *geo_fallback,
                    *signals.ecotaxa_intents,
                )
                if group in active_groups
            )
        else:
            fallback_groups = ("core",)
        fallback_limits: dict[ToolExposureGroup, int] = {
            # Always keep all 3 ecotaxa_discovery tools — schema-first rule
            # requires list_ecotaxa_cache_tables and describe_ecotaxa_cache_table
            # to be reachable whenever the agent may need to verify a column.
            "ecotaxa_discovery": 3,
        }
        if turn_context.file_loaded:
            # Always guarantee run_pandas + find_uvp_matches_for_net_table.
            fallback_limits["file_analysis"] = 2
        if signals.cross_source_compare_requested:
            fallback_limits["file_analysis"] = max(fallback_limits.get("file_analysis", 0), 2)
        if "ecotaxa_geo_time" in fallback_groups:
            fallback_limits["ecotaxa_geo_time"] = 2 if signals.multi_zone_requested else 1
        for intent in signals.ecotaxa_intents:
            fallback_limits[intent] = 4
        selected = _ordered_names(names, policies, fallback_groups, fallback_limits)
        # Hard guarantee: schema inspection tools must survive any overflow when
        # EcoTaxa is authorized — the schema-first rule requires them to be
        # reachable without needing to load a skill first.
        if "ecotaxa" in authorized:
            _schema_tools = ("list_ecotaxa_cache_tables", "describe_ecotaxa_cache_table")
            for _st in _schema_tools:
                if _st in names and _st not in selected and len(selected) < max_tools:
                    selected = (*selected, _st)
        if signals.regional_ranking_requested:
            ranker = "rank_ecotaxa_samples_by_region"
            if ranker in names and ranker not in selected:
                replacement = next(
                    (
                        name for name in selected
                        if policies[name].exposure_group == "ecotaxa_geo_time"
                    ),
                    None,
                )
                if replacement is not None:
                    selected = tuple(ranker if name == replacement else name for name in selected)
                elif len(selected) < max_tools:
                    selected = (*selected, ranker)
        if len(selected) > max_tools and "ecotaxa" in authorized:
            selected = tuple(selected[:max_tools])
        if max_tools <= 4:
            selected = _ordered_names(names, policies, ("core",))
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
