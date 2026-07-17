"""Unified explicit-enrichment contract across every supported source."""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from tools.source_scope import SourceAffinity, SourceDecision, decide_source
from tools.tool_catalog import TOOL_POLICIES
from tools.tool_exposure import decide_tool_exposure
from tools.turn_context import TurnContext


ENRICHMENT_CASES = (
    ("ecopart", "EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
    ("amundsen", "Amundsen", "enrich_with_amundsen_ctd"),
    ("bio_oracle", "Bio-ORACLE", "enrich_with_bio_oracle"),
    ("ogsl", "OGSL", "enrich_with_ogsl"),
)


@pytest.mark.parametrize("source,label,canonical_tool", ENRICHMENT_CASES)
def test_explicit_enrichment_replaces_polluted_affinity_for_every_source(
    source,
    label,
    canonical_tool,
):
    affinity = SourceAffinity(
        active_sources=("file", "ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl"),
        evidence="explicit_name",
        origin_user_text="Anciennes sources",
        updated_at="2026-07-16T12:00:00+00:00",
    )

    decision = decide_source(
        f"Enrichis le sample avec {label}.",
        affinity=affinity,
        file_loaded=True,
    )

    assert decision.authorized_sources == ("file", source)
    assert decision.explicit_sources == (source,)


@pytest.mark.parametrize("source,label,canonical_tool", ENRICHMENT_CASES)
def test_explicit_enrichment_exposes_only_named_canonical_tool_despite_pollution(
    source,
    label,
    canonical_tool,
):
    authorized = ("file", "ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl")
    source_decision = SourceDecision(
        primary_source="file",
        authorized_sources=authorized,
        explicit_sources=(source,),
        evidence="explicit_name",
        needs_clarification=False,
        reason="polluted affinity fixture",
    )
    turn = TurnContext(
        thread_id="unified-enrichment",
        file_loaded=True,
        active_variable="df_active_sample",
        active_source="file:sample.tsv",
        derived_zone_subsets=(),
        authorized_sources=authorized,
        primary_source="file",
        explicit_sources=(source,),
        capsule="",
    )

    exposure = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        turn,
        source_decision,
        [HumanMessage(content=f"Enrichis le sample avec {label}.")],
    )
    exposed_enrichments = {
        "enrich_ecotaxa_with_ecopart_remote",
        "enrich_with_amundsen_ctd",
        "enrich_with_bio_oracle",
        "enrich_with_ogsl",
    }.intersection(exposure.tool_names)

    assert exposed_enrichments == {canonical_tool}
    assert not any(group.startswith("ecotaxa_") for group in exposure.active_groups)
    assert exposure.policy_overflow is False
    # file_analysis actif (fichier chargé) → run_pandas + split_dataframe_by_zone.
    assert "split_dataframe_by_zone" in exposure.tool_names
    assert len(exposure.tool_names) == 8


def test_system_prompt_defines_one_explicit_enrichment_contract_for_all_sources():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "ecopart, amundsen ctd, ogsl, or bio-oracle" in prompt
    assert "call the named source's canonical enrichment capability directly" in prompt
    assert "ecopart always starts with its dry-run" in prompt
    assert "bio-oracle requires confirmation" in prompt


@pytest.mark.parametrize(
    "filename,canonical_tool,forbidden_legacy",
    (
        ("amundsen_ctd_query.md", "enrich_with_amundsen_ctd", "enrich_loaded_table_with_amundsen_ctd"),
        ("bio_oracle_query.md", "enrich_with_bio_oracle", "couple_zooplankton_bio_oracle"),
        ("ecopart_query.md", "enrich_ecotaxa_with_ecopart_remote", "query_ecotaxa"),
        ("ogsl_query.md", "enrich_with_ogsl", "query_ogsl"),
    ),
)
def test_source_skill_uses_only_the_canonical_enrichment_path(
    filename,
    canonical_tool,
    forbidden_legacy,
):
    skill = (Path("agents/skills") / filename).read_text(encoding="utf-8").lower()

    assert canonical_tool.lower() in skill
    assert forbidden_legacy.lower() not in skill
    assert "current explicit enrichment request" in skill


def test_ecopart_skill_preserves_dry_run_then_confirmation_sequence():
    skill = Path("agents/skills/ecopart_query.md").read_text(encoding="utf-8").lower()

    assert "confirmed=false" in skill
    assert "confirmed=true" in skill
    assert "same canonical enrichment" in skill


def test_ogsl_skill_is_bound_to_source_policy_and_catalog():
    from tools.source_scope import source_for_tool_call

    assert source_for_tool_call(
        "load_skill",
        {"skill_name": "ogsl_query"},
        TOOL_POLICIES,
    ) == "ogsl"
    assert TOOL_POLICIES["enrich_with_ogsl"].required_skill == "ogsl_query"
