"""TDD — tools/skill_tool.py."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_hub_skill_name_maps_correctly():
    from tools.skill_tool import _hub_skill_name

    assert _hub_skill_name("ecotaxa_query") == "copepod-ecotaxa-query"
    assert _hub_skill_name("graph_planner") == "copepod-graph-planner"
    assert _hub_skill_name("uvp_ecopart") == "copepod-uvp-ecopart"


def test_load_skill_pulls_from_hub_when_api_key_set(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    monkeypatch.setenv("SKILL_ENV", "production")

    mock_skill = MagicMock()
    mock_skill.files = {"SKILL.md": MagicMock(content="# Hub skill content")}
    mock_instance = MagicMock()
    mock_instance.pull_skill.return_value = mock_skill
    mock_class = MagicMock(return_value=mock_instance)

    with patch("tools.skill_tool._LangSmithClient", mock_class):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "ecotaxa_query"})

    mock_instance.pull_skill.assert_called_once_with("copepod-ecotaxa-query:production")
    assert result == "# Hub skill content"


def test_load_skill_falls_back_to_local_when_hub_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")

    mock_instance = MagicMock()
    mock_instance.pull_skill.side_effect = Exception("Hub unreachable")
    mock_class = MagicMock(return_value=mock_instance)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "ecotaxa_query.md").write_text("# Local skill content")

    with patch("tools.skill_tool._LangSmithClient", mock_class), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "ecotaxa_query"})

    assert result == "# Local skill content"


def test_load_skill_skips_hub_when_no_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_planner.md").write_text("# Local graph planner")

    mock_class = MagicMock()

    with patch("tools.skill_tool._LangSmithClient", mock_class), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "graph_planner"})

    mock_class.assert_not_called()
    assert result == "# Local graph planner"
