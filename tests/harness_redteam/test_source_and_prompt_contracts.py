"""Contradictions de routage actuellement portées par des sources distinctes."""

from __future__ import annotations

def test_bare_project_id_does_not_authorize_ecotaxa():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from tools.source_scope import ecotaxa_signal

    assert "A project number alone is not an EcoTaxa signal" in COPEPOD_SYSTEM_PROMPT
    assert ecotaxa_signal("résume le projet 17498") is False, (
        "source_scope.py autorise actuellement EcoTaxa avec un project_id nu, "
        "contrairement au Source Selection Gateway"
    )


def test_specialized_numeric_tool_results_do_not_require_run_pandas():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "always call `run_pandas` to produce any numeric value" not in prompt, (
        "la règle absolue contredit les tools spécialisés de count/summarize"
    )
    assert "derived" in prompt and "specialized" in prompt


def test_ogsl_enrichment_has_a_single_deterministic_rule():
    """4C: environmental_join.md must not call two different tools 'the standard'.

    `query_ogsl` (station/time/depth matching) and `enrich_with_ogsl`
    (latitude/longitude spatial matching) are distinct join strategies. The
    skill previously declared BOTH as "standard OGSL enrichment", which is the
    internal contradiction the plan's step 4C must remove.
    """
    from pathlib import Path

    text = Path("agents/skills/environmental_join.md").read_text(encoding="utf-8")
    lowered = text.lower()

    claims_query_ogsl_standard = "standard ogsl enrichment is handled inside `query_ogsl`" in lowered
    claims_enrich_ogsl_standard = "standard ogsl enrichment uses `enrich_with_ogsl`" in lowered
    assert not (claims_query_ogsl_standard and claims_enrich_ogsl_standard), (
        "environmental_join.md déclare simultanément query_ogsl ET "
        "enrich_with_ogsl comme l'enrichissement OGSL « standard »"
    )

    # The single rule must disambiguate by the join key the loaded table carries.
    assert "`query_ogsl`" in text and "`enrich_with_ogsl`" in text
    assert "station" in lowered and ("latitude" in lowered or "lat/lon" in lowered), (
        "la règle OGSL unique doit distinguer station/temps (query_ogsl) de "
        "latitude/longitude (enrich_with_ogsl)"
    )
