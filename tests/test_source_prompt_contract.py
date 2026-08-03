"""The source gateway prose is rendered from the executable policy."""

from __future__ import annotations


def test_system_prompt_embeds_generated_source_gateway_once():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from tools.source_scope import SOURCE_SELECTION_GATEWAY

    assert COPEPOD_SYSTEM_PROMPT.count("## Source Selection Gateway") == 1
    assert SOURCE_SELECTION_GATEWAY in COPEPOD_SYSTEM_PROMPT


def test_system_prompt_keeps_canonical_join_policy_and_accepts_any_loaded_file():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "EcoTaxa↔EcoPart: canonical join only" in COPEPOD_SYSTEM_PROMPT
    assert "Amundsen CTD: canonical enrichment only" in COPEPOD_SYSTEM_PROMPT
    assert "Any loaded tabular file is in scope" in COPEPOD_SYSTEM_PROMPT
    assert "never ask whether it concerns copepods" in COPEPOD_SYSTEM_PROMPT


def test_system_prompt_requires_neolabs_to_amundsen_matching_before_profile_read():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = " ".join(COPEPOD_SYSTEM_PROMPT.split())
    assert "never copy a NeoLabs cast into an Amundsen profile call" in prompt
    assert "match by latitude/longitude/time first" in prompt


def test_system_prompt_requires_comparable_abundance_before_cross_instrument_comparison():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = " ".join(COPEPOD_SYSTEM_PROMPT.split())
    assert "Cross-instrument abundance comparison" in prompt
    assert "normalize to ind./m³" in prompt
    assert "Raw object/image counts and incompatible volumes are never comparable" in prompt
    assert "FlowCam uses its own export-native concentration workflow" in prompt


def test_system_prompt_lists_french_net_uvp_audit_intents():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = " ".join(COPEPOD_SYSTEM_PROMPT.split())
    assert "analyse les correspondances filet–UVP" in prompt
    assert "cherche les profils UVP/EcoTaxa associés" in prompt
    assert "prépare une comparaison d'abondance filet–UVP" in prompt


def test_net_uvp_skill_requires_stratum_matched_and_explained_profiles():
    from pathlib import Path

    skill = Path("agents/skills/net_uvp_abundance_comparison.md").read_text()
    normalized = skill.lower()

    assert "never compare a full uvp profile with one net stratum" in normalized
    assert "same depth interval" in normalized
    assert "sum of sampled volumes" in normalized
    assert "method disclosure" in normalized
    assert "user may change" in normalized


def test_net_uvp_skill_routes_depth_comparison_through_canonical_builder():
    from pathlib import Path

    skill = Path("agents/skills/net_uvp_abundance_comparison.md").read_text()

    assert "from core.net_uvp_comparison import build_paired_depth_strata" in skill
    assert "paired_strata = build_paired_depth_strata(" in skill
    assert "comparison_calculable" in skill
    assert "depth_match_status" in skill
    assert "df_net_uvp_strata" in skill


def test_generated_gateway_documents_persistent_affinity_and_bare_ids():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    assert "A project number alone is not an EcoTaxa signal" in gateway
    assert "remains active on following turns" in gateway
    assert "newly loaded file becomes the active source" in gateway
    assert "New file -> sole source for implicit follow-ups" in gateway
    assert "names another source" in gateway


def test_gateway_names_every_selectable_external_source():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    for label in ("EcoTaxa", "EcoPart", "Amundsen CTD", "Bio-ORACLE", "OGSL", "SQL"):
        assert label in gateway


def test_ecotaxa_skill_makes_cache_sql_the_default_exploration_path():
    from pathlib import Path

    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "query_ecotaxa_cache" in navigation
    assert "GROUP BY" in navigation
    assert "df_ecotaxa_cache_query" in navigation


def test_cross_source_analysis_uses_generic_run_pandas_sandbox():
    from pathlib import Path
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    text = COPEPOD_SYSTEM_PROMPT + "\n" + Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "run_pandas" in text
    assert "persistent variable" in text
    assert "df_ecotaxa_cache_query" in text
    assert "comparison" in text


def test_ecotaxa_cache_prompt_does_not_impose_an_implicit_limit():
    from pathlib import Path

    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()

    assert "Add `LIMIT` only when" in navigation
    assert "GROUP BY" in navigation


def test_ecotaxa_skill_requires_schema_and_result_validation():
    from pathlib import Path

    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "Schema-first rule" in navigation
    assert "before writing SQL" in navigation
    assert "Never refuse a query or invent a workaround" in navigation


def test_aggregate_object_request_prefers_cache_sql_over_object_tools():
    from pathlib import Path

    skill = Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "query_ecotaxa_cache" in skill
    assert "paginated object browsing" in skill


def test_ecotaxa_prompt_distinguishes_samples_casts_and_validated_objects():
    from pathlib import Path

    prompt = __import__("agents.copepod_system_prompt", fromlist=["COPEPOD_SYSTEM_PROMPT"])
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text()
    text = f"{prompt.COPEPOD_SYSTEM_PROMPT}\n{skill}"

    assert "profile_id" in text
    assert "Never group a profile map by sample_id" in text
    assert "`nb_validated`" in text
    assert "`nb_predicted`" in text
    assert "`nb_dubious`" in text
    assert "`nb_unclassified`" in text
    assert "Stay at sample level unless" in text
    assert "Individual objects require an export plan" in text
    assert "pre-aggregate objects by `sample_id`" in text


def test_ecotaxa_sample_maps_require_a_persisted_named_dataframe():
    from pathlib import Path

    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()
    graph_writer = Path("agents/skills/graph_writer.md").read_text()
    text = f"{COPEPOD_SYSTEM_PROMPT}\n{navigation}\n{graph_writer}"
    assert "sample maps" in text
    assert "bare `df`" in text
    assert "exact saved variable" in text
    assert "exact named DataFrame" in text
