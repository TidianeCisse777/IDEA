"""Evals catégorie Graphs — cartes, stades, biomasse, profondeur, lacunes, temporel."""
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from agent import make_agent, invoke_verbose
from tools.session_store import default_store
from evals.judge import make_judge_evaluator, judge_with_image
from evals.runner import run_eval_suite, print_scores

load_dotenv()

DATASET_NAME = "copepod-graphs-evals"

TSV_ABUNDANCE = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_abundance_amundsen_ctd.tsv"
TSV_STAGES = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_stages_amundsen_ctd.tsv"

GRAPHS_CASES = [
    {
        "id": "GR-01",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "montre-moi les stations d'échantillonnage sur une carte",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a station map using latitude and longitude. "
                "The response must confirm the map was produced. "
                "If an image is provided, verify it shows a scatter plot of station positions "
                "with longitude on X and latitude on Y."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    {
        "id": "GR-02",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "fais une carte des stations avec l'abondance totale encodée en couleur",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a station map where color encodes total abundance. "
                "The response must confirm the map was produced. "
                "If an image is provided, verify it shows stations as colored points "
                "with a colorbar representing abundance."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    {
        "id": "GR-03",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "fais un graphique de l'abondance totale moyenne par station",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a bar chart of mean total abundance grouped by station. "
                "The response must confirm the chart was produced. "
                "If an image is provided, verify it shows stations on one axis, "
                "abundance values on the other, with a title and labeled axes."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    {
        "id": "GR-05",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "montre-moi uniquement les stations dans la baie de Baffin",
        },
        "outputs": {
            "criteria": (
                "The agent must: (1) filter the data to stations in Baffin Bay "
                "(latitude ~66-78N, longitude ~58-80W — from knowledge base or internal knowledge), "
                "(2) use run_graph to produce a map of the filtered stations. "
                "If no stations fall in the zone, the agent must say so explicitly."
            ),
            "required_tools": ["run_graph"],
        },
    },
    {
        "id": "GR-05b",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "quelles sont les coordonnées géographiques de la baie de Baffin ? donne-moi les bornes latitude et longitude",
        },
        "outputs": {
            "criteria": (
                "The response must include the approximate geographic bounds of Baffin Bay: "
                "latitude range ~66-78°N and longitude range ~58-80°W. "
                "Numeric bounds must be present in the response."
            ),
            "required_tools": ["query_copepod_knowledge_base"],
        },
    },
    {
        "id": "GR-06",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "compare l'abondance totale entre les stations de la baie de Baffin et celles du golfe du Saint-Laurent",
        },
        "outputs": {
            "criteria": (
                "The agent must: (1) filter the data for Baffin Bay and Gulf of St. Lawrence separately "
                "(using appropriate lat/lon bounds — from knowledge base or internal knowledge), "
                "(2) compute mean or total abundance per zone, "
                "(3) produce a comparison graph (bar chart or similar)."
            ),
            "required_tools": ["run_pandas", "run_graph"],
        },
    },
    {
        "id": "GR-04",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "quelles stations ont les abondances les plus élevées ? montre-moi ça sur une carte",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a map showing station positions (lat/lon) "
                "where color or size encodes total or mean abundance. "
                "The response must confirm the map was produced. "
                "If an image is provided, verify it shows a geographic scatter plot "
                "with abundance encoded visually."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    # --- Stades copépodites ---
    {
        "id": "GR-07",
        "inputs": {
            "file_path": TSV_STAGES,
            "question": "fais un graphique de la distribution des stades copépodites (C1 à C5, M, F) pour Calanus hyperboreus",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a bar chart showing the distribution of copepodite stages "
                "(C1 to C5, M, F) for Calanus hyperboreus. "
                "The response must confirm the chart was produced. "
                "If an image is provided, verify it shows stages on one axis and abundance on the other."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    {
        "id": "GR-08",
        "inputs": {
            "file_path": TSV_STAGES,
            "question": "compare la biomasse carbonée des stades C4 et C5 entre toutes les espèces",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a grouped or stacked bar chart comparing C4 vs C5 carbon biomass "
                "across species or taxa. "
                "The response must confirm the chart was produced. "
                "If an image is provided, verify it shows species on one axis and C4/C5 biomass values on the other."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    # --- Distribution verticale ---
    {
        "id": "GR-09",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "montre-moi la distribution verticale de l'abondance totale en fonction de la profondeur minimale",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a depth profile plot with depth on the Y axis "
                "(inverted so deeper values are lower) and total abundance on the X axis. "
                "The response must confirm the chart was produced. "
                "If an image is provided, verify the depth axis is inverted."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
    # --- Lacunes de données ---
    {
        "id": "GR-10",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "montre-moi les lacunes de données dans ce fichier — quelles colonnes ont le plus de valeurs manquantes ?",
        },
        "outputs": {
            "criteria": (
                "The agent must compute the count or percentage of missing values per column "
                "and report the columns with the most missing values. "
                "A text table or a bar chart are both acceptable outputs. "
                "The response must include at least the top missing-value columns with their counts or percentages."
            ),
            "required_tools": ["run_pandas"],
        },
    },
    # --- Évolution temporelle ---
    {
        "id": "GR-11",
        "inputs": {
            "file_path": TSV_ABUNDANCE,
            "question": "montre-moi l'évolution de l'abondance totale au fil des dates de déploiement",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a time-series plot of total abundance over deployment dates. "
                "The response must confirm the chart was produced. "
                "If an image is provided, verify dates are on the X axis and abundance on the Y axis."
            ),
            "required_tools": ["load_skill", "run_graph"],
        },
    },
]


def _extract_graph_image(messages: list) -> str | None:
    """Extrait le premier PNG base64 retourné par run_graph depuis les ToolMessages."""
    import re
    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None:
            continue
        if isinstance(content, list):
            parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
            content = "\n".join(parts)
        if isinstance(content, str):
            match = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", content)
            if match:
                return match.group(1)
    return None


def _extract_tools_called(messages: list) -> list[str]:
    tools_called = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc["name"] if isinstance(tc, dict) else tc.name
                tools_called.append(name)
    return tools_called


def make_vision_judge_evaluator(criteria_key: str = "criteria"):
    """Évaluateur qui juge le graphique via GPT-4o vision si une image est disponible,
    sinon tombe sur le judge texte."""
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        response = outputs.get("response", "")
        image_b64 = outputs.get("image_b64", "")
        criteria = reference_outputs.get(criteria_key, "")
        if image_b64:
            result = judge_with_image(response, image_b64, criteria)
        else:
            from evals.judge import judge
            result = judge(response, criteria)
        return {
            "key": "vision_judge",
            "score": result["score"],
            "comment": result["reasoning"],
        }
    return evaluator


def make_tools_called_evaluator(tools_key: str = "required_tools"):
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        tools_called = outputs.get("tools_called", [])
        required = reference_outputs.get(tools_key, [])
        missing = [t for t in required if t not in tools_called]
        score = 1.0 if not missing else 0.0
        comment = "All required tools called" if not missing else f"Missing: {missing}"
        return {"key": "tools_called", "score": score, "comment": comment}
    return evaluator


def _run_graph(inputs: dict) -> dict:
    thread_id = str(uuid.uuid4())
    default_store.clear(thread_id)
    agent = make_agent(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    invoke_verbose(agent, {"messages": [{"role": "user", "content": f"Charge ce fichier : {inputs['file_path']}"}]}, config)
    result = invoke_verbose(agent, {"messages": [{"role": "user", "content": inputs["question"]}]}, config)

    msgs = result.get("messages", [])
    tools_called = _extract_tools_called(msgs)
    image_b64 = _extract_graph_image(msgs)
    return {
        "response": msgs[-1].content if msgs else "",
        "tools_called": tools_called,
        "image_b64": image_b64 or "",
    }


def run_graphs_evals(experiment_prefix: str = "graphs") -> None:
    print(f"\n=== Graphs Evals ===")
    rows = run_eval_suite(
        cases=GRAPHS_CASES,
        run_fn=_run_graph,
        evaluators=[make_vision_judge_evaluator("criteria"), make_tools_called_evaluator("required_tools")],
        dataset_name=DATASET_NAME,
        experiment_prefix=experiment_prefix,
        metadata={"category": "graphs", "agent_version": "slice-5"},
    )
    print_scores(rows, score_keys=["vision_judge", "tools_called"])


if __name__ == "__main__":
    run_graphs_evals()
