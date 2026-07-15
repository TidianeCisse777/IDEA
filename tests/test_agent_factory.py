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


def test_agent_graph_node_names_match_sse_stream_filter():
    """serve._stream_agent_sse ne diffuse le contenu/tool_calls que pour le
    nœud nommé "model" (et les résultats de tools pour "tools"). Si create_agent
    renomme ces nœuds, le stream SSE jette silencieusement toute la réponse
    (bug observé après la migration create_react_agent → create_agent, où le
    nœud modèle s'appelait "model" et non plus "agent"). On verrouille le
    contrat ici pour que ça pète côté test, pas côté UI.
    """
    with patch("agent.ChatOpenAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        from agent import make_agent
        agent = make_agent("thread-nodes")
    node_names = set(agent.get_graph().nodes)
    assert "model" in node_names, f"nœud 'model' attendu, obtenu: {sorted(node_names)}"
    assert "tools" in node_names, f"nœud 'tools' attendu, obtenu: {sorted(node_names)}"


def test_make_agent_registers_marine_taxonomy_tool():
    captured = {}

    def fake_create_agent(llm, tools, **kwargs):
        captured["tool_names"] = {tool.name for tool in tools}
        return MagicMock()

    with patch("agent.ChatOpenAI") as mock_llm, patch(
        "agent.create_agent", side_effect=fake_create_agent
    ):
        mock_llm.return_value = MagicMock()
        from agent import make_agent

        make_agent("thread-taxonomy")

    assert "lookup_marine_taxonomy" in captured["tool_names"]


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
    from tools.taxonomy_tool import make_taxonomy_tool
    tools = (
        make_tools("thread-test")
        + make_source_tools("thread-test")
        + make_bio_oracle_tools("thread-test")
        + make_amundsen_tools("thread-test")
        + make_ogsl_tools("thread-test")
        + make_sql_tools("thread-test")
        + [make_rag_tool(), make_taxonomy_tool()]
    )
    tool_names = {t.name for t in tools}
    descriptions = {t.name: t.description for t in tools}
    assert "load_file" in tool_names
    assert "run_pandas" in tool_names
    assert "query_copepod_knowledge_base" in tool_names
    assert "lookup_marine_taxonomy" in tool_names
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
    assert 'load_skill("ecotaxa_navigation")' in descriptions["search_ecotaxa_taxa"]


# --- Comportement 3 : prompt anti-hallucination ---

def test_system_prompt_anti_hallucination():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "run_pandas" in prompt
    assert "numérique" in prompt or "numeric" in prompt or "valeur" in prompt
    assert "general reasoning" in prompt or "raisonnement général" in prompt
    assert "project-specific facts" in prompt or "faits spécifiques" in prompt
    assert "lookup_marine_taxonomy" in COPEPOD_SYSTEM_PROMPT
    assert "not limited to ecotaxa" in prompt
    assert "combien de x dans le projet y" in prompt
    assert "preserve the definition source" in prompt
    assert "wikipedia article url" in prompt


# --- Comportement 4 : prompt mentionne les sources autorisées ---

def test_system_prompt_mentions_sources():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    assert "EcoTaxa" in COPEPOD_SYSTEM_PROMPT
    assert "EcoPart" in COPEPOD_SYSTEM_PROMPT
    assert "Amundsen" in COPEPOD_SYSTEM_PROMPT


def test_context_preparation_records_tool_truncation_metrics(monkeypatch):
    from langchain_core.messages import HumanMessage, ToolMessage

    import agent as agent_module

    monkeypatch.setattr(agent_module, "_MAX_TOOL_RESULT_CHARS", 20)

    messages, metrics = agent_module._truncate_tool_results(
        [
            HumanMessage(content="question"),
            ToolMessage(content="x" * 80, tool_call_id="tool-1"),
        ]
    )

    assert "tronqué" in messages[-1].content
    assert metrics["tool_messages_seen"] == 1
    assert metrics["tool_messages_truncated"] == 1
    assert metrics["tool_result_chars_saved"] > 0


def _spy_model():
    """FakeMessagesListChatModel qui capture le system prompt vu par le LLM."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    seen = {}

    class Spy(FakeMessagesListChatModel):
        def _generate(self, messages, *args, **kwargs):
            seen["system"] = "\n".join(m.content for m in messages if m.type == "system")
            seen["messages"] = list(messages)
            return super()._generate(messages, *args, **kwargs)

    return Spy(responses=[AIMessage(content="ok")]), seen


def test_context_middleware_injects_memories_into_system_prompt():
    from langchain_core.messages import HumanMessage
    from langgraph.store.memory import InMemoryStore
    from langchain.agents import create_agent
    import agent as agent_module

    store = InMemoryStore()
    store.put(("user-mem", "memories"), "m1", {"content": "préfère les graphiques en violet"})

    model, seen = _spy_model()
    mw = agent_module._ContextMiddleware(user_id="user-mem", thread_id="t-mem")
    graph = create_agent(model, [], system_prompt="BASE", middleware=[mw], store=store)
    graph.invoke(
        {"messages": [HumanMessage(content="salut")]},
        {"configurable": {"thread_id": "t-mem"}},
    )

    assert "préfère les graphiques en violet" in seen["system"]
    assert "BASE" in seen["system"]
    audit = agent_module.get_context_audit("t-mem")
    assert audit["approx_tokens_after_memory"] == audit["approx_tokens_model_request"]


def test_context_middleware_injects_memories_on_async_path():
    """serve.py invoque en async avec un store async — awrap_model_call doit marcher."""
    import asyncio
    from langchain_core.messages import HumanMessage
    from langgraph.store.memory import InMemoryStore
    from langchain.agents import create_agent
    import agent as agent_module

    store = InMemoryStore()
    store.put(("user-async", "memories"), "m1", {"content": "toujours en français"})

    model, seen = _spy_model()
    mw = agent_module._ContextMiddleware(user_id="user-async", thread_id="t-async")
    graph = create_agent(model, [], system_prompt="BASE", middleware=[mw], store=store)
    asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="salut")]},
            {"configurable": {"thread_id": "t-async"}},
        )
    )

    assert "toujours en français" in seen["system"]


def test_context_middleware_no_memories_leaves_system_prompt_untouched():
    from langchain_core.messages import HumanMessage
    from langgraph.store.memory import InMemoryStore
    from langchain.agents import create_agent
    import agent as agent_module

    model, seen = _spy_model()
    mw = agent_module._ContextMiddleware(user_id="user-empty", thread_id="t-empty")
    graph = create_agent(model, [], system_prompt="BASE", middleware=[mw], store=InMemoryStore())
    graph.invoke(
        {"messages": [HumanMessage(content="salut")]},
        {"configurable": {"thread_id": "t-empty"}},
    )

    assert seen["system"] == "BASE"


def test_context_middleware_trims_the_request_seen_by_model_without_mutating_checkpoint(monkeypatch):
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.messages.utils import count_tokens_approximately
    from langgraph.checkpoint.memory import MemorySaver

    import agent as agent_module

    agent_module.clear_context_audit()
    monkeypatch.setattr(agent_module, "_MAX_CONTEXT_TOKENS", 50)
    monkeypatch.setattr(agent_module, "_MAX_TOOL_RESULT_CHARS", 20)

    model, seen = _spy_model()
    graph = create_agent(
        model,
        [],
        system_prompt="BASE",
        middleware=[agent_module._ContextMiddleware(thread_id="trim-real")],
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "trim-real"}}
    old_content = "ancien-tour:" + "x" * 240
    messages = [
        HumanMessage(content=old_content),
        AIMessage(content="ancienne réponse"),
        HumanMessage(content="question récente"),
        AIMessage(
            content="",
            tool_calls=[{"name": "noop", "args": {}, "id": "call-1", "type": "tool_call"}],
        ),
        ToolMessage(content="résultat:" + "y" * 100, tool_call_id="call-1"),
    ]

    graph.invoke({"messages": messages}, config)

    visible = [message for message in seen["messages"] if message.type != "system"]
    assert all(old_content not in str(message.content) for message in visible)
    assert [message.type for message in visible[:3]] == ["human", "ai", "tool"]
    assert visible[1].tool_calls[0]["id"] == visible[2].tool_call_id
    assert "tronqué" in visible[2].content

    audit = agent_module.get_context_audit("trim-real")
    assert audit["messages_after_trim"] == len(visible)
    assert audit["approx_tokens_after_trim"] == count_tokens_approximately(visible)

    checkpoint_messages = graph.get_state(config).values["messages"]
    assert any(old_content in str(message.content) for message in checkpoint_messages)


def test_system_prompt_is_grouped_by_routing_domain():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    headings = [
        "## Identity",
        "## Operating Model",
        "## Authorized Data Sources",
        "## Routing Priority",
        "## Session Rules",
        "## Context and Session State",
        "## Knowledge Base vs Data Requests",
        "## Files and DataFrames",
        "## Geographic Zones",
        "## EcoTaxa",
        "## EcoPart",
        "## Environmental Enrichment",
        "## SQL Workspace",
        "## Graphs and Visual Outputs",
        "## Deliverables",
        "## Response Format and Tone",
        "## Confirmation Gates",
        "## Citations and Security",
    ]

    positions = [COPEPOD_SYSTEM_PROMPT.index(heading) for heading in headings]

    assert positions == sorted(positions)


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
    assert 'never call `run_graph` immediately after `load_skill("graph_planner")`' in planner
    assert 'first call `load_skill("graph_writer")`' in planner


def test_graph_writer_supports_standalone_named_zone_maps():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()

    assert "standalone named-zone map" in writer
    assert "get_zone_info(zone_name=...)" in writer
    assert "do not reference `df`" in writer
    assert "bbox = {\"south\"" in writer
    assert "ccrs.lambertconformal" in writer


def test_biodiversity_graph_plan_is_frozen_in_docs():
    plan = Path("docs/biodiversity_graph_test_plan.md")

    assert plan.exists()
    text = plan.read_text(encoding="utf-8").lower()
    for expected in [
        "profil vertical",
        "composition taxonomique",
        "rarefaction",
        "accumulation",
        "nmds",
        "pcoa",
        "heatmap",
        "rank-abundance",
        "neolabs_taxonomy_2014_2020.tsv",
    ]:
        assert expected in text


def test_graph_planner_lists_biodiversity_graph_types():
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()

    for expected in [
        "vertical profile",
        "taxonomic composition",
        "rarefaction",
        "species accumulation",
        "composition heatmap",
        "rank-abundance",
        "nmds",
        "pcoa",
    ]:
        assert expected in planner


def test_graph_writer_has_biodiversity_templates():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()

    for expected in [
        "vertical profile template",
        "taxonomic composition stacked bar template",
        "taxonomic composition heatmap template",
        "rarefaction curve template",
        "species accumulation curve template",
        "nmds / pcoa ordination template",
        "rank-abundance template",
        "ax.invert_yaxis()",
        "braycurtis",
        "mds(",
        "fill_between",
    ]:
        assert expected in writer


def test_graph_writer_documents_readability_guards():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()

    for expected in [
        "`figsize` must stay at or below",
        "more than 15 levels",
        "do not call `ax.legend()`",
        "legend omitted",
        "never show more than 50 visible tick labels",
        "display only the terminal taxon name",
        "truncate labels longer than 35 characters",
        "do not replace it with `/graphs/graph.png`",
        "top_groups",
        "groups_to_plot",
    ]:
        assert expected in writer


def test_graph_evals_include_biodiversity_benchmark_cases():
    text = Path("evals/eval_graphs.py").read_text(encoding="utf-8").lower()

    for expected in [
        "data/demo/neolabs_taxonomy_2014_2020.tsv",
        "required_skills",
        "make_skills_called_evaluator",
        "graph_writer",
        "gr-12",
        "rarefaction",
        "gr-13",
        "nmds",
        "gr-14",
        "heatmap",
        "gr-15",
        "rank-abundance",
    ]:
        assert expected in text


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


def test_system_prompt_routes_ecotaxa_enrichment_with_ecopart_to_remote_when_missing_loaded_ecopart():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "enrich_ecotaxa_with_ecopart_remote" in prompt
    assert "no ecopart file/project is already loaded in session" in prompt
    assert "even if `df_ecotaxa` is already loaded" in prompt
    assert "detour through `query_ecotaxa`" in prompt
    assert "no args by default" in prompt
    assert "heavy operation" in prompt


def test_system_prompt_requires_reporting_ecopart_join_match_coverage():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    # The agent must report match coverage and warn on weak/empty joins.
    assert "report join coverage" in prompt
    assert "matchées sur un bin ecopart" in prompt
    assert "same campaign" in prompt or "different campaign" in prompt
    assert "depth range actually covered" in prompt
    assert "not scientific interpretation" in prompt


def test_system_prompt_requires_source_variable_when_chaining_enrichments():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "chaining enrichments on the same ecotaxa-derived table" in prompt
    assert "exact variable produced by the previous step" in prompt
    assert "do not rely on the bare active `df`" in prompt
    assert "silently enrich the wrong table" in prompt
    assert "table enrichie" in prompt


def test_enrichment_skills_require_reporting_match_coverage():
    for path in ("agents/skills/ecopart_query.md", "agents/skills/ecotaxa_query.md"):
        skill = Path(path).read_text(encoding="utf-8").lower()
        assert "always report match coverage" in skill, path
        assert "did not really take" in skill, path


def test_ecopart_query_skill_prefers_remote_enrichment_when_ecotaxa_is_already_loaded():
    skill = Path("agents/skills/ecopart_query.md").read_text(encoding="utf-8").lower()

    assert "do **not** call `query_ecotaxa` again" in skill
    assert "use `enrich_ecotaxa_with_ecopart_remote` as the default route" in skill
    assert "only call `query_ecotaxa(project_id=...`" in skill or "only call `query_ecotaxa(project_id=...)" in skill


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
    assert "## routing priority" in prompt
    assert "prefer the most specific read-only source tool" in prompt
    assert "generic `run_pandas`, graph planning, or export/download tools" in prompt
    assert "ecotaxa read-only requests" in prompt
    assert "heavy exports/downloads" in prompt
    assert "explicit confirmation" in prompt


def test_system_prompt_routes_ecotaxa_stats_tables_to_project_summary():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "ecotaxa read-only routes beat dataframe/graph/export routes" in prompt
    assert 'load_skill("ecotaxa_navigation")` first' in prompt
    assert "tableau de stats des projets 17498 et 2331" in prompt
    assert "summarize_ecotaxa_projects(project_ids=[17498, 2331])" in prompt
    assert "résume le projet 17498 avant export" in prompt
    assert "summarize_ecotaxa_project(project_id=17498)" in prompt
    assert "prépare l'export de ces samples mais ne lance rien" in prompt
    assert "confirmed=false" in prompt
    assert "do not call `run_pandas`" in prompt
    assert "do not call `query_ecotaxa`" in prompt


def test_system_prompt_separates_ecotaxa_summary_from_preview():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "project preview / object sample" in prompt
    assert "do not use `preview_ecotaxa_project` for project summaries" in prompt
    assert "stats tables" in prompt
    assert "scan-before-export" in prompt
    assert "summarize_ecotaxa_project" in prompt


def test_system_prompt_loads_ecotaxa_navigation_before_zone_lookup():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "for ecotaxa navigation requests with a named zone" in prompt
    assert '(1) `load_skill("ecotaxa_navigation")`' in prompt
    assert "(2) `get_zone_info(zone_name=...)`" in prompt
    assert "first geography/source-boundary tool" in prompt


def test_system_prompt_handles_multiple_named_ecotaxa_zones_separately():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "multiple named zones" in prompt
    assert "baie de baffin et baie d'ungava" in prompt
    assert "do not merge names into one fake zone" in prompt
    assert "call `get_zone_info` once per zone" in prompt
    assert "once per zone with the same date/instrument filters" in prompt


def test_system_prompt_preserves_ecotaxa_source_links():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "ecotaxa source links" in prompt
    assert "https://ecotaxa.obs-vlfr.fr/prj/{project_id}" in prompt
    assert "samples={sample_id}" in prompt
    assert "do not remove links from copied ecotaxa tables" in prompt


def test_system_prompt_loads_ecotaxa_navigation_before_column_inspection():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "distribution de depth_min projet 17498" in prompt
    assert 'inspect_ecotaxa_column(project_id=17498, column_name="depth_min")' in prompt
    assert "first call `load_skill(\"ecotaxa_navigation\")`" in prompt
    assert "do not call `inspect_ecotaxa_project_schema` before or after" in prompt
    assert "`obj_depth` must stay `obj_depth`" in prompt


def test_system_prompt_routes_ecotaxa_export_planning_to_dry_run_tool():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "ecotaxa dry-run export planning" in prompt
    assert "prépare l'export" in prompt
    assert "mais ne lance rien" in prompt
    assert "export_ecotaxa_samples(sample_ids=[...], confirmed=false)" in prompt
    assert "do not stop after loading the skill" in prompt


def test_system_prompt_handles_export_failed_rights_without_relaunching_export():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "previous `export_failed` / rights failure" in prompt
    assert "verify access without relaunching export" in prompt
    assert "preview_ecotaxa_project(project_id=...)" in prompt
    assert "do not call `query_ecotaxa`" in prompt
    assert "or `export_ecotaxa_samples`" in prompt


def test_system_prompt_handles_missing_ecotaxa_project_cache_read_only():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "absent from the ecotaxa cache" in prompt
    assert "summarize_ecotaxa_project" in prompt
    assert "cache-missing message" in prompt
    assert "do not switch to `query_ecotaxa`" in prompt


def test_system_prompt_handles_sample_taxon_exact_vs_approximation():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "no-export approximation" in prompt
    assert "summarize_ecotaxa_samples(sample_ids=[...])" in prompt
    assert "exact per-sample counts for one taxon" in prompt
    assert "require an export/download path with confirmation" in prompt


def test_system_prompt_routes_current_ecotaxa_sample_followups_without_kb():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "current-result follow-ups" in prompt
    assert "ambiguous cache/context wording" in prompt
    assert "samples présents" in prompt
    assert "which of these" in prompt
    assert "extract the visible `sample_id`" in prompt
    assert "short clarifying question" in prompt
    assert "2–3 concrete scope options" in prompt
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
    assert "summarize_ecotaxa_project(project_id=x)" in skill
    assert "not the project" in skill
    assert "do not switch to `run_pandas`" in skill
    assert "query_ecotaxa" in skill
    assert "choose the read-only summary" in skill
    assert "exact_user_column" in skill
    assert "do not rewrite a clear column name" in skill
    assert "ne lance rien" in skill
    assert "confirmed=false" in skill
    assert "multiple zones" in skill
    assert "do not concatenate zones" in skill
    assert "export_failed" in skill
    assert "missing export rights" in skill
    assert "preserve ecotaxa project/sample source links" in skill
    assert "absent from the local" in skill
    assert "do not compensate" in skill


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


def test_system_prompt_requires_shared_hierarchy_resolver_for_loaded_copepod_data():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()

    assert "all copepoda filtering on a loaded dataframe" in prompt
    assert "copepod_hierarchy_mask" in prompt
    assert "do not reimplement" in prompt
    assert "object_annotation_hierarchy" in prompt
    assert "do not copy or rename another column" in prompt
    assert "`hierarchy` is not an accepted substitute" in prompt


def test_system_prompt_requires_canonical_sample_depth_for_uvp_analyses():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()

    assert "build_canonical_sample_depth" in prompt
    assert "one row per (`sample_id`, `depth_bin`)" in prompt
    assert "tables, correlations, and graph datasets" in prompt
    assert "do not independently rebuild" in prompt


def test_system_prompt_routes_two_local_ecotaxa_ecopart_files_by_variable():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT
    assert "ecotaxa_variable" in prompt
    assert "ecopart_variable" in prompt
    assert "project_id=None" in prompt
    assert "ignore any numeric EcoPart project from earlier turns" in prompt


def test_system_prompt_routes_join_control_to_persisted_audit_tool():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "audit_ecotaxa_ecopart_join" in prompt
    assert "never reconstruct the join for an audit" in prompt


def test_system_prompt_respects_run_pandas_persistence_contract():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Persistence: persisted=false" in prompt
    assert "do not claim that it was saved" in prompt
    assert "Persistence: persisted=true" in prompt


def test_system_prompt_requires_zero_inclusive_correlations_and_explicit_profile_metrics():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()

    assert "prepare_environment_correlation" in prompt
    assert "includes sampled zero-abundance bins by default" in prompt
    assert "presence_only=true" in prompt
    assert "explicit presence-only" in prompt
    assert "generic abundance requests never produce m5 or m6" in prompt
    assert "m5/m6 are explicit-only" in prompt
    assert "surface + bottom" in prompt
    assert "compute the requested coefficient from `analysis_df`" in prompt
    assert "do not look for coefficients in the preparer's attrs" in prompt
    assert "compute_m5" in prompt
    assert "never hand-write the m5 aggregation" in prompt
    assert "missing surface coverage" in prompt
    assert "compute_m5(df_canonical_sample_depth, sample_id=<requested sample>)" in prompt
    assert "do not pre-filter the canonical dataframe" in prompt


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


def test_system_prompt_routes_copepod_micro_hydrodynamics_to_dedicated_skill():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert 'load_skill("copepod_hydrodynamic_micro_zoom")' in prompt
    assert "front thermique" in prompt
    assert "panache" in prompt
    assert "upwelling" in prompt
    assert "migration verticale" in prompt
    assert "not fixed geographic zones" in prompt
    assert "for explicit file/dataset loading requests" in prompt
    assert "for ecotaxa browser/data requests that mention these structures" in prompt
    assert "then load the source-specific skill" in prompt
    assert "ecotaxa read-only skill-loading order" in prompt
    assert "call `load_file` first" in prompt
    assert 'next tool call must be `load_skill("copepod_hydrodynamic_micro_zoom")`' in prompt
    assert "before `query_copepod_knowledge_base`" in prompt
    assert "analysis, graphing, or scientific claims" in prompt
    assert "micro-hydrodynamic file-analysis exception" in prompt
    assert "the route is file-analysis first, not" in prompt
    assert "`load_file` → `load_skill(\"copepod_hydrodynamic_micro_zoom\")`" in prompt


def test_copepod_hydrodynamic_micro_zoom_skill_is_copepod_centered():
    skill = Path("agents/skills/copepod_hydrodynamic_micro_zoom.md").read_text(
        encoding="utf-8",
    ).lower()

    assert "copepod-centric" in skill
    assert "front" in skill
    assert "panache" in skill
    assert "upwelling" in skill
    assert "migration verticale" in skill
    assert "reproduction" in skill
    assert "do not present fronts, plumes, upwellings, or currents as fixed zones" in skill


def test_system_prompt_routes_neolabs_abundance_analysis_to_dedicated_skill():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert 'load_skill("neolabs_abundance_analysis")' in prompt
    assert "neolabs" in prompt
    assert "sample_id + analysis_id" in prompt
    assert "ordination" in prompt
    assert "nmds" in prompt
    assert "rda" in prompt


def test_system_prompt_neolabs_graphs_still_require_graph_writer():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "neolabs_abundance_analysis is not a replacement for graph_planner or graph_writer" in prompt
    assert 'then call `load_skill("graph_planner")`' in prompt
    assert 'then call `load_skill("graph_writer")`' in prompt
    assert "the very next execution call must be `run_graph`" in prompt


def test_graph_planner_requires_sample_df_for_neolabs_taxon_level_data():
    from pathlib import Path

    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()
    assert "sample_df" in planner
    assert "sample_id + analysis_id" in planner
    assert "taxon-level" in planner or "niveau taxon" in planner
    assert "total abundance (ind./m3 depth vol)" in planner
    assert "ctd_match_status" in planner


def test_neolabs_skill_routes_visual_outputs_through_graph_writer():
    skill = Path("agents/skills/neolabs_abundance_analysis.md").read_text(
        encoding="utf-8",
    ).lower()

    assert "not a graph_writer replacement" in skill
    assert 'load_skill("graph_planner")' in skill
    assert 'load_skill("graph_writer")' in skill
    assert "very next execution call must be `run_graph`" in skill


def test_system_prompt_requires_executable_graph_contracts():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "graph_contract" in COPEPOD_SYSTEM_PROMPT
    assert "only the depth y-axis" in COPEPOD_SYSTEM_PROMPT
    assert "independent axes" in COPEPOD_SYSTEM_PROMPT
    assert "zero_abundance" in COPEPOD_SYSTEM_PROMPT
    assert "abundance_size_legend" in COPEPOD_SYSTEM_PROMPT
    assert "environment_color_legend" in COPEPOD_SYSTEM_PROMPT


def test_graph_writer_defines_all_executable_contract_families():
    skill = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8")

    for kind in (
        "generic",
        "vertical_profile",
        "environment_relationships",
        "temperature_salinity",
        "abundance_environment_map",
    ):
        assert f'"kind": "{kind}"' in skill
    for field in (
        '"axes"',
        '"inverted_axes"',
        '"mappings"',
        '"zero_policy"',
        '"source_variables"',
    ):
        assert field in skill
    assert 'set_gid("zero_abundance")' in skill
    assert 'set_gid("abundance_size_legend")' in skill
    assert 'set_gid("environment_color_legend")' in skill
