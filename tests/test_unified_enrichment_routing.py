"""Source preference and free canonical-tool exposure contracts."""

import pytest

from tools.source_scope import SourceAffinity, SourceDecision, decide_source
from tools.tool_catalog import TOOL_POLICIES
from tools.tool_exposure import decide_tool_exposure


ENRICHMENT_CASES = (
    ("ecopart", "EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
    ("amundsen", "Amundsen", "enrich_with_amundsen_ctd"),
    ("bio_oracle", "Bio-ORACLE", "enrich_with_bio_oracle"),
    ("ogsl", "OGSL", "enrich_with_ogsl"),
)


@pytest.mark.parametrize("source,label,canonical_tool", ENRICHMENT_CASES)
def test_explicit_enrichment_replaces_polluted_affinity(
    source, label, canonical_tool
):
    affinity = SourceAffinity(
        active_sources=("file", "ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl"),
        evidence="explicit_name",
        origin_user_text="Anciennes sources",
        updated_at="2026-07-16T12:00:00+00:00",
    )

    decision = decide_source(
        f"Enrichis le sample avec {label}.", affinity=affinity, file_loaded=True
    )

    assert decision.primary_source == source
    assert decision.authorized_sources == (source, "file")
    assert canonical_tool in TOOL_POLICIES


def test_source_preference_never_hides_canonical_tools():
    source_decision = SourceDecision(
        primary_source="file",
        authorized_sources=("file",),
        explicit_sources=(),
        evidence="file_loaded",
        needs_clarification=False,
        reason="fixture",
    )
    exposure = decide_tool_exposure(
        TOOL_POLICIES,
        TOOL_POLICIES,
        turn_context=None,
        source_decision=source_decision,
        messages=[],
    )

    assert set(exposure.tool_names) == set(TOOL_POLICIES)
    assert exposure.dropped_tool_names == ()
