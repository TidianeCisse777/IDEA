"""TDD — tools/skill_tool.py."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_hub_skill_name_maps_correctly():
    from tools.skill_tool import _hub_skill_name

    assert _hub_skill_name("ecotaxa_query") == "copepod-ecotaxa-query"
    assert _hub_skill_name("graph_planner") == "copepod-graph-planner"
    assert _hub_skill_name("uvp_ecopart") == "copepod-uvp-ecopart"
    assert _hub_skill_name("neolabs_abundance_analysis") == "copepod-neolabs-abundance-analysis"


def test_load_skill_pulls_from_hub_when_api_key_set(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    monkeypatch.setenv("SKILL_ENV", "production")
    monkeypatch.delenv("SKILL_PREFER_LOCAL", raising=False)

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


def test_load_skill_records_loaded_skills_in_session(monkeypatch, tmp_path):
    from tools.session_store import SessionStore

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_writer.md").write_text("# Local graph writer")
    store = SessionStore(tmp_path / "sessions")

    with patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool

        skill_tool = make_skill_tool(thread_id="thread-skills", store=store)
        result = skill_tool.invoke({"skill_name": "graph_writer"})

    session = store.get("thread-skills")
    assert result == "# Local graph writer"
    assert session is not None
    assert session["meta"]["loaded_skills"] == ["graph_writer"]


def test_neolabs_abundance_skill_documents_standard_analysis_workflow():
    skill = Path("agents/skills/neolabs_abundance_analysis.md").read_text(encoding="utf-8")
    text = skill.lower()

    assert "sample_id + analysis_id" in text
    assert "sample_df" in text
    assert "ind./m3" in text or "ind m" in text
    assert "ctd_match_status" in text
    assert "shannon" in text
    assert "simpson" in text
    assert "pielou" in text
    assert "anomal" in text
    assert "ordination" in text
    assert "pca" in text
    assert "nmds" in text
    assert "pcoa" in text
    assert "rda" in text


def test_uvp_skill_requires_strict_hierarchy_resolver():
    content = Path("agents/skills/uvp_ecotaxa.md").read_text(encoding="utf-8")

    assert "from core.copepod_taxonomy import copepod_hierarchy_mask" in content
    assert "copepod_keywords" not in content
    assert "cop_cats =" not in content
    assert "Do not copy or rename an alternate column" in content
    assert "`hierarchy` is not an accepted substitute" in content


def test_uvp_skill_requires_canonical_sample_depth_builder_for_downstream_views():
    content = Path("agents/skills/uvp_ecotaxa.md").read_text(encoding="utf-8")

    assert (
        "from core.copepod_sample_depth import build_canonical_sample_depth"
        in content
    )
    assert "canonical_bins = build_canonical_sample_depth(" in content
    assert "tables, correlations, and graph datasets" in content
    assert "reuse the same `canonical_bins`" in content


def test_uvp_skill_requires_zero_inclusive_environment_contract_and_explicit_m5():
    content = Path("agents/skills/uvp_ecotaxa.md").read_text(encoding="utf-8")

    assert (
        "from core.copepod_abundance_analysis import prepare_environment_correlation"
        in content
    )
    assert "presence_only=False" in content
    assert "report `n_retained` and `n_zero_abundance`" in content
    assert "Generic abundance requests never produce m5 or m6" in content
    assert "m5/m6 are explicit-only" in content
    assert "compute the requested coefficient from `analysis_df` after preparation" in content
    assert "The preparer does not store coefficients in `attrs`" in content
    assert "default to **m5" not in content
    assert "canonically map to m5" not in content
