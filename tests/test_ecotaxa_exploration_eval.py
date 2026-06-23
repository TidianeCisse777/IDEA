from evals.eval_ecotaxa_exploration import (
    EXPLORATION_CASES,
    _apply_quick_defaults,
    _chunks,
    final_answer_contains,
    forbidden_tools_absent,
    required_tool_args_present,
    trajectory_subsequence,
)
from argparse import Namespace


def _case(case_id: str) -> dict:
    return next(case for case in EXPLORATION_CASES if case["id"] == case_id)


def test_trajectory_subsequence_allows_extra_tools_between_expected_steps():
    outputs = {
        "trajectory": [
            "query_copepod_knowledge_base",
            "load_skill",
            "get_zone_info",
            "find_ecotaxa_samples_in_region",
        ]
    }
    reference = {
        "expected_sequence": [
            "load_skill",
            "find_ecotaxa_samples_in_region",
        ]
    }

    result = trajectory_subsequence(outputs, reference)

    assert result["score"] == 1


def test_trajectory_subsequence_accepts_alternative_tools_for_a_step():
    outputs = {
        "trajectory": [
            "load_skill",
            "summarize_ecotaxa_project",
        ]
    }
    reference = {
        "expected_sequence": [
            "load_skill",
            ["summarize_ecotaxa_project", "summarize_ecotaxa_projects"],
        ]
    }

    result = trajectory_subsequence(outputs, reference)

    assert result["score"] == 1


def test_trajectory_subsequence_scores_late_expected_step_partially():
    outputs = {"trajectory": ["inspect_ecotaxa_column"]}
    reference = {
        "expected_sequence": [
            "load_skill",
            "inspect_ecotaxa_column",
        ]
    }

    result = trajectory_subsequence(outputs, reference)

    assert result["score"] == 0.5
    assert "load_skill" in result["comment"]


def test_forbidden_tools_absent_rejects_exports_for_read_only_case():
    outputs = {
        "trajectory": [
            "load_skill",
            "summarize_ecotaxa_project",
            "query_ecotaxa",
        ]
    }
    reference = {"forbidden_tools": ["query_ecotaxa", "run_pandas"]}

    result = forbidden_tools_absent(outputs, reference)

    assert result["score"] == 0
    assert "query_ecotaxa" in result["comment"]


def test_required_tool_args_present_accepts_recursive_subset():
    outputs = {
        "tool_calls": [
            {
                "name": "find_ecotaxa_samples_in_region",
                "arguments": {
                    "zone_name": "Baie de Baffin",
                    "date_range": {
                        "from": "2024-10-01",
                        "to": "2024-10-31",
                    },
                    "project_ids": [2331, 14853],
                },
            }
        ]
    }
    reference = {
        "required_tool_args": [
            {
                "name": "find_ecotaxa_samples_in_region",
                "args": {
                    "zone_name": "Baie de Baffin",
                    "project_ids": [14853, 2331],
                },
            }
        ]
    }

    result = required_tool_args_present(outputs, reference)

    assert result["score"] == 1


def test_required_tool_args_present_rejects_wrong_parameter_value():
    outputs = {
        "tool_calls": [
            {
                "name": "export_ecotaxa_samples",
                "arguments": {
                    "sample_ids": [14853000001, 14853000002],
                    "confirmed": True,
                },
            }
        ]
    }
    reference = {
        "required_tool_args": [
            {
                "name": "export_ecotaxa_samples",
                "args": {
                    "sample_ids": [14853000001, 14853000002],
                    "confirmed": False,
                },
            }
        ]
    }

    result = required_tool_args_present(outputs, reference)

    assert result["score"] == 0
    assert "confirmed" in result["comment"]


def test_required_tool_args_present_scores_partial_progress():
    outputs = {
        "tool_calls": [
            {
                "name": "load_skill",
                "arguments": {"skill_name": "ecotaxa_navigation"},
            },
            {
                "name": "summarize_ecotaxa_project",
                "arguments": {"project_id": 99999},
            },
        ]
    }
    reference = {
        "required_tool_args": [
            {
                "name": "load_skill",
                "args": {"skill_name": "ecotaxa_navigation"},
            },
            {
                "name": "summarize_ecotaxa_project",
                "args": {"project_id": 14853},
            },
        ]
    }

    result = required_tool_args_present(outputs, reference)

    assert result["score"] == 0.5
    assert "summarize_ecotaxa_project" in result["comment"]


