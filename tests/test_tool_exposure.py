"""Deterministic per-turn tool exposure policy (harness step 6)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tools.source_scope import SourceDecision
from tools.tool_result import success
from tools.turn_context import TurnContext


def _source_decision(*sources: str) -> SourceDecision:
    return SourceDecision(
        primary_source=sources[0] if sources else None,
        authorized_sources=tuple(sources),
        explicit_sources=tuple(source for source in sources if source != "file"),
        evidence="explicit_name" if sources else "none",
        needs_clarification=False,
        reason="fixture",
    )


def _turn(*, file_loaded: bool, sources: tuple[str, ...] = (), output_intent: str = "ambiguous") -> TurnContext:
    return TurnContext(
        thread_id="tool-exposure",
        file_loaded=file_loaded,
        active_variable="df_file_demo" if file_loaded else None,
        active_source="file:demo.tsv" if file_loaded else None,
        derived_zone_subsets=(),
        authorized_sources=sources,
        primary_source=sources[0] if sources else None,
        explicit_sources=tuple(source for source in sources if source != "file"),
        capsule="",
        output_intent=output_intent,
    )


def _decision(text: str, *, file_loaded: bool = False, sources: tuple[str, ...] = (), messages=None, max_tools: int = 15, output_intent: str = "ambiguous"):
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    history = messages or [HumanMessage(content=text)]
    return decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(file_loaded=file_loaded, sources=sources, output_intent=output_intent),
        _source_decision(*sources),
        history,
        max_tools=max_tools,
    )


def _successful_skill_messages(text: str, *skills: str):
    messages = [HumanMessage(content=text)]
    for index, skill in enumerate(skills):
        call_id = f"skill-{index}"
        call = {
            "name": "load_skill",
            "args": {"skill_name": skill},
            "id": call_id,
            "type": "tool_call",
        }
        content, artifact = success("loaded")
        messages.extend(
            [
                AIMessage(content="", tool_calls=[call]),
                ToolMessage(content=content, artifact=artifact, tool_call_id=call_id),
            ]
        )
    return messages


def test_no_state_exposes_permanent_core_and_geographic_capabilities():
    decision = _decision("Bonjour")

    assert decision.tool_names[:4] == (
        "load_file",
        "load_skill",
        "query_copepod_knowledge_base",
        "run_pandas",
    )
    assert set(decision.tool_names[4:]) == {
        "filter_dataframe_by_zone",
        "get_zone_info",
    }
    assert decision.active_groups == ("core", "geography")
    assert decision.policy_overflow is False


@pytest.mark.parametrize(
    "text",
    [
        "Baie d’Hudson",
        "Fais la même chose pour le secteur scientifique alpha",
        "Bonjour",
    ],
)
def test_geographic_capabilities_do_not_depend_on_lexical_detection(text):
    decision = _decision(text)

    assert "get_zone_info" in decision.tool_names
    assert "filter_dataframe_by_zone" in decision.tool_names
    assert "geography" in decision.active_groups


def test_run_pandas_is_permanent_sandbox_without_loaded_file():
    decision = _decision("Bonjour")

    assert "run_pandas" in decision.tool_names
    assert "run_graph" not in decision.tool_names


def test_explicit_visual_intent_exposes_graph_workflow_before_graph_skills():
    # The fixture carries the semantic decision that the runtime computes
    # before the first model call; no graph skill has been loaded yet.
    visual_context = _turn(
        file_loaded=True,
        sources=("file",),
        output_intent="visual",
    )
    indirect_request = (
        "Montre-moi où sont les stations et comment elles se répartissent au fil des années."
    )
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        visual_context,
        _source_decision("file"),
        [HumanMessage(content=indirect_request)],
    )

    assert "run_graph" in decision.tool_names
    assert "visualization" in decision.active_groups
    assert "semantic visual output requested" in decision.reasons


def test_graph_and_deliverable_execution_unlock_from_successful_current_turn_skills():
    graph_messages = _successful_skill_messages(
        "Fais une carte", "graph_planner", "graph_writer"
    )
    graph = _decision(
        "Fais une carte",
        file_loaded=True,
        sources=("file",),
        messages=graph_messages,
    )
    report_messages = _successful_skill_messages(
        "Crée un rapport", "deliverable_writer"
    )
    report = _decision(
        "Crée un rapport",
        file_loaded=True,
        sources=("file",),
        messages=report_messages,
    )

    assert "run_graph" in graph.tool_names
    assert "export_deliverable" in report.tool_names


@pytest.mark.parametrize(
    ("source", "text", "expected"),
    [
        ("ecopart", "Enrichis mon fichier avec EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
        ("amundsen", "Enrichis mon fichier avec Amundsen CTD", "enrich_with_amundsen_ctd"),
        ("bio_oracle", "Enrichis mon fichier avec Bio-ORACLE", "enrich_with_bio_oracle"),
        ("ogsl", "Enrichis mon fichier avec OGSL", "enrich_with_ogsl"),
    ],
)
def test_explicit_enrichment_exposes_one_canonical_source_tool(source, text, expected):
    decision = _decision(text, file_loaded=True, sources=("file", source))

    source_tools = [
        name
        for name in decision.tool_names
        if name == expected or source in name or (source == "amundsen" and "amundsen" in name)
    ]
    assert expected in decision.tool_names
    assert source_tools == [expected]


def test_explicit_enrichment_source_wins_over_stale_authorized_sources():
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    source_decision = SourceDecision(
        primary_source="file",
        authorized_sources=("file", "ecotaxa", "ecopart", "amundsen"),
        explicit_sources=("amundsen",),
        evidence="explicit_name",
        needs_clarification=False,
        reason="stale affinity fixture",
    )
    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(
            file_loaded=True,
            sources=source_decision.authorized_sources,
        ),
        source_decision,
        [HumanMessage(content="Enrichis le sample avec Amundsen.")],
    )

    assert decision.policy_overflow is False
    assert "enrich_with_amundsen_ctd" in decision.tool_names
    assert "enrich_ecotaxa_with_ecopart_remote" not in decision.tool_names
    assert not any(group.startswith("ecotaxa_") for group in decision.active_groups)
    # file_analysis actif (fichier chargé) → run_pandas + split_dataframe_by_zone.
    assert "split_dataframe_by_zone" in decision.tool_names
    assert len(decision.tool_names) == 8


@pytest.mark.parametrize(
    ("source", "text", "canonical"),
    [
        ("ecopart", "Utilise EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
        ("amundsen", "Utilise Amundsen CTD", "enrich_with_amundsen_ctd"),
        ("bio_oracle", "Utilise Bio-ORACLE", "enrich_with_bio_oracle"),
        ("ogsl", "Utilise OGSL", "enrich_with_ogsl"),
    ],
)
def test_source_name_without_enrichment_keeps_source_tools_hidden(source, text, canonical):
    decision = _decision(text, file_loaded=True, sources=("file", source))

    assert canonical not in decision.tool_names


def test_enrichment_without_loaded_file_keeps_canonical_tool_hidden():
    decision = _decision(
        "Enrichis avec Bio-ORACLE",
        file_loaded=False,
        sources=("bio_oracle",),
    )

    assert "enrich_with_bio_oracle" not in decision.tool_names


@pytest.mark.parametrize(
    ("text", "expected_group", "expected_tool"),
    [
        ("Explore EcoTaxa", "ecotaxa_discovery", "find_ecotaxa_projects"),
        ("Liste les samples EcoTaxa du projet", "ecotaxa_samples", "get_ecotaxa_sample"),
        ("Résous la station RA76 dans EcoTaxa", "ecotaxa_discovery", "resolve_ecotaxa_sample"),
        ("Montre les objets du sample EcoTaxa 14853000001", "ecotaxa_objects", "list_ecotaxa_sample_objects"),
        ("Montre les objets du sample 14853000001 sans l'exporter", "ecotaxa_objects", "list_ecotaxa_sample_objects"),
        ("Trouve les samples EcoTaxa au Labrador en 2020", "ecotaxa_geo_time", "find_ecotaxa_samples_in_region"),
        ("Compte les taxons EcoTaxa", "ecotaxa_taxonomy", "count_ecotaxa_taxa"),
        ("Inspecte le schéma du projet EcoTaxa", "ecotaxa_schema", "inspect_ecotaxa_project_schema"),
        ("Audite la couverture EcoTaxa", "ecotaxa_audit", "audit_ecotaxa_spatial_coverage"),
        ("Résume maintenant le projet 17498", "ecotaxa_audit", "summarize_ecotaxa_project"),
        ("Exporte les données EcoTaxa", "ecotaxa_export", "query_ecotaxa"),
    ],
)
def test_ecotaxa_selects_only_the_requested_subtoolset(text, expected_group, expected_tool):
    decision = _decision(text, sources=("ecotaxa",))

    assert expected_group in decision.active_groups
    assert expected_tool in decision.tool_names
    assert len(decision.tool_names) <= 15


def test_ecotaxa_does_not_always_include_geo_time_for_a_project_audit():
    decision = _decision("Audite le projet EcoTaxa", sources=("ecotaxa",))

    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "ecotaxa_audit" in decision.active_groups
    assert len(decision.tool_names) <= 15


def test_ecotaxa_exploration_keeps_discovery_and_multiple_intents():
    decision = _decision(
        "Montre le projet 1165 et ses samples de la campagne X",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_discovery" in decision.active_groups
    assert "ecotaxa_samples" in decision.active_groups
    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "preview_ecotaxa_project" in decision.tool_names
    assert "list_ecotaxa_campaigns" in decision.tool_names
    assert "list_ecotaxa_project_samples" in decision.tool_names


def test_ecotaxa_does_not_expose_geo_time_for_non_geographic_exploration():
    decision = _decision("Le cache EcoTaxa est-il à jour ?", sources=("ecotaxa",))

    assert "ecotaxa_discovery" in decision.active_groups
    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "get_ecotaxa_cache_status" in decision.tool_names


def test_visual_overflow_keeps_graph_and_ecotaxa_discovery():
    decision = _decision(
        "Affiche les samples EcoTaxa de la Baie de Baffin sur une carte",
        sources=("ecotaxa",),
        output_intent="visual",
    )

    assert decision.policy_overflow is True
    assert "run_graph" in decision.tool_names
    assert "list_ecotaxa_campaigns" in decision.tool_names
    assert "find_ecotaxa_samples_in_region" in decision.tool_names


def test_ecotaxa_overflow_keeps_central_cache_query():
    decision = _decision(
        "Explore les samples EcoTaxa par projet, station, date et instrument",
        sources=("ecotaxa",),
    )

    assert decision.policy_overflow is True
    assert "query_ecotaxa_cache" in decision.tool_names


def test_global_region_ranking_keeps_spatial_ranker_during_overflow():
    decision = _decision(
        "Dans tout le cache EcoTaxa, classe les zones et écorégions par nombre de samples",
        sources=("ecotaxa",),
    )

    assert decision.policy_overflow is True
    assert "rank_ecotaxa_samples_by_region" in decision.tool_names


def test_negated_export_does_not_expose_ecotaxa_export_tools():
    decision = _decision(
        "Montre le projet 1165 et ses samples, ne fais aucun export",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_export" not in decision.active_groups
    assert "query_ecotaxa" not in decision.tool_names


def test_ecotaxa_is_never_enabled_by_a_bare_identifier():
    decision = _decision("Résume le projet 17498")

    assert not any(name.startswith(("find_ecotaxa", "query_ecotaxa", "summarize_ecotaxa")) for name in decision.tool_names)


def test_hidden_legacy_tools_are_never_exposed():
    from tools.tool_catalog import TOOL_POLICIES

    decision = _decision(
        "Enrichis mon fichier avec Bio-ORACLE",
        file_loaded=True,
        sources=("file", "bio_oracle"),
    )
    hidden = {
        name
        for name, policy in TOOL_POLICIES.items()
        if policy.exposure_group == "hidden_legacy"
    }

    assert hidden.isdisjoint(decision.tool_names)


def test_overflow_falls_back_to_the_core_when_discovery_does_not_fit():
    decision = _decision("Explore EcoTaxa", sources=("ecotaxa",), max_tools=4)

    assert decision.policy_overflow is True
    assert decision.tool_names == (
        "load_file",
        "load_skill",
        "query_copepod_knowledge_base",
    )
    assert len(decision.tool_names) <= 4
