"""Tests TDD — slice 5 : CLI run_query"""
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


@pytest.fixture
def tsv_path(tmp_path):
    df = pd.DataFrame({
        "profile_id": ["ips_007", "ips_008"],
        "depth": [10.5, 25.0],
        "temperature": [2.1, 1.8],
    })
    p = tmp_path / "sample.tsv"
    df.to_csv(p, sep="\t", index=False)
    return str(p)


# --- Comportement 1 : run_query retourne une réponse ---

def test_run_query_returns_response(tsv_path):
    fake_response = "Le fichier contient 2 profils."
    mock_msg = MagicMock()
    mock_msg.content = fake_response

    with patch("agent.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        # create_agent retourne un graph dont invoke retourne {"messages": [...]}
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"messages": [mock_msg]}

        with patch("agent.create_agent", return_value=mock_graph):
            from agent import run_query
            result = run_query(tsv_path, "combien de profils ?")

    assert result == fake_response


# --- Comportement 2 : callbacks LangSmith passés avec metadata ---

def test_run_query_passes_langsmith_callbacks(tsv_path):
    mock_msg = MagicMock()
    mock_msg.content = "réponse"

    with patch("agent.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"messages": [mock_msg]}

        with patch("agent.create_agent", return_value=mock_graph):
            with patch("agent.LangChainTracer") as mock_tracer_cls:
                mock_tracer = MagicMock()
                mock_tracer_cls.return_value = mock_tracer

                from agent import run_query
                run_query(tsv_path, "combien de profils ?")

    # LangChainTracer doit être instancié avec project_name et tags
    mock_tracer_cls.assert_called_once()
    call_kwargs = mock_tracer_cls.call_args.kwargs
    assert "project_name" in call_kwargs
    assert "tags" in call_kwargs
