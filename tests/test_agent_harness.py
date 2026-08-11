"""Minimal construction and permanent-behavior contracts for IDEA."""

from unittest.mock import MagicMock, patch


def test_agent_graph_keeps_model_and_tool_nodes():
    with patch("agent.ChatOpenAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        from agent import make_agent

        graph = make_agent("harness-construction")

    assert {"model", "tools"} <= set(graph.get_graph().nodes)


def test_permanent_prompt_matches_current_harness():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "load_skill" not in prompt
    assert "qualified: true|false" in prompt
    assert "wait for" in prompt and "tool result" in prompt
    assert "available dataframes" in prompt
    assert "rag" in prompt
