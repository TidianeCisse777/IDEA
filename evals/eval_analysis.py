"""Evals catégorie Analysis — planification + exécution + tools appelés."""
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from agent import make_agent
from tools.session_store import default_store
from evals.judge import make_judge_evaluator
from evals.runner import run_eval_suite, print_scores

load_dotenv()

DATASET_NAME = "copepod-analysis-evals"

TSV_ABUNDANCE = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_abundance_amundsen_ctd.tsv"
TSV_STAGES = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_stages_amundsen_ctd.tsv"

ANALYSIS_CASES = [
    {
        "id": "AN-01",
        "inputs": {"file_path": TSV_ABUNDANCE, "question": "quels sont les 5 taxons les plus abondants dans ce fichier ?"},
        "outputs": {
            "criteria": (
                "The agent must: (1) identify the relevant abundance column before executing, "
                "(2) outline a plan (steps) before running code, "
                "(3) return an actual ranked list of 5 taxon names with their values. "
                "The result must come from the data, not be invented."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    {
        "id": "AN-02",
        "inputs": {"file_path": TSV_ABUNDANCE, "question": "quelle est l'abondance totale moyenne par station ?"},
        "outputs": {
            "criteria": (
                "The agent must: (1) identify the station column and the total abundance column, "
                "(2) outline a plan before executing, "
                "(3) return a numeric result or table with mean abundance per station. "
                "The values must come from the data."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    {
        "id": "AN-03",
        "inputs": {"file_path": TSV_STAGES, "question": "quelle espèce a la biomasse carbonée totale la plus élevée ?"},
        "outputs": {
            "criteria": (
                "The agent must: (1) identify the biomass column(s) (e.g. columns containing 'BIOMASS'), "
                "(2) identify the taxon column, "
                "(3) outline a plan before executing, "
                "(4) return the species name and its total biomass value. "
                "The result must come from the data."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    {
        "id": "AN-04",
        "inputs": {"file_path": TSV_ABUNDANCE, "question": "fais-moi un graphique des 10 taxons les plus abondants"},
        "outputs": {
            "criteria": (
                "The agent must produce a bar chart of the top 10 taxa by abundance. "
                "It must plan the graph first, then write correct matplotlib code. "
                "The chart must have a title, labeled axes, and display actual taxon names from the data."
            ),
            "required_tools": ["load_skill", "run_pandas"],
        },
    },
    {
        "id": "AN-05",
        "inputs": {
            "file_path": TSV_STAGES,
            "question": "montre-moi la distribution des stades copépodites (C1 à C5) pour Calanus hyperboreus",
        },
        "outputs": {
            "criteria": (
                "The agent must: (1) filter rows for Calanus hyperboreus (or closest match in TAXON_ID), "
                "(2) identify the C1 through C5 abundance columns, "
                "(3) outline a plan before executing, "
                "(4) return a table or summary showing abundance per stage. "
                "If species not found, agent must say so explicitly."
            ),
            "required_tools": ["run_pandas"],
        },
    },
]


def _extract_tools_called(messages: list) -> list[str]:
    tools_called = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc["name"] if isinstance(tc, dict) else tc.name
                tools_called.append(name)
    return tools_called


def make_tools_called_evaluator(tools_key: str = "required_tools"):
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        tools_called = outputs.get("tools_called", [])
        required = reference_outputs.get(tools_key, [])
        missing = [t for t in required if t not in tools_called]
        score = 1.0 if not missing else 0.0
        comment = "All required tools called" if not missing else f"Missing: {missing}"
        return {"key": "tools_called", "score": score, "comment": comment}
    return evaluator


def _run_analysis(inputs: dict) -> dict:
    thread_id = str(uuid.uuid4())
    default_store.clear(thread_id)
    agent = make_agent(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    agent.invoke(
        {"messages": [{"role": "user", "content": f"Charge ce fichier : {inputs['file_path']}"}]},
        config=config,
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": inputs["question"]}]},
        config=config,
    )
    tools_called = _extract_tools_called(result["messages"])
    return {"response": result["messages"][-1].content, "tools_called": tools_called}


def run_analysis_evals(experiment_prefix: str = "analysis") -> None:
    print(f"\n=== Analysis Evals ===")
    rows = run_eval_suite(
        cases=ANALYSIS_CASES,
        run_fn=_run_analysis,
        evaluators=[make_judge_evaluator("criteria"), make_tools_called_evaluator("required_tools")],
        dataset_name=DATASET_NAME,
        experiment_prefix=experiment_prefix,
        metadata={"category": "analysis", "agent_version": "slice-5"},
    )
    print_scores(rows, score_keys=["llm_judge", "tools_called"])


if __name__ == "__main__":
    run_analysis_evals()
