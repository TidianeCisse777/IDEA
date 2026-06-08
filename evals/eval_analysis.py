"""Evals catégorie Analysis — planification + exécution + tools appelés."""
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from langsmith.evaluation import evaluate
from langsmith import Client

from agent import make_agent
from tools.data_tools import _sessions
from evals.judge import make_judge_evaluator

load_dotenv()

DATASET_NAME = "copepod-analysis-evals"

TSV_ABUNDANCE = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_abundance_amundsen_ctd.tsv"
TSV_STAGES = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_stages_amundsen_ctd.tsv"

ANALYSIS_CASES = [
    {
        "id": "AN-01",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "quels sont les 5 taxons les plus abondants dans ce fichier ?",
        },
        "outputs": {
            "criteria": (
                "The agent must: (1) identify the relevant abundance column before executing, "
                "(2) outline a plan (steps) before running code, "
                "(3) return an actual ranked list of 5 taxon names with their values. "
                "The result must come from the data, not be invented. "
                "Taxon names must match values found in the TAXON_ID or equivalent column."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    {
        "id": "AN-02",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "quelle est l'abondance totale moyenne par station ?",
        },
        "outputs": {
            "criteria": (
                "The agent must: (1) identify the station column and the total abundance column, "
                "(2) outline a plan before executing, "
                "(3) return a numeric result or table with mean abundance per station. "
                "The values must come from the data. "
                "The agent must not invent column names."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    {
        "id": "AN-03",
        "inputs": {
            "file_path": TSV_STAGES,
            "question": "quelle espèce a la biomasse carbonée totale la plus élevée ?",
        },
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
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "fais-moi un graphique des 10 taxons les plus abondants",
        },
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
    """Extrait les noms des tools appelés depuis l'historique de messages."""
    tools_called = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc["name"] if isinstance(tc, dict) else tc.name
                tools_called.append(name)
    return tools_called


def _run_analysis(inputs: dict) -> dict:
    """Charge le fichier puis pose la question d'analyse."""
    thread_id = str(uuid.uuid4())
    _sessions.pop(thread_id, None)

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
    return {
        "response": result["messages"][-1].content,
        "tools_called": tools_called,
    }


def make_tools_called_evaluator(tools_key: str = "required_tools"):
    """Évaluateur qui vérifie que les tools requis ont été appelés."""
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        tools_called = outputs.get("tools_called", [])
        required = reference_outputs.get(tools_key, [])
        missing = [t for t in required if t not in tools_called]
        score = 1.0 if not missing else 0.0
        comment = "All required tools called" if not missing else f"Missing: {missing}"
        return {"key": "tools_called", "score": score, "comment": comment}
    return evaluator


def run_analysis_evals(experiment_prefix: str = "analysis") -> None:
    """Lance les evals analyse et pousse dans LangSmith."""
    client = Client()

    datasets = list(client.list_datasets(dataset_name=DATASET_NAME))
    if datasets:
        client.delete_dataset(dataset_id=datasets[0].id)
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Analysis evals — planification + exécution pandas sur données NeoLab",
    )
    for case in ANALYSIS_CASES:
        client.create_example(
            inputs=case["inputs"],
            outputs=case["outputs"],
            dataset_id=dataset.id,
            metadata={"scenario_id": case["id"]},
        )
    print(f"Dataset recréé : {DATASET_NAME} ({len(ANALYSIS_CASES)} exemples)")

    results = evaluate(
        _run_analysis,
        data=DATASET_NAME,
        evaluators=[
            make_judge_evaluator("criteria"),
            make_tools_called_evaluator("required_tools"),
        ],
        experiment_prefix=experiment_prefix,
        metadata={"category": "analysis", "agent_version": "slice-5"},
    )

    rows = []
    for r in results._results:
        example = r["example"]
        sc_id = example.metadata.get("scenario_id", "?") if example.metadata else "?"
        eval_results = r["evaluation_results"]["results"]
        judge_score = next((e.score for e in eval_results if e.key == "llm_judge"), 0.0) or 0.0
        tools_score = next((e.score for e in eval_results if e.key == "tools_called"), 0.0) or 0.0
        rows.append((sc_id, judge_score, tools_score))

    rows.sort(key=lambda x: x[0])

    print(f"\n=== Analysis Evals ===")
    print(f"{'ID':<8} {'Output':>8} {'Tools':>8}")
    print("-" * 26)
    for sc_id, judge_score, tools_score in rows:
        j = "✓" if judge_score >= 0.7 else "✗"
        t = "✓" if tools_score >= 1.0 else "✗"
        print(f"  {sc_id:<8} {j} {judge_score:.2f}   {t} {tools_score:.2f}")

    avg_judge = sum(r[1] for r in rows) / len(rows) if rows else 0
    avg_tools = sum(r[2] for r in rows) / len(rows) if rows else 0
    print(f"\n  Moyenne output : {avg_judge:.2f}  |  Moyenne tools : {avg_tools:.2f}")

    if avg_judge < 0.8 or avg_tools < 0.8:
        print("\n⚠ Score < 0.8 — ne pas passer à la suite avant correction.")
    else:
        print("\n✓ Analysis validée — ok pour continuer.")


if __name__ == "__main__":
    run_analysis_evals()
