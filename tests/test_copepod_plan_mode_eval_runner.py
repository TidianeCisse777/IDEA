from scripts.evals.run_copepod_plan_mode_eval import run_mock_eval


def test_mock_eval_runner_passes_context_workflow():
    report = run_mock_eval(push_langfuse=False)

    assert report["passed"] is True
    assert report["passed_count"] == report["total_count"]
    assert report["dataset"] == "copepod-plan-mode-v1"

    scores = {item["name"]: item for item in report["results"]}
    assert report["total_count"] >= 10
    assert scores["upload_ecotaxa_creates_data_understanding"]["passed"] is True
    assert scores["analyse_blocked_before_active_artifacts"]["passed"] is True
    assert scores[
        "graph_context_without_data_understanding_version_is_blocked"
    ]["passed"] is True
    assert scores["plan_ready_button_not_emitted_before_minimum_turns"]["passed"] is True
    assert scores["data_understanding_confirmation_activates_artifact"]["passed"] is True
    assert scores["graph_context_draft_links_to_active_du"]["passed"] is True
    assert scores["plan_ready_after_graph_context_activation"]["passed"] is True
    assert scores["upload_in_analyse_creates_draft_without_replan"]["passed"] is True
    assert scores[
        "analyse_blocked_when_graph_context_references_stale_data_understanding"
    ]["passed"] is True
    assert scores["artifact_debug_routes_are_copepod_only"]["passed"] is True
