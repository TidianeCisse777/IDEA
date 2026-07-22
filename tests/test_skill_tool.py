"""TDD — tools/skill_tool.py."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _skill_doc(name: str, body: str, *, version: str = "1.0.0", max_tokens: int = 500) -> str:
    return f"""---
name: {name}
version: {version}
triggers:
  - matching user intent
forbidden_when:
  - source is not authorized
requires: []
next_tool: null
max_tokens: {max_tokens}
---
{body}
"""


def test_hub_skill_name_maps_correctly():
    from tools.skill_tool import _hub_skill_name

    assert _hub_skill_name("ecotaxa_query") == "copepod-ecotaxa-query"
    assert _hub_skill_name("graph_planner") == "copepod-graph-planner"
    assert _hub_skill_name("uvp_ecopart") == "copepod-uvp-ecopart"
    assert _hub_skill_name("neolabs_abundance_analysis") == "copepod-neolabs-abundance-analysis"


def test_load_skill_pulls_from_hub_when_api_key_set(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    monkeypatch.setenv("SKILL_ENV", "production")
    monkeypatch.delenv("SKILL_PREFER_LOCAL", raising=False)

    mock_skill = MagicMock()
    hub_content = _skill_doc("ecotaxa_query", "# Hub skill content")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "ecotaxa_query.md").write_text(hub_content)
    mock_skill.files = {"SKILL.md": MagicMock(content=hub_content)}
    mock_instance = MagicMock()
    mock_instance.pull_skill.return_value = mock_skill
    mock_class = MagicMock(return_value=mock_instance)

    with patch("tools.skill_tool._LangSmithClient", mock_class), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "ecotaxa_query"})

    mock_instance.pull_skill.assert_called_once_with("copepod-ecotaxa-query:production")
    assert result.strip() == "# Hub skill content"


def test_load_skill_falls_back_to_local_when_hub_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")

    mock_instance = MagicMock()
    mock_instance.pull_skill.side_effect = Exception("Hub unreachable")
    mock_class = MagicMock(return_value=mock_instance)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "ecotaxa_query.md").write_text(
        _skill_doc("ecotaxa_query", "# Local skill content")
    )

    with patch("tools.skill_tool._LangSmithClient", mock_class), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "ecotaxa_query"})

    assert result.strip() == "# Local skill content"


def test_load_skill_skips_hub_when_no_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_planner.md").write_text(
        _skill_doc("graph_planner", "# Local graph planner")
    )

    mock_class = MagicMock()

    with patch("tools.skill_tool._LangSmithClient", mock_class), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool
        skill_tool = make_skill_tool()
        result = skill_tool.invoke({"skill_name": "graph_planner"})

    mock_class.assert_not_called()
    assert "Plan before code" in result


def test_load_skill_records_loaded_skills_in_session(monkeypatch, tmp_path):
    from tools.session_store import SessionStore

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_writer.md").write_text(
        _skill_doc("graph_writer", "# Local graph writer")
    )
    store = SessionStore(tmp_path / "sessions")

    with patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool

        skill_tool = make_skill_tool(thread_id="thread-skills", store=store)
        result = skill_tool.invoke({"skill_name": "graph_writer"})

    session = store.get("thread-skills")
    assert "Stop on empty data" in result
    assert session is not None
    assert session["meta"]["loaded_skills"] == ["graph_writer"]


def test_load_skill_reuses_active_versioned_capsule(monkeypatch, tmp_path):
    from tools.session_store import SessionStore

    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    body = "# Graph rules\n" + ("Use the active table.\n" * 50)
    (skills_dir / "graph_writer.md").write_text(_skill_doc("graph_writer", body))
    store = SessionStore(tmp_path / "sessions")

    with patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool

        tool = make_skill_tool(thread_id="thread-capsule", store=store)
        first = tool.invoke({"skill_name": "graph_writer"})
        second = tool.invoke({"skill_name": "graph_writer"})

    assert len(second) < len(first)
    assert "already active" in second
    capsule = store.get("thread-capsule")["meta"]["active_skill_capsules"]["graph_writer"]
    assert "Stop on empty data" in capsule["content"]
    assert capsule["sha256"]


def test_every_local_skill_has_valid_common_manifest_and_budget():
    from tools.skill_manifest import load_skill_document

    for path in sorted(Path("agents/skills").glob("*.md")):
        document = load_skill_document(path)
        assert document.manifest.name == path.stem
        assert document.estimated_tokens <= document.manifest.max_tokens
        if document.estimated_tokens > 3_000:
            assert document.manifest.size_exemption


def test_manifest_rejects_missing_required_frontmatter(tmp_path):
    from tools.skill_manifest import SkillManifestError, load_skill_document

    path = tmp_path / "bad.md"
    path.write_text("# No manifest")

    with pytest.raises(SkillManifestError, match="frontmatter"):
        load_skill_document(path)


def test_hub_skill_with_unreviewed_hash_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    monkeypatch.setenv("SKILL_ENV", "production")
    monkeypatch.delenv("SKILL_PREFER_LOCAL", raising=False)

    local_content = _skill_doc("ecotaxa_query", "# Reviewed local content")
    hub_content = _skill_doc("ecotaxa_query", "# Drifted hub content")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "ecotaxa_query.md").write_text(local_content)

    mock_skill = MagicMock()
    mock_skill.files = {"SKILL.md": MagicMock(content=hub_content)}
    mock_instance = MagicMock()
    mock_instance.pull_skill.return_value = mock_skill

    with patch("tools.skill_tool._LangSmithClient", MagicMock(return_value=mock_instance)), \
         patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool

        result = make_skill_tool().invoke({"skill_name": "ecotaxa_query"})

    assert result.strip() == "# Reviewed local content"


def test_skill_provenance_exposes_environment_version_and_hash(monkeypatch, tmp_path):
    from tools.tool_result import validate_tool_artifact

    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("SKILL_ENV", "staging")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_writer.md").write_text(
        _skill_doc("graph_writer", "# Writer", version="2.3.0")
    )

    with patch("tools.skill_tool.SKILLS_DIR", skills_dir):
        from tools.skill_tool import make_skill_tool

        message = make_skill_tool().invoke(
            {
                "type": "tool_call",
                "id": "skill-1",
                "name": "load_skill",
                "args": {"skill_name": "graph_writer"},
            }
        )

    provenance = validate_tool_artifact(message.artifact).provenance
    assert provenance["skill"] == "graph_writer"
    assert provenance["version"] == "2.3.0"
    assert provenance["environment"] == "staging"
    assert len(provenance["sha256"]) == 64


def test_large_skill_is_fully_visible_after_model_context_preparation(monkeypatch):
    import agent as agent_module
    from tools.skill_tool import make_skill_tool

    monkeypatch.setenv("SKILL_PREFER_LOCAL", "true")
    message = make_skill_tool().invoke(
        {
            "type": "tool_call",
            "id": "skill-large",
            "name": "load_skill",
            "args": {"skill_name": "graph_writer"},
        }
    )

    prepared, metrics = agent_module._truncate_tool_results([message])

    assert prepared[0].content == message.content
    assert "Never produce a graph where exploratory and confirmed values" in prepared[0].content
    assert metrics["tool_messages_truncated"] == 0


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
    assert "from core.copepod_abundance_analysis import compute_m5" in content
    assert "Never hand-write the m5 aggregation" in content
    assert "refuses missing 0–50 m coverage" in content
    assert "compute_m5(df_canonical_sample_depth, sample_id=requested_sample_id)" in content
    assert "Do not pre-filter the dataframe before this call" in content
    assert "default to **m5" not in content
    assert "canonically map to m5" not in content
