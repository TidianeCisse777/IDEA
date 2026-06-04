import scripts.evals.run_copepod_lean_eval as lean_eval
from scripts.evals.run_copepod_graph_happy_path_eval import (
    GRAPH_HAPPY_PATH_SCENARIOS,
    run_graph_happy_path_eval,
)


def test_graph_happy_path_runner_exposes_dedicated_scenario_slugs():
    slugs = {scenario.slug for scenario in GRAPH_HAPPY_PATH_SCENARIOS}
    assert "uvp_enriched_reasoning_code" in slugs
    assert "ecotaxa_simple_reasoning_code" in slugs
    assert "neolabs_ctd_production_flow" in slugs


def test_graph_happy_path_runner_does_not_mutate_base_scenarios(monkeypatch):
    original_slugs = [scenario.slug for scenario in lean_eval.SCENARIOS]

    def fake_run_lean_eval(*, scenario_slugs=None, completion_fn=None):
        current_slugs = [scenario.slug for scenario in lean_eval.SCENARIOS]
        assert "uvp_enriched_reasoning_code" in current_slugs
        assert "ecotaxa_simple_reasoning_code" in current_slugs
        assert "neolabs_ctd_production_flow" in current_slugs
        return {
            "mode": "lean",
            "model": "fake",
            "passed": True,
            "passed_count": 1,
            "total_count": 1,
            "results": [],
        }

    monkeypatch.setattr(lean_eval, "run_lean_eval", fake_run_lean_eval)

    run_graph_happy_path_eval(scenario_slugs=["uvp_enriched_reasoning_code"])

    assert [scenario.slug for scenario in lean_eval.SCENARIOS] == original_slugs
    assert "uvp_enriched_reasoning_code" not in original_slugs
    assert "ecotaxa_simple_reasoning_code" not in original_slugs
    assert "neolabs_ctd_production_flow" not in original_slugs
