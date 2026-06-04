import scripts.evals.run_copepod_graph_happy_path_multiturn_eval as multiturn_eval


def test_multiturn_runner_exposes_uvp_validation_followup_slug():
    slugs = {scenario.slug for scenario in multiturn_eval.MULTITURN_SCENARIOS}
    assert "uvp_enriched_after_validation_clarification" in slugs


def test_multiturn_runner_exposes_neolabs_validation_followup_slug():
    slugs = {scenario.slug for scenario in multiturn_eval.MULTITURN_SCENARIOS}
    assert "neolabs_ctd_after_validation_clarification" in slugs
