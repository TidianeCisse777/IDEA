"""Tests TDD — agent.py slice 4"""
from unittest.mock import patch, MagicMock

import pytest


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
    from tools.sql_workspace import make_sql_tools
    from tools.rag_tool import make_rag_tool
    from tools.copepod_sources import make_source_tools
    tools = (
        make_tools("thread-test")
        + make_source_tools("thread-test")
        + make_bio_oracle_tools("thread-test")
        + make_amundsen_tools("thread-test")
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
    assert "list_sql_tables" in tool_names
    assert "copy_sql_query_to_workspace" in tool_names


# --- Comportement 3 : prompt anti-hallucination ---

def test_system_prompt_anti_hallucination():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "run_pandas" in prompt
    assert "numérique" in prompt or "numeric" in prompt or "valeur" in prompt


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


def test_system_prompt_routes_sql_workspace_queries():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "database_url" in prompt
    assert "read-only" in prompt
    assert "preview_sql_table" in prompt
    assert "copy_sql_query_to_workspace" in prompt
    assert "sql_workspace_query" in prompt


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


def test_system_prompt_routes_bio_oracle_list_preview_query_and_coupling():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "list_bio_oracle_datasets" in prompt
    assert "preview_bio_oracle_point" in prompt
    assert "query_bio_oracle" in prompt
    assert "couple_zooplankton_bio_oracle" in prompt
    assert "only if `query_bio_oracle` succeeds" in prompt


def test_system_prompt_routes_amundsen_preview_and_query():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "amundsen12713" in prompt
    assert "list_amundsen_datasets" in prompt
    assert "preview_amundsen_profile" in prompt
    assert "query_amundsen_ctd" in prompt


def test_system_prompt_loads_environmental_join_skill_for_ctd_and_bio_oracle_joins():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert 'load_skill("environmental_join")' in prompt
    assert "amundsen ct" in prompt
    assert "bio-oracle" in prompt
