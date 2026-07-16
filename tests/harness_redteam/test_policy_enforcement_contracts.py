"""Politiques critiques encore déclarées en prose au lieu d'être exécutables."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.xfail(
    strict=True,
    reason="Étapes 2A/7: registre de risque puis ApprovalGrant lié aux arguments",
)
def test_every_heavy_tool_has_an_executable_confirmation_argument(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("redteam-heavy-confirmation")
    by_name = {tool.name: tool for tool in catalog.tools}
    heavy = {
        "query_ecotaxa",
        "query_ecopart",
        "query_amundsen_ctd",
        "query_bio_oracle",
        "export_deliverable",
    }
    missing = []
    for name in sorted(heavy):
        schema = by_name[name].args_schema.model_json_schema()
        confirmed = schema.get("properties", {}).get("confirmed")
        if not confirmed or confirmed.get("default") is not False:
            missing.append(name)
    assert not missing, (
        "opérations lourdes exécutables sans confirmed=False par défaut: "
        + ", ".join(missing)
    )


def test_run_graph_is_fail_closed_when_no_graph_skill_was_loaded(tmp_path):
    from tools.data_tools import make_tools
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    run_graph = {tool.name: tool for tool in make_tools("redteam-graph", store=store)}[
        "run_graph"
    ]

    result = run_graph.invoke({"code": "pass"})

    assert result.startswith("Graph workflow blocked:"), (
        "loaded_skills vide est actuellement traité comme une autorisation implicite"
    )


def test_hub_cannot_load_a_skill_absent_from_local_allowlist(tmp_path):
    from tools.session_store import SessionStore

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "graph_writer.md").write_text("# allowed", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions")

    with patch("tools.skill_tool.SKILLS_DIR", skills_dir), patch(
        "tools.skill_tool._pull_from_hub", return_value="# rogue hub skill"
    ):
        from tools.skill_tool import make_skill_tool

        result = make_skill_tool("redteam-skill", store=store).invoke(
            {"skill_name": "rogue"}
        )

    assert "not found" in result.lower()
    assert (store.get("redteam-skill") or {}).get("meta", {}).get("loaded_skills") in (
        None,
        [],
    )
