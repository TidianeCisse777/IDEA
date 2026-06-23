"""Evals — connaissance copépodes & taxonomie marine (WoRMS + RAG + Wikipedia)."""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

from agent import invoke_verbose, make_agent
from evals.judge import make_judge_evaluator
from evals.runner import print_scores, run_eval_suite
from tools.session_store import default_store

load_dotenv()

DATASET_NAME = "copepod-taxonomy-knowledge"

TAXONOMY_CASES = [
    {
        "id": "TX-01-hyperboreus",
        "inputs": {"question": "Qu'est-ce que Calanus hyperboreus et quel est son rôle écologique ?"},
        "outputs": {
            "criteria": (
                "The agent must identify Calanus hyperboreus as a copepod of the order Calanoida, "
                "family Calanidae, with AphiaID 104467. "
                "It must mention its large size relative to other Calanus species and its high lipid content (wax esters). "
                "It must mention its role as prey for the North Atlantic right whale OR its long diapause at stage CV. "
                "Numerical values (AphiaID, sizes) must NOT be invented and must match the RAG knowledge base."
            ),
        },
    },
    {
        "id": "TX-02-aphiaid-glacialis",
        "inputs": {"question": "Quel est l'AphiaID WoRMS de Calanus glacialis ?"},
        "outputs": {
            "criteria": (
                "The agent must return the AphiaID 104465 for Calanus glacialis. "
                "It must NOT invent a different number. "
                "It is acceptable to also mention that the value was validated via WoRMS or the marine taxonomy lookup."
            ),
        },
    },
    {
        "id": "TX-03-finmarchicus-vs-glacialis",
        "inputs": {
            "question": (
                "Quelles différences écologiques et d'identification entre "
                "Calanus finmarchicus et Calanus glacialis ?"
            )
        },
        "outputs": {
            "criteria": (
                "The agent must identify finmarchicus as the boreal North Atlantic species and "
                "glacialis as the dominant Arctic shelf species. "
                "It must mention that morphological identification (e.g. prosome length) is unreliable "
                "in overlap zones such as the Gulf of Saint-Lawrence and that molecular markers are required. "
                "Habitat / range distinctions must be coherent with the RAG knowledge — no invented values."
            ),
        },
    },
    {
        "id": "TX-04-stage-cv",
        "inputs": {"question": "Que signifie le stade CV chez un copépode calanoïde ?"},
        "outputs": {
            "criteria": (
                "The agent must explain that CV is the fifth copepodite stage (juvenile stage just before adulthood). "
                "It must mention that CV is the stage at which Calanus species enter diapause / overwinter. "
                "It must NOT invent biological details not supported by the RAG or WoRMS lookup."
            ),
        },
    },
    {
        "id": "TX-05-oithona-similis",
        "inputs": {"question": "C'est quoi Oithona similis et pourquoi c'est important pour le cycle du carbone ?"},
        "outputs": {
            "criteria": (
                "The agent must identify Oithona similis as a small cyclopoid copepod (order Cyclopoida, AphiaID 106485). "
                "It must mention its role in recycling carbon at the surface, "
                "e.g. by consuming fecal pellets of Calanus, partially counteracting the biological carbon pump. "
                "Numerical or taxonomic facts (order, AphiaID) must NOT be invented."
            ),
        },
    },
    {
        "id": "TX-06-unknown-taxon",
        "inputs": {"question": "Cherche-moi le taxon marin 'Zzzpseudotaxonus inexistans'."},
        "outputs": {
            "criteria": (
                "The agent must explicitly say that the taxon could not be resolved / was not found in WoRMS "
                "and that no definition exists in the local RAG. "
                "It must NOT invent an AphiaID, a classification, or a fake description. "
                "Saying 'inconnu', 'introuvable', 'non résolu' or equivalent is required."
            ),
        },
    },
]


def _run_taxonomy(inputs: dict) -> dict:
    thread_id = str(uuid.uuid4())
    default_store.clear(thread_id)
    agent = make_agent(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    result = invoke_verbose(
        agent,
        {"messages": [{"role": "user", "content": inputs["question"]}]},
        config,
    )
    msgs = result.get("messages", [])
    return {"response": msgs[-1].content if msgs else ""}


def run_taxonomy_evals(experiment_prefix: str = "taxonomy-knowledge") -> None:
    print(f"\n=== Taxonomy Knowledge Evals ({len(TAXONOMY_CASES)} cas) ===")
    rows = run_eval_suite(
        cases=TAXONOMY_CASES,
        run_fn=_run_taxonomy,
        evaluators=[make_judge_evaluator("criteria")],
        dataset_name=DATASET_NAME,
        experiment_prefix=experiment_prefix,
        metadata={
            "category": "taxonomy",
            "branch": "feature/marine-taxonomy-lookup",
        },
        max_concurrency=3,
    )
    print_scores(rows, score_keys=["llm_judge"])


if __name__ == "__main__":
    run_taxonomy_evals()
