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
    assert "analysis-ready cache contract" in prompt
    assert "directly answers a simple list" in prompt
    assert "exactly one `run_pandas` call" in prompt


def test_permanent_prompt_requires_rag_and_clarification_before_method_sensitive_comparison():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "cross-instrument quantitative comparison" in prompt
    assert "rag before the first calculation" in prompt
    assert "ask one short clarification before calculation" in prompt
    assert "never validate a corrected-looking derived table by name" in prompt
    assert "recompute from the nearest authoritative source" in prompt


def test_permanent_prompt_stops_repeated_column_or_method_guessing():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = " ".join(COPEPOD_SYSTEM_PROMPT.lower().split())
    assert "one evidence attempt only" in prompt
    assert "stop and ask one short user question" in prompt
    assert "never launch another `run_pandas` to guess aliases" in prompt
    assert "never continue at a reduced grain" in prompt


def test_permanent_prompt_requires_user_choice_between_plausible_columns():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = " ".join(COPEPOD_SYSTEM_PROMPT.lower().split())
    assert "column choice is a material analytical decision" in prompt
    assert "ask which exact column to use" in prompt
    assert "name the observed candidates" in prompt
    assert "never choose a data column by name similarity" in prompt
    assert "defaults apply only to non-material presentation choices" in prompt
    assert "does not override the mandatory user question" in prompt


def test_display_only_followup_is_narrow_and_excludes_new_analysis():
    from agent import _is_display_only_followup

    assert _is_display_only_followup("affiche moi le resultat")
    assert _is_display_only_followup("Réaffiche ce tableau")
    assert _is_display_only_followup("show this table")
    assert not _is_display_only_followup("affiche une carte du résultat")
    assert not _is_display_only_followup("trie puis affiche le tableau")
    assert not _is_display_only_followup("calcule le total")
