"""Tests TDD — agent.py slice 4"""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# --- Comportement 0 : _make_tracer inclut user_id ---

def test_make_tracer_uses_email_as_tag_when_provided(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    from agent import _make_tracer
    tracer = _make_tracer("thread-abc123", user_id="uid-42", user_email="alice@ulaval.ca")
    assert tracer is not None
    assert any("alice@ulaval.ca" in tag for tag in tracer.tags)
    assert not any("uid-42" in tag for tag in tracer.tags)


def test_make_tracer_falls_back_to_user_id_when_no_email(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    from agent import _make_tracer
    tracer = _make_tracer("thread-abc123", user_id="uid-42")
    assert tracer is not None
    assert any("uid-42" in tag for tag in tracer.tags)


def test_make_tracer_defaults_user_id_to_anonymous(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    from agent import _make_tracer
    tracer = _make_tracer("thread-abc123")
    assert tracer is not None
    assert any("anonymous" in tag for tag in tracer.tags)


# --- Comportement 1 : make_agent retourne un graph ---

def test_make_agent_returns_graph():
    with patch("agent.ChatOpenAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        from agent import make_agent
        agent = make_agent("thread-test")
    assert agent is not None


# --- Comportement 2 : les 3 tools sont présents ---

def test_agent_has_required_tools(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SQL_WORKSPACE_DIR", str(tmp_path / "sql_workspace"))

    with patch("agent.ChatOpenAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        from agent import make_agent
        make_agent("thread-test")

    from tools.data_tools import make_tools
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.amundsen_sources import make_amundsen_tools
    from tools.ogsl_sources import make_ogsl_tools
    from tools.sql_workspace import make_sql_tools
    from tools.rag_tool import make_rag_tool
    from tools.copepod_sources import make_source_tools
    tools = (
        make_tools("thread-test")
        + make_source_tools("thread-test")
        + make_bio_oracle_tools("thread-test")
        + make_amundsen_tools("thread-test")
        + make_ogsl_tools("thread-test")
        + make_sql_tools("thread-test")
        + [make_rag_tool()]
    )
    tool_names = {t.name for t in tools}
    assert "load_file" in tool_names
    assert "run_pandas" in tool_names
    assert "query_copepod_knowledge_base" in tool_names
    assert "list_bio_oracle_datasets" in tool_names
    assert "preview_bio_oracle_point" in tool_names
    assert "query_bio_oracle" in tool_names
    assert "couple_zooplankton_bio_oracle" in tool_names
    assert "list_amundsen_datasets" in tool_names
    assert "preview_amundsen_profile" in tool_names
    assert "query_amundsen_ctd" in tool_names
    assert "enrich_loaded_table_with_amundsen_ctd" in tool_names
    assert "query_ogsl" in tool_names
    assert "list_sql_tables" in tool_names
    assert "copy_sql_query_to_workspace" in tool_names


# --- Comportement 3 : prompt anti-hallucination ---

def test_system_prompt_anti_hallucination():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "run_pandas" in prompt
    assert "numérique" in prompt or "numeric" in prompt or "valeur" in prompt
    assert "general reasoning" in prompt or "raisonnement général" in prompt
    assert "project-specific facts" in prompt or "faits spécifiques" in prompt


# --- Comportement 4 : prompt mentionne les sources autorisées ---

def test_system_prompt_mentions_sources():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    assert "EcoTaxa" in COPEPOD_SYSTEM_PROMPT
    assert "EcoPart" in COPEPOD_SYSTEM_PROMPT
    assert "Amundsen" in COPEPOD_SYSTEM_PROMPT


def test_system_prompt_mentions_graph_explanation():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "graph_explanation" in prompt
    assert "lecture rapide" in prompt


def test_system_prompt_forbids_bare_df_for_multi_source_graphs():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "multi-source" in prompt
    assert "never use bare `df`" in prompt
    assert "df_ecotaxa_ecopart" in prompt
    assert "df_bio_oracle" in prompt
    assert "plot_df" in prompt


def test_system_prompt_forbids_plan_only_visual_answers():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "profil vertical" in prompt
    assert "trace" in prompt
    assert "affiche" in prompt
    assert "do not stop after planning" in prompt
    assert "only contains `<details><summary>output plan</summary>" in prompt
    assert "run_graph` image markdown" in prompt


def test_graph_planner_treats_french_profile_requests_as_visual():
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()

    assert "profil vertical" in planner
    assert "profil verticale" in planner
    assert "trace" in planner
    assert "affiche" in planner
    assert "never answer the user with only this `<details>` block" in planner


def test_graph_writer_supports_standalone_named_zone_maps():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()

    assert "standalone named-zone map" in writer
    assert "get_zone_info(zone_name=...)" in writer
    assert "do not reference `df`" in writer
    assert "bbox = {\"south\"" in writer
    assert "ccrs.lambertconformal" in writer


def test_system_prompt_routes_named_zone_map_requests():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "first geography/source-boundary tool must be `get_zone_info" in prompt
    assert "carte" in prompt
    assert "load_skill(\"graph_planner\")" in prompt
    assert "load_skill(\"graph_writer\")" in prompt
    assert "very next tool call must be `run_graph`" in prompt


def test_graph_rules_preserve_identifier_types_and_validate_non_empty_plot_df():
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()

    assert "never `int(station)`" in planner
    assert "identifiers as labels" in writer
    assert "never cast identifiers" in writer
    assert "astype(str).str.strip()" in writer
    assert "if plot_df.empty: raise valueerror" in writer
    assert "validate again" in writer


def test_system_prompt_routes_sql_workspace_queries():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "database_url" in prompt
    assert "read-only" in prompt
    assert "preview_sql_table" in prompt
    assert "copy_sql_query_to_workspace" in prompt
    assert "sql_workspace_query" in prompt


def test_system_prompt_routes_sql_workspace_joins_from_foreign_keys():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "join" in prompt
    assert "foreign key" in prompt or "foreign keys" in prompt
    assert "list_sql_tables" in prompt
    assert "select" in prompt
    assert "limit" in prompt
    assert "copy_sql_query_to_workspace" in prompt


def test_system_prompt_sql_join_planning_uses_columns_cardinality_and_retry():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "column" in prompt
    assert "cardinality" in prompt or "row count" in prompt
    assert "preview_sql_table" in prompt
    assert "retry" in prompt
    assert "schema" in prompt


def test_system_prompt_sql_copy_requires_limit_and_mentions_row_cap():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "copy_sql_query_to_workspace" in prompt
    assert "explicit `limit`" in prompt
    assert "row cap" in prompt


def test_system_prompt_mentions_supported_sql_backends():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "sqlite" in prompt
    assert "postgresql" in prompt
    assert "mysql" in prompt
    assert "mariadb" in prompt


def test_system_prompt_routes_ecotaxa_project_discovery():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "list_ecotaxa_projects" in COPEPOD_SYSTEM_PROMPT


def test_system_prompt_loads_ecotaxa_skill_only_after_success():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "only if `query_ecotaxa` succeeds" in prompt
    assert "do not call `load_skill(\"ecotaxa_query\")` after an error" in prompt


def test_system_prompt_routes_ecotaxa_list_preview_and_export_separately():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "`list_ecotaxa_projects`" in prompt
    assert "`preview_ecotaxa_project`" in prompt
    assert "présente-moi" in prompt
    assert "do not call `query_ecotaxa` for preview-only requests" in prompt
    assert "charge" in prompt
    assert "exporte" in prompt


def test_ecotaxa_navigation_distinguishes_loki_instrument_from_project():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert 'load_skill("ecotaxa_navigation")' in prompt
    assert "loki-as-instrument" in prompt
    assert "samples-by-zone queries" in skill
    assert "projet loki" in skill
    assert "instrument loki" in skill
    assert 'instrument="loki"' in skill
    assert "instead of resolving a" in skill
    assert "project title" in skill


def test_system_prompt_prioritizes_read_only_source_tools_over_generic_pandas():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "routing priority and ambiguity policy" in prompt
    assert "most specific read-only source tool" in prompt
    assert "generic `run_pandas` / graph planning" in prompt
    assert "must not steal requests" in prompt
    assert "ask one short clarification question" in prompt
    assert "do not export by default" in prompt


def test_system_prompt_routes_ecotaxa_stats_tables_to_project_summary():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "ecotaxa read-only routes beat dataframe/graph/export routes" in prompt
    assert "tableau de stats des projets 14853 et 2331" in prompt
    assert "summarize_ecotaxa_projects(project_ids=[14853, 2331])" in prompt
    assert "do not call `run_pandas`" in prompt
    assert "do not call `query_ecotaxa`" in prompt


def test_system_prompt_loads_ecotaxa_navigation_before_zone_lookup():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "for ecotaxa navigation requests with a named zone" in prompt
    assert '(1) `load_skill("ecotaxa_navigation")`' in prompt
    assert "(2) `get_zone_info(zone_name=...)`" in prompt
    assert "first geography/source-boundary tool" in prompt


def test_system_prompt_routes_current_ecotaxa_sample_followups_without_kb():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "current-result follow-ups" in prompt
    assert "ambiguous cache/context wording" in prompt
    assert "samples présents" in prompt
    assert "which of these" in prompt
    assert "extract the visible `sample_id`" in prompt
    assert "ask one short clarification question" in prompt
    assert "which" in prompt
    assert "le plus" in prompt
    assert "never route to the knowledge base" in prompt
    assert "do not call `query_copepod_knowledge_base`" in prompt
    assert "do not answer with a fresh metadata list" in prompt


def test_system_prompt_allows_operational_synthesis_without_scientific_interpretation():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "tool outputs are evidence, not necessarily the final answer" in prompt
    assert "compute requested metrics" in prompt
    assert "sort rankings" in prompt
    assert "select relevant columns" in prompt
    assert "non_annoté = p + d + u" in prompt
    assert "return the ranked answer, not the raw wide tool table" in prompt
    assert "scientific or biological interpretation" in prompt
    assert "operational transformations requested by the user" in prompt


def test_ecotaxa_navigation_skill_prefers_read_only_when_ambiguous():
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "general ambiguity rule" in skill
    assert "prefer read-only navigation tools over exports" in skill
    assert "summarize_ecotaxa_projects" in skill
    assert "do not switch to `run_pandas`" in skill
    assert "query_ecotaxa" in skill
    assert "choose the read-only summary" in skill


def test_ecotaxa_navigation_skill_handles_current_sample_taxon_rankings():
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "parmi ceux-là" in skill
    assert "reuse those ids" in skill
    assert "samples présents" in skill
    assert "ambiguous unless" in skill
    assert "ecotaxa cache" in skill
    assert "ask one short clarification question" in skill
    assert "summarize_ecotaxa_samples(sample_ids=[...])" in skill
    assert "taxon-specific limitation" in skill
    assert "not exact per-sample counts" in skill
    assert "do not fall back to a fresh sample" in skill
    assert "exact object-level filtering requires an export/download" in skill


def test_ecotaxa_navigation_skill_owns_project_taxon_count_details():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    skill = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert 'load_skill("ecotaxa_navigation")' in prompt
    assert "count_ecotaxa_taxa" in prompt
    assert "25828" not in prompt
    assert "copepoda<multicrustacea" not in prompt

    assert "taxa_ids=<taxon_id" in skill
    assert "25828" in skill
    assert "copepoda<multicrustacea" in skill
    assert "copépodes" in skill


def test_system_prompt_routes_bio_oracle_list_preview_query_and_enrichment():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "list_bio_oracle_datasets" in prompt
    assert "preview_bio_oracle_point" in prompt
    assert "query_bio_oracle" in prompt
    assert "enrich_with_bio_oracle" in prompt
    assert "only if `query_bio_oracle` succeeds" in prompt


def test_system_prompt_routes_bio_oracle_per_station_to_enrichment():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "les mêmes stations" in prompt
    assert "top n stations" in prompt
    assert "scenarios" in prompt
    assert "never create empty placeholder columns" in prompt
    assert "do not use `query_bio_oracle_zones` for this case" in prompt
    assert "a download link alone is not an answer" in prompt
    assert "df_bio_oracle_enriched_*" in prompt


def test_system_prompt_routes_bio_oracle_year_specific_requests_to_target_year():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "target_year=2050" in prompt
    assert "en 2050" in prompt
    assert "do not reuse a previously computed" in prompt
    assert "time_*" in prompt
    assert "re-query bio-oracle" in prompt
    assert "baseline is historical" in prompt
    assert "verify the requested year on `time_ssp*`" in prompt
    assert "not on `time_baseline`" in prompt


def test_bio_oracle_skill_routes_per_station_followups_to_coupling():
    skill = Path("agents/skills/bio_oracle_query.md").read_text(encoding="utf-8").lower()

    assert "never use `query_bio_oracle_zones` for a per-station request" in skill
    assert "les mêmes stations" in skill
    assert "top_n_stations" in skill
    assert "scenarios=[\"baseline\", \"ssp1-2.6\", \"ssp5-8.5\"]" in skill
    assert "do not create placeholder columns with `pd.na`" in skill


def test_bio_oracle_skill_requires_target_year_for_year_specific_requests():
    skill = Path("agents/skills/bio_oracle_query.md").read_text(encoding="utf-8").lower()

    assert "target_year" in skill
    assert "2050" in skill
    assert "does not prove whether" in skill
    assert "dataset's last time slice" in skill
    assert "baseline is historical" in skill
    assert "verify year-specific requests on `time_ssp*`" in skill


def test_bio_oracle_skill_documents_coupling_tool_capabilities():
    skill = Path("agents/skills/bio_oracle_query.md").read_text(encoding="utf-8").lower()

    assert "`couple_zooplankton_bio_oracle` can:" in skill
    assert "enrich each source row" in skill
    assert "build a station table internally" in skill
    assert "compare multiple bio-oracle scenarios" in skill
    assert "return traceability columns" in skill


def test_system_prompt_routes_amundsen_preview_and_query():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "amundsen12713" in prompt
    assert "list_amundsen_datasets" in prompt
    assert "preview_amundsen_profile" in prompt
    assert "query_amundsen_ctd" in prompt
    assert "enrich_loaded_table_with_amundsen_ctd" in prompt
    assert "récupère ça avec amundsen science" in prompt
    assert "missing_sample_metadata" in prompt
    assert "do not use `query_amundsen_ctd` for a whole loaded file" in prompt


def test_system_prompt_routes_ogsl_enrichment_to_enrich_with_ogsl():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "enrich_with_ogsl" in prompt
    assert "spatial_tolerance_km" in prompt
    assert "time_tolerance_hours" in prompt
    assert "ogsl_te90_degc" in prompt
    assert "ogsl_match_status" in prompt


def test_system_prompt_loads_environmental_join_skill_for_ctd_and_bio_oracle_joins():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert 'load_skill("environmental_join")' in prompt
    assert "amundsen ct" in prompt
    assert "bio-oracle" in prompt


def test_system_prompt_routes_neolabs_abundance_analysis_to_dedicated_skill():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert 'load_skill("neolabs_abundance_analysis")' in prompt
    assert "neolabs" in prompt
    assert "sample_id + analysis_id" in prompt
    assert "ordination" in prompt
    assert "nmds" in prompt
    assert "rda" in prompt


def test_graph_planner_requires_sample_df_for_neolabs_taxon_level_data():
    from pathlib import Path

    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()
    assert "sample_df" in planner
    assert "sample_id + analysis_id" in planner
    assert "taxon-level" in planner or "niveau taxon" in planner
    assert "total abundance (ind./m3 depth vol)" in planner
    assert "ctd_match_status" in planner
