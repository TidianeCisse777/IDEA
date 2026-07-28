"""Regression contract: active skills must be reused across the session."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_guidance_never_requires_reloading_active_graph_skills():
    """Permanent prompt, skills, and tool schemas must agree on session reuse."""
    sources = {
        "graph_routing": ROOT / "agents" / "graph_output_routing_rules.py",
        "graph_planner": ROOT / "agents" / "skills" / "graph_planner.md",
        "ecotaxa_navigation": ROOT / "agents" / "skills" / "ecotaxa_navigation.md",
        "net_uvp": ROOT / "agents" / "skills" / "net_uvp_abundance_comparison.md",
        "hydrodynamic": ROOT / "agents" / "skills" / "copepod_hydrodynamic_micro_zoom.md",
        "ecotaxa_tools": ROOT / "tools" / "copepod_sources.py",
    }
    text = {name: path.read_text(encoding="utf-8") for name, path in sources.items()}
    tick = chr(96)

    assert "Every EcoTaxa map request must load" not in text["graph_routing"]
    assert "the current turn must load both graph skills" not in text["ecotaxa_navigation"]
    assert f"load {tick}graph_writer{tick} directly" not in text["graph_planner"]
    assert f'first call {tick}load_skill("graph_writer"){tick}' not in text["graph_planner"]
    assert f'call {tick}load_skill("graph_writer"){tick} then {tick}run_graph{tick}' not in text["net_uvp"]
    assert "Visual request: load" not in text["hydrodynamic"]
    assert "Routing requirement: before calling this tool" not in text["ecotaxa_tools"]

    assert "already-active graph workflow" in text["graph_routing"]
    assert "already-active graph workflow" in text["graph_planner"]
    assert "never reload either skill in a later turn" in text["ecotaxa_navigation"].lower()
    assert "already-active graph rules" in text["net_uvp"]
    assert "already-active graph workflow" in text["hydrodynamic"]
    assert "already pre-activated with this source family" in text["ecotaxa_tools"]