def test_final_answer_contains_scores_required_source_links():
    outputs = {
        "final_answer": (
            "Sample [14853000001]"
            "(https://ecotaxa.obs-vlfr.fr/prj/14853?samples=14853000001)"
        )
    }
    reference = {
        "final_answer_contains": ["ecotaxa.obs-vlfr.fr", "/prj/"]
    }

    result = final_answer_contains(outputs, reference)

    assert result["score"] == 1


def test_final_answer_contains_reports_missing_source_links():
    outputs = {"final_answer": "Sample 14853000001"}
    reference = {
        "final_answer_contains": ["ecotaxa.obs-vlfr.fr", "/prj/"]
    }

    result = final_answer_contains(outputs, reference)

    assert result["score"] == 0
    assert "ecotaxa.obs-vlfr.fr" in result["comment"]


def test_chunks_splits_cases_into_requested_batch_size():
    cases = [{"id": str(index)} for index in range(7)]

    chunks = _chunks(cases, 3)

    assert [[case["id"] for case in chunk] for chunk in chunks] == [
        ["0", "1", "2"],
        ["3", "4", "5"],
        ["6"],
    ]


def test_apply_quick_defaults_sets_fast_stable_eval_options():
    args = Namespace(
        quick=True,
        max_concurrency=9,
        case_delay=0,
        retry_delay=30,
        max_attempts=5,
        output_tokens=1200,
        batch_size=None,
    )

    _apply_quick_defaults(args)

    assert args.max_concurrency == 3
    assert args.case_delay == 0.0
    assert args.retry_delay == 10.0
    assert args.max_attempts == 3
    assert args.output_tokens == 600
    assert args.batch_size == 3


def test_mixed_taxon_zone_month_depth_prompt_routes_to_observations():
    case = _case("EX-31-taxon-zone-month-depth")
    outputs = case["outputs"]

    assert outputs["expected_sequence"] == [
        "load_skill",
        "get_zone_info",
        "find_ecotaxa_observations",
    ]
    assert "find_ecotaxa_samples_in_region" in outputs["forbidden_tools"]
    result = required_tool_args_present(
        {
            "tool_calls": [
                {
                    "name": "load_skill",
                    "arguments": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "get_zone_info",
                    "arguments": {"zone_name": "Baie de Baffin"},
                },
                {
                    "name": "find_ecotaxa_observations",
                    "arguments": {
                        "taxon": "Calanus finmarchicus",
                        "zone_name": "Baie de Baffin",
                        "month": 7,
                        "depth_max_lt": 100,
                    },
                }
            ]
        },
        outputs,
    )
    assert result["score"] == 1


def test_mixed_samples_zone_month_depth_prompt_routes_to_samples_without_taxon():
    case = _case("EX-32-samples-zone-month-depth-no-taxon")
    outputs = case["outputs"]

    assert outputs["expected_sequence"] == [
        "load_skill",
        "get_zone_info",
        "find_ecotaxa_samples_in_region",
    ]
    assert "find_ecotaxa_observations" in outputs["forbidden_tools"]
    result = required_tool_args_present(
        {
            "tool_calls": [
                {
                    "name": "load_skill",
                    "arguments": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "get_zone_info",
                    "arguments": {"zone_name": "Baie de Baffin"},
                },
                {
                    "name": "find_ecotaxa_samples_in_region",
                    "arguments": {
                        "zone_name": "Baie de Baffin",
                        "month": 7,
                        "depth_max_lt": 100,
                    },
                }
            ]
        },
        outputs,
    )
    assert result["score"] == 1


def test_mixed_taxon_zone_date_depth_status_prompt_preserves_all_filters():
    case = _case("EX-33-taxon-zone-date-depth-status-all")
    outputs = case["outputs"]

    result = required_tool_args_present(
        {
            "tool_calls": [
                {
                    "name": "load_skill",
                    "arguments": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "get_zone_info",
                    "arguments": {"zone_name": "Baie d'Hudson"},
                },
                {
                    "name": "find_ecotaxa_observations",
                    "arguments": {
                        "taxon": "Copepoda",
                        "zone_name": "Baie d'Hudson",
                        "date_range": {
                            "from": "2018-06-01",
                            "to": "2018-06-30",
                        },
                        "depth_max_gte": 100,
                        "status": "all",
                    },
                }
            ]
        },
        outputs,
    )
    assert result["score"] == 1
