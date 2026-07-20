"""The source gateway prose is rendered from the executable policy."""

from __future__ import annotations


def test_system_prompt_embeds_generated_source_gateway_once():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from tools.source_scope import SOURCE_SELECTION_GATEWAY

    assert COPEPOD_SYSTEM_PROMPT.count("## Source Selection Gateway") == 1
    assert SOURCE_SELECTION_GATEWAY in COPEPOD_SYSTEM_PROMPT


def test_generated_gateway_documents_persistent_affinity_and_bare_ids():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    assert "A project number alone is not an EcoTaxa signal" in gateway
    assert "remains active on following turns" in gateway
    assert "newly loaded file becomes the active source" in gateway
    assert "becomes the sole source for implicit follow-ups" in gateway
    assert "names another source" in gateway


def test_gateway_names_every_selectable_external_source():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    for label in ("EcoTaxa", "EcoPart", "Amundsen CTD", "Bio-ORACLE", "OGSL", "SQL"):
        assert label in gateway


def test_ecotaxa_prompt_makes_cache_sql_the_default_exploration_path():
    from pathlib import Path

    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "query_ecotaxa_cache" in COPEPOD_SYSTEM_PROMPT
    assert "GROUP BY" in COPEPOD_SYSTEM_PROMPT
    assert "df_ecotaxa_cache_query" in COPEPOD_SYSTEM_PROMPT
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "query_ecotaxa_cache" in navigation


def test_cross_source_analysis_uses_generic_run_pandas_sandbox():
    from pathlib import Path
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    text = COPEPOD_SYSTEM_PROMPT + "\n" + Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "run_pandas" in text
    assert "loaded_file" in text
    assert "df_file_*" in text
    assert "df_ecotaxa_cache_query" in text
    assert "dedicated comparison tool" in text


def test_ecotaxa_cache_prompt_does_not_impose_an_implicit_limit():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from pathlib import Path

    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text()

    prompt_text = f"{COPEPOD_SYSTEM_PROMPT}\n{navigation}"
    assert "sans LIMIT implicite" in prompt_text
    assert "résultat complet" in prompt_text
    assert "GROUP BY" in navigation


def test_aggregate_object_request_prefers_cache_sql_over_object_tools():
    from pathlib import Path

    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "global aggregation" in COPEPOD_SYSTEM_PROMPT
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text()
    assert "query_ecotaxa_cache" in skill
    assert "paginated object browsing" in skill


def test_ecotaxa_prompt_distinguishes_samples_casts_and_validated_objects():
    from pathlib import Path

    prompt = __import__("agents.copepod_system_prompt", fromlist=["COPEPOD_SYSTEM_PROMPT"])
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text()
    text = f"{prompt.COPEPOD_SYSTEM_PROMPT}\n{skill}"

    assert "profile_id" in text
    assert "never use `sample_id` as a proxy for a cast" in text
    assert "samples_cache.nb_validated" in text
    assert "samples_cache.nb_predicted" in text
    assert "samples_cache.nb_dubious" in text
    assert "samples_cache.nb_unclassified" in text
    assert "only for an explicitly object-level query" in text
    assert "objets validés" in text
    assert "pre-aggregate object metrics by `sample_id`" in text


def test_ecotaxa_sample_maps_require_a_persisted_named_dataframe():
    from pathlib import Path

    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    graph_writer = Path("agents/skills/graph_writer.md").read_text()
    text = f"{COPEPOD_SYSTEM_PROMPT}\n{graph_writer}"
    assert "map of EcoTaxa samples" in text
    assert "reference bare `df`" in text
    assert "exact combined variable" in text
    assert "exact named DataFrame" in text
    assert "never run separate selections and plot only the last active one" in text
    assert "combined table" in text
