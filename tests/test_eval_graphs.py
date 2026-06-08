"""Tests pour le pipeline vision judge — extraction PNG + judge avec image."""
import base64
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import MagicMock, patch
from evals.eval_graphs import _extract_graph_image, _extract_tools_called, make_vision_judge_evaluator


# --- Fixtures ---

def _make_tool_message(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    return msg


def _make_ai_message_with_tool_calls(tool_names: list[str]):
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [{"name": name, "args": {}} for name in tool_names]
    return msg


# Petit PNG 1x1 pixel valide en base64
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# --- Tests _extract_graph_image ---

def test_extract_graph_image_found():
    msgs = [
        _make_tool_message("some text"),
        _make_tool_message(f"![graph](data:image/png;base64,{_TINY_PNG_B64})"),
        _make_tool_message("other text"),
    ]
    result = _extract_graph_image(msgs)
    assert result == _TINY_PNG_B64


def test_extract_graph_image_not_found():
    msgs = [
        _make_tool_message("no image here"),
        _make_tool_message("just text"),
    ]
    result = _extract_graph_image(msgs)
    assert result is None


def test_extract_graph_image_empty():
    assert _extract_graph_image([]) is None


# --- Tests _extract_tools_called ---

def test_extract_tools_called():
    msgs = [
        _make_tool_message("text"),
        _make_ai_message_with_tool_calls(["load_skill", "run_graph"]),
    ]
    result = _extract_tools_called(msgs)
    assert "load_skill" in result
    assert "run_graph" in result


def test_extract_tools_called_empty():
    msgs = [_make_tool_message("no tools")]
    result = _extract_tools_called(msgs)
    assert result == []


# --- Tests make_vision_judge_evaluator ---

def test_vision_judge_calls_judge_with_image_when_image_present():
    with patch("evals.eval_graphs.judge_with_image") as mock_vision:
        mock_vision.return_value = {"score": 0.9, "reasoning": "Good chart"}
        evaluator = make_vision_judge_evaluator("criteria")
        result = evaluator(
            outputs={"response": "Voici le graphe", "image_b64": _TINY_PNG_B64},
            reference_outputs={"criteria": "Must produce a bar chart"},
        )
        mock_vision.assert_called_once()
        assert result["score"] == 0.9
        assert result["key"] == "vision_judge"


def test_vision_judge_falls_back_to_text_when_no_image():
    with patch("evals.judge.judge") as mock_judge:
        mock_judge.return_value = {"score": 0.5, "reasoning": "No image"}
        evaluator = make_vision_judge_evaluator("criteria")
        result = evaluator(
            outputs={"response": "Voici le graphe", "image_b64": ""},
            reference_outputs={"criteria": "Must produce a bar chart"},
        )
        assert result["key"] == "vision_judge"
