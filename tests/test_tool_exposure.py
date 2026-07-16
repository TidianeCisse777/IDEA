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


def _turn(*, file_loaded: bool, sources: tuple[str, ...] = ()) -> TurnContext:
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
    )


def _decision(text: str, *, file_loaded: bool = False, sources: tuple[str, ...] = (), messages=None, max_tools: int = 15):
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    history = messages or [HumanMessage(content=text)]
    return decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(file_loaded=file_loaded, sources=sources),
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


def test_no_state_exposes_only_the_permanent_core():
    decision = _decision("Bonjour")

    assert decision.tool_names == (
        "load_file",
        "load_skill",
        "query_copepod_knowledge_base",
    )
    assert decision.active_groups == ("core",)
    assert decision.policy_overflow is False


def test_loaded_file_adds_pandas_but_not_graph_rendering():
    decision = _decision("Calcule la moyenne", file_loaded=True, sources=("file",))

    assert "run_pandas" in decision.tool_names
    assert "run_graph" not in decision.tool_names


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
