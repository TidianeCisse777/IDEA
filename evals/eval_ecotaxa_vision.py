"""EcoTaxa vision eval — measures whether the agent routes correctly
to the M3+M5 tools, respects anti-triggers, and chains workflows.

Metrics:
- M1 expected_tool_called: the first or any tool call must be the expected one.
- M2 sequence_match: tools must appear in the expected order (subsequence allowed).
- M3 forbidden_tool_absent: tools listed as forbidden must NOT be called.

Run:
    python evals/eval_ecotaxa_vision.py

Requires:
- OPENAI_API_KEY, ECOTAXA_* credentials, LANGCHAIN_API_KEY in .env
- Cache populated (POST /admin/resync or run sync once locally)
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

from agent import invoke_verbose, make_agent
from evals.runner import print_scores, run_eval_suite

load_dotenv()

DATASET_NAME = "copepod-ecotaxa-vision-evals"

# ---------------------------------------------------------------------------
# Scenarios — 20 piégeux, S3 scope from the grilling.
#
# Each case: {id, inputs.question, outputs.{expected_first_tool,
# expected_sequence, forbidden_tools, category}}
# ---------------------------------------------------------------------------

VISION_CASES = [
    # ─── Catégorie 1 : routing direct vers nouveaux tools (8 cas) ──────────
    {
        "id": "EC-01-search",
        "inputs": {"question": "Cherche les projets EcoTaxa qui contiennent du Calanus."},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_projects",
            "expected_sequence": ["find_ecotaxa_projects"],
            "forbidden_tools": ["query_ecotaxa", "list_ecotaxa_projects"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-02-schema",
        "inputs": {"question": "Quelles colonnes a le projet EcoTaxa 42 ? Je veux voir le schéma avant de l'exporter."},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_project_schema",
            "expected_sequence": ["inspect_ecotaxa_project_schema"],
            "forbidden_tools": ["query_ecotaxa", "preview_ecotaxa_project"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-03-column-distribution",
        "inputs": {"question": "Quelle est la plage de profondeur (depth_min) sur le projet EcoTaxa 42 ?"},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_column",
            "expected_sequence": ["inspect_ecotaxa_column"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-04-taxa-counts",
        "inputs": {"question": "Combien de Calanus finmarchicus sont validés dans le projet EcoTaxa 42 ?"},
        "outputs": {
            "expected_first_tool": "count_ecotaxa_taxa",
            "expected_sequence": ["count_ecotaxa_taxa"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-05-compare",
        "inputs": {"question": "Est-ce que les projets EcoTaxa 42 et 14844 sont compatibles pour un export combiné ? Y a-t-il des conflits de colonnes ?"},
        "outputs": {
            "expected_first_tool": "compare_ecotaxa_projects",
            "expected_sequence": ["compare_ecotaxa_projects"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-06-samples-region",
        "inputs": {"question": "Y a-t-il des samples EcoTaxa entre 60°N et 70°N, -80°W et -60°W ?"},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_samples_in_region",
            "expected_sequence": ["find_ecotaxa_samples_in_region"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-07-projects-region",
        "inputs": {"question": "Quels projets EcoTaxa ont des samples entre 2014 et 2016 ?"},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_projects_in_region",
            "expected_sequence": ["find_ecotaxa_projects_in_region"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    {
        "id": "EC-08-observations",
        "inputs": {"question": "Où trouve-t-on du Calanus finmarchicus validé dans les projets EcoTaxa accessibles ?"},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_observations",
            "expected_sequence": ["find_ecotaxa_observations"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "routing_direct",
        },
    },
    # ─── Catégorie 2 : anti-triggers (5 cas) ───────────────────────────────
    {
        "id": "EC-09-anti-query-for-schema",
        "inputs": {"question": "Y a-t-il une colonne température dans le projet EcoTaxa 42 ?"},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_project_schema",
            "expected_sequence": ["inspect_ecotaxa_project_schema"],
            "forbidden_tools": ["query_ecotaxa", "preview_ecotaxa_project"],
            "category": "anti_trigger",
        },
    },
    {
        "id": "EC-10-anti-list-for-search",
        "inputs": {"question": "Trouve-moi un projet EcoTaxa sur Hudson Bay."},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_projects",
            "expected_sequence": ["find_ecotaxa_projects"],
            "forbidden_tools": ["list_ecotaxa_projects", "query_ecotaxa"],
            "category": "anti_trigger",
        },
    },
    {
        "id": "EC-11-anti-query-for-counts",
        "inputs": {"question": "Quel est le ratio validé/prédit pour les Copepoda dans le projet 42 ?"},
        "outputs": {
            "expected_first_tool": "count_ecotaxa_taxa",
            "expected_sequence": ["count_ecotaxa_taxa"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "anti_trigger",
        },
    },
    {
        "id": "EC-12-anti-query-for-distribution",
        "inputs": {"question": "Quelle est la distribution de la colonne area sur le projet 42 ?"},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_column",
            "expected_sequence": ["inspect_ecotaxa_column"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "anti_trigger",
        },
    },
    {
        "id": "EC-13-anti-preview-for-schema",
        "inputs": {"question": "Quels sont les free fields disponibles sur le projet 42 ?"},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_project_schema",
            "expected_sequence": ["inspect_ecotaxa_project_schema"],
            "forbidden_tools": ["preview_ecotaxa_project", "query_ecotaxa"],
            "category": "anti_trigger",
        },
    },
    # ─── Catégorie 3 : chaînage de workflows (3 cas) ───────────────────────
    {
        "id": "EC-14-chain-compare-then-warn",
        "inputs": {"question": "Je veux exporter les projets EcoTaxa 42 et 14844 ensemble. Vérifie d'abord si c'est compatible."},
        "outputs": {
            "expected_first_tool": "compare_ecotaxa_projects",
            "expected_sequence": ["compare_ecotaxa_projects"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "workflow_chain",
        },
    },
    {
        "id": "EC-15-chain-schema-before-export",
        "inputs": {"question": "Avant d'exporter le projet 42, montre-moi le schéma."},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_project_schema",
            "expected_sequence": ["inspect_ecotaxa_project_schema"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "workflow_chain",
        },
    },
    {
        "id": "EC-16-chain-observations-then-count",
        "inputs": {"question": "Trouve où il y a du Calanus glacialis dans les projets accessibles, puis donne-moi le ratio V/P par projet."},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_observations",
            "expected_sequence": ["find_ecotaxa_observations", "count_ecotaxa_taxa"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "workflow_chain",
        },
    },
    # ─── Catégorie 4 : error recovery + cas piégeux (4 cas) ────────────────
    {
        "id": "EC-17-ambiguous-taxon",
        "inputs": {"question": "Combien de Copepoda dans le projet 42 ?"},
        "outputs": {
            "expected_first_tool": "count_ecotaxa_taxa",
            "expected_sequence": ["count_ecotaxa_taxa"],
            "forbidden_tools": [],
            "category": "error_recovery",
        },
    },
    {
        "id": "EC-18-ambiguous-column",
        "inputs": {"question": "Distribution de la colonne 'orig_id' sur le projet 42, niveau sample."},
        "outputs": {
            "expected_first_tool": "inspect_ecotaxa_column",
            "expected_sequence": ["inspect_ecotaxa_column"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "error_recovery",
        },
    },
    {
        "id": "EC-19-cache-empty-handling",
        "inputs": {"question": "Y a-t-il des samples dans l'océan Atlantique sud (entre -60°S et -40°S, -50°W et -30°W) ?"},
        "outputs": {
            "expected_first_tool": "find_ecotaxa_samples_in_region",
            "expected_sequence": ["find_ecotaxa_samples_in_region"],
            "forbidden_tools": ["query_ecotaxa"],
            "category": "error_recovery",
        },
    },
    {
        "id": "EC-20-no-tool-needed",
        "inputs": {"question": "Quels sont les principaux instruments utilisés pour échantillonner le zooplancton ?"},
        "outputs": {
            "expected_first_tool": "query_copepod_knowledge_base",
            "expected_sequence": ["query_copepod_knowledge_base"],
            "forbidden_tools": [
                "query_ecotaxa",
                "find_ecotaxa_observations",
                "find_ecotaxa_samples_in_region",
            ],
            "category": "error_recovery",
        },
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _capture_tool_calls(state) -> list[str]:
    """Extract the ordered list of tool names called in this run."""
    tools_called: list[str] = []
    for msg in state.get("messages", []):
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            name = tc["name"] if isinstance(tc, dict) else tc.name
            tools_called.append(name)
    return tools_called


def run_one_case(inputs: dict) -> dict:
    """Invoke the agent on a single question, return the tool sequence."""
    thread_id = uuid.uuid4().hex[:12]
    agent = make_agent(thread_id, user_id="eval-bot")
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"user_id": "eval-bot"},
    }
    final_state = invoke_verbose(
        agent,
        {"messages": [{"role": "user", "content": inputs["question"]}]},
        config,
    )
    tools_called = _capture_tool_calls(final_state)
    final_msg = final_state.get("messages", [])
    final_text = ""
    if final_msg:
        final_text = getattr(final_msg[-1], "content", "") or ""
    return {
        "tools_called": tools_called,
        "final_answer": final_text[:1000],
    }


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

def evaluator_expected_first_tool(run, example) -> dict:
    """M1: the FIRST tool call must match expected_first_tool."""
    tools = run.outputs.get("tools_called", []) if run.outputs else []
    expected = example.outputs["expected_first_tool"]
    if not tools:
        return {"key": "expected_first_tool", "score": 0,
                "comment": f"No tool was called (expected {expected})."}
    actual = tools[0]
    if actual == expected:
        return {"key": "expected_first_tool", "score": 1, "comment": ""}
    if expected in tools:
        return {"key": "expected_first_tool", "score": 0.5,
                "comment": f"Expected {expected} as FIRST tool, came later. Actual first: {actual}."}
    return {"key": "expected_first_tool", "score": 0,
            "comment": f"Expected {expected}; got sequence {tools}."}


def evaluator_sequence_subsequence(run, example) -> dict:
    """M2: expected_sequence must appear as an in-order subsequence."""
    tools = run.outputs.get("tools_called", []) if run.outputs else []
    expected_seq = example.outputs.get("expected_sequence", [])
    if not expected_seq:
        return {"key": "sequence_match", "score": 1, "comment": "No sequence required."}
    idx = 0
    for tool in tools:
        if idx < len(expected_seq) and tool == expected_seq[idx]:
            idx += 1
    if idx == len(expected_seq):
        return {"key": "sequence_match", "score": 1, "comment": ""}
    missing = expected_seq[idx:]
    return {"key": "sequence_match", "score": 0,
            "comment": f"Missing {missing} from actual sequence {tools}."}


def evaluator_forbidden_tools(run, example) -> dict:
    """M3: forbidden_tools must NOT appear in the actual sequence."""
    tools = run.outputs.get("tools_called", []) if run.outputs else []
    forbidden = set(example.outputs.get("forbidden_tools", []))
    violations = [t for t in tools if t in forbidden]
    if not violations:
        return {"key": "forbidden_tool_absent", "score": 1, "comment": ""}
    return {"key": "forbidden_tool_absent", "score": 0,
            "comment": f"Forbidden tools called: {violations}."}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Optional subset for cheap smoke runs: EVAL_CASE_IDS="EC-01-search,EC-09-anti-query-for-schema"
    only_ids = os.getenv("EVAL_CASE_IDS")
    if only_ids:
        wanted = {x.strip() for x in only_ids.split(",") if x.strip()}
        cases = [c for c in VISION_CASES if c["id"] in wanted]
        print(f"Subset mode: running {len(cases)} scenario(s): {[c['id'] for c in cases]}")
    else:
        cases = VISION_CASES

    rows = run_eval_suite(
        cases=cases,
        run_fn=run_one_case,
        evaluators=[
            evaluator_expected_first_tool,
            evaluator_sequence_subsequence,
            evaluator_forbidden_tools,
        ],
        dataset_name=DATASET_NAME,
        experiment_prefix="ecotaxa-vision",
        metadata={
            "milestone": "M3+M5",
            "model": os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
        },
    )
    print_scores(
        rows,
        score_keys=[
            "expected_first_tool",
            "sequence_match",
            "forbidden_tool_absent",
        ],
        threshold=0.8,
    )

    # Breakdown by category
    print("\n=== Score breakdown by category ===")
    by_cat: dict[str, list] = {}
    for case in VISION_CASES:
        cat = case["outputs"]["category"]
        by_cat.setdefault(cat, []).append(case["id"])
    score_lookup = {sc_id: scores for sc_id, scores, _ in rows}
    for cat, ids in by_cat.items():
        cat_scores = {"expected_first_tool": [], "sequence_match": [], "forbidden_tool_absent": []}
        for sc_id in ids:
            scores = score_lookup.get(sc_id, {})
            for k in cat_scores:
                cat_scores[k].append(scores.get(k, 0))
        avg = lambda lst: sum(lst) / len(lst) if lst else 0
        print(f"  {cat:<18} | first={avg(cat_scores['expected_first_tool']):.2f}  "
              f"seq={avg(cat_scores['sequence_match']):.2f}  "
              f"forbid={avg(cat_scores['forbidden_tool_absent']):.2f}  "
              f"(n={len(ids)})")


if __name__ == "__main__":
    main()
