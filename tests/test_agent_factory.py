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

def test_agent_has_required_tools():
    with patch("agent.ChatOpenAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        from agent import make_agent
        make_agent("thread-test")

    from tools.data_tools import make_tools
    from tools.rag_tool import make_rag_tool
    tools = make_tools("thread-test") + [make_rag_tool()]
    tool_names = {t.name for t in tools}
    assert "load_file" in tool_names
    assert "run_pandas" in tool_names
    assert "query_copepod_knowledge_base" in tool_names


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
