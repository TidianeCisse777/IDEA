"""Evals catégorie Inspection — SC-13 : l'agent comprend le fichier chargé."""
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

DATASET_NAME = "copepod-inspection-evals"

TSV_UVP = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/uvp_amundsen_1165_ecotaxa_object_sample.tsv"
TSV_CTD = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/amundsen_12713_ctd_2018_sample.tsv"

INSPECTION_CASES = [
    {
        "id": "SC-13a",
        "inputs": {"file_path": TSV_UVP, "question": "qu'est-ce que contient ce fichier ?"},
        "outputs": {
            "criteria": (
                "The agent must identify this as an EcoTaxa or UVP5 export. "
                "It must mention at least two key columns (e.g. obj_orig_id, obj_depth_min, txo_display_name). "
                "It must describe what kind of data is present (zooplankton objects, depth, taxonomy). "
                "It must NOT invent information not present in the file."
            ),
        },
    },
    {
        "id": "SC-13b",
        "inputs": {
            "file_path": TSV_UVP,
            "question": "quelles sont les colonnes importantes dans ce fichier et à quoi servent-elles ?",
        },
        "outputs": {
            "criteria": (
                "The agent must identify the key columns: obj_orig_id, obj_depth_min, txo_display_name. "
                "For each, it must provide a meaningful description of what it represents. "
                "Descriptions must come from the knowledge base, not be invented. "
                "Column names must be exact — not paraphrased or translated."
            ),
        },
    },
    {
        "id": "SC-13c",
        "inputs": {
            "file_path": TSV_UVP,
            "question": "que signifie la colonne obj_orig_id dans ce fichier ?",
        },
        "outputs": {
            "criteria": (
                "The agent must explain that obj_orig_id is the original object identifier from EcoTaxa. "
                "It must mention that this column links the object to a profile (e.g. profile_id extraction). "
                "The explanation must come from the knowledge base. "
                "If not found in the knowledge base, the agent must say so explicitly — not guess."
            ),
        },
    },
    {
        "id": "SC-13d",
        "inputs": {
            "file_path": TSV_UVP,
            "question": "que signifie la colonne txo_display_name dans ce fichier ?",
        },
        "outputs": {
            "criteria": (
                "The agent must explain that txo_display_name is the taxonomic name (species or group) "
                "assigned to the object in EcoTaxa. "
                "The explanation must come from the knowledge base. "
                "If not found, the agent must say so explicitly — not guess."
            ),
        },
    },
    {
        "id": "SC-13e",
        "inputs": {
            "file_path": TSV_CTD,
            "question": "qu'est-ce que contient ce fichier CTD et quelles sont ses colonnes importantes ?",
        },
        "outputs": {
            "criteria": (
                "The agent must identify this as a CTD file containing oceanographic measurements. "
                "It must mention at least one column related to depth, temperature, or salinity. "
                "It must describe what those columns represent. "
                "It must NOT invent column names or definitions not present in the file."
            ),
        },
    },
    {
        "id": "SC-13f",
        "inputs": {
            "file_path": TSV_UVP,
            "question": "en regardant les colonnes de ce fichier, qu'est-ce que tu comprends de ce que je manipule comme données ?",
        },
        "outputs": {
            "criteria": (
                "The agent must demonstrate understanding of the data: "
                "identify it as individual zooplankton objects from EcoTaxa/UVP5, "
                "mention that columns like obj_depth_min represent depth measurements, "
                "and txo_display_name represents taxonomy. "
                "The response must be grounded in what is actually in the file, not generic knowledge."
            ),
        },
    },
]


def _run_inspection(inputs: dict) -> dict:
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
    return {"response": result["messages"][-1].content}


def run_inspection_evals(experiment_prefix: str = "inspection") -> None:
    print(f"\n=== Inspection Evals ===")
    rows = run_eval_suite(
        cases=INSPECTION_CASES,
        run_fn=_run_inspection,
        evaluators=[make_judge_evaluator("criteria")],
        dataset_name=DATASET_NAME,
        experiment_prefix=experiment_prefix,
        metadata={"category": "inspection", "agent_version": "slice-5"},
    )
    print_scores(rows, score_keys=["llm_judge"])


if __name__ == "__main__":
    run_inspection_evals()
