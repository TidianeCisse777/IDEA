"""Evals catégorie Graphs — cartes, stades, biomasse, profondeur, biodiversité."""
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

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
TSV_ABUNDANCE = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_abundance_amundsen_ctd.tsv"
TSV_STAGES = "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_stages_amundsen_ctd.tsv"
TSV_BIODIVERSITY = os.path.join(REPO_ROOT, "data/demo/neolabs_taxonomy_2014_2020.tsv")

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
                "The agent must filter the data to stations in Baffin Bay "
                "(latitude ~66-78N, longitude ~58-80W). "
                "A map OR a list/table of the filtered stations are both acceptable. "
                "If no stations fall in the zone, the agent must say so explicitly."
            ),
            "required_tools": ["run_pandas"],
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
                "The agent must filter the data for Baffin Bay and Gulf of St. Lawrence separately "
                "(using appropriate lat/lon bounds) and compute mean or total abundance per zone. "
                "A comparison table OR a bar chart are both acceptable outputs. "
                "The response must include numeric values for each zone."
            ),
            "required_tools": ["run_pandas"],
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
                "The agent must identify C4 and C5 carbon biomass columns and compare them across species or taxa. "
                "A table OR a bar chart are both acceptable outputs. "
                "The response must include C4 and C5 values for multiple species."
            ),
            "required_tools": ["run_pandas"],
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
    # --- Biodiversité / communauté ---
    {
        "id": "GR-12",
        "inputs": {
            "file_path": TSV_BIODIVERSITY,
            "question": "trace une courbe de rarefaction de la richesse taxonomique par station",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a rarefaction curve for taxon richness by station or sample group. "
                "The chart must have sampling effort or sample size on one axis and expected richness on the other. "
                "The agent should treat the result as exploratory if the source values are normalized abundances."
            ),
            "required_tools": ["load_skill", "run_graph"],
            "required_skills": ["neolabs_abundance_analysis", "graph_planner", "graph_writer"],
        },
    },
    {
        "id": "GR-13",
        "inputs": {
            "file_path": TSV_BIODIVERSITY,
            "question": "fais une NMDS Bray-Curtis de la composition taxonomique coloree par station",
        },
        "outputs": {
            "criteria": (
                "The agent must build a sample by taxon matrix and produce an exploratory NMDS using Bray-Curtis dissimilarity. "
                "The plot must show two ordination axes and points colored or grouped by station. "
                "The response must not claim causality or biological interpretation."
            ),
            "required_tools": ["load_skill", "run_graph"],
            "required_skills": ["neolabs_abundance_analysis", "graph_planner", "graph_writer"],
        },
    },
    {
        "id": "GR-14",
        "inputs": {
            "file_path": TSV_BIODIVERSITY,
            "question": "fais une heatmap de composition taxonomique des 20 taxons dominants par station",
        },
        "outputs": {
            "criteria": (
                "The agent must produce a heatmap where one axis is station, the other is dominant taxa, "
                "and color encodes abundance or log-transformed abundance. "
                "The agent must aggregate taxon-level rows before plotting."
            ),
            "required_tools": ["load_skill", "run_graph"],
            "required_skills": ["neolabs_abundance_analysis", "graph_planner", "graph_writer"],
        },
    },
    {
        "id": "GR-15",
        "inputs": {
            "file_path": TSV_BIODIVERSITY,
            "question": "trace une courbe rank-abundance des taxons de copepodes",
        },
        "outputs": {
            "criteria": (
                "The agent must rank taxa by total abundance and produce a rank-abundance curve. "
                "The X axis must represent taxon rank and the Y axis abundance or relative abundance, "
                "preferably with a log scale for abundance."
            ),
            "required_tools": ["load_skill", "run_graph"],
            "required_skills": ["neolabs_abundance_analysis", "graph_planner", "graph_writer"],
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


def _extract_graph_markdown(messages: list) -> str | None:
    """Extract the first graph markdown URL returned by run_graph."""
    import re

    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None:
            continue
        if isinstance(content, list):
            parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
            content = "\n".join(parts)
        if not isinstance(content, str):
            continue
        match = re.search(r"!\[[^\]]*\]\((?:https?://[^)\s]+)?/graphs/[A-Za-z0-9_.-]+\.png\)", content)
        if match:
            return match.group(0)
    return None


def _extract_tools_called(messages: list) -> list[str]:
    tools_called = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc["name"] if isinstance(tc, dict) else tc.name
                tools_called.append(name)
    return tools_called


def _extract_skill_names(messages: list) -> list[str]:
    skill_names = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name")
                    args = tc.get("args") or {}
                else:
                    name = tc.name
                    args = getattr(tc, "args", {}) or {}
                if name != "load_skill":
                    continue
                skill_name = args.get("skill_name")
                if skill_name:
                    skill_names.append(skill_name)
    return skill_names


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


def make_valid_graph_url_evaluator():
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        response = outputs.get("response", "")
        graph_markdown = outputs.get("graph_markdown", "")
        if "/graphs/graph.png" in response:
            return {
                "key": "valid_graph_url",
                "score": 0.0,
                "comment": "Final response contains placeholder /graphs/graph.png.",
            }
        if not graph_markdown:
            return {
                "key": "valid_graph_url",
                "score": 0.0,
                "comment": "No graph markdown URL found in tool output.",
            }
        return {"key": "valid_graph_url", "score": 1.0, "comment": "Valid graph URL found"}
    return evaluator


def make_skills_called_evaluator(skills_key: str = "required_skills"):
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        skills_called = outputs.get("skills_called", [])
        required = reference_outputs.get(skills_key, [])
        missing = [s for s in required if s not in skills_called]
        score = 1.0 if not missing else 0.0
        comment = "All required skills loaded" if not missing else f"Missing skills: {missing}"
        return {"key": "skills_called", "score": score, "comment": comment}
    return evaluator


def _run_graph(inputs: dict) -> dict:
    thread_id = str(uuid.uuid4())
    default_store.clear(thread_id)
    os.environ.setdefault("SKILL_PREFER_LOCAL", "true")
    agent = make_agent(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    invoke_verbose(agent, {"messages": [{"role": "user", "content": f"Charge ce fichier : {inputs['file_path']}"}]}, config)
    result = invoke_verbose(agent, {"messages": [{"role": "user", "content": inputs["question"]}]}, config)

    msgs = result.get("messages", [])
    tools_called = _extract_tools_called(msgs)
    skills_called = _extract_skill_names(msgs)
    image_b64 = _extract_graph_image(msgs)
    graph_markdown = _extract_graph_markdown(msgs)
    return {
        "response": msgs[-1].content if msgs else "",
        "tools_called": tools_called,
        "skills_called": skills_called,
        "image_b64": image_b64 or "",
        "graph_markdown": graph_markdown or "",
    }


def run_graphs_evals(experiment_prefix: str = "graphs") -> None:
    print(f"\n=== Graphs Evals ===")
    rows = run_eval_suite(
        cases=GRAPHS_CASES,
        run_fn=_run_graph,
        evaluators=[
            make_vision_judge_evaluator("criteria"),
            make_tools_called_evaluator("required_tools"),
            make_skills_called_evaluator("required_skills"),
            make_valid_graph_url_evaluator(),
        ],
        dataset_name=DATASET_NAME,
        experiment_prefix=experiment_prefix,
        metadata={"category": "graphs", "agent_version": "slice-5"},
    )
    print_scores(rows, score_keys=["vision_judge", "tools_called", "skills_called", "valid_graph_url"])


if __name__ == "__main__":
    run_graphs_evals()
