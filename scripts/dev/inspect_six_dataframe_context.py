#!/usr/bin/env python3
"""Print the exact model-bound context for a six-DataFrame IDEA session.

This is an offline integration harness: it runs the real context middlewares
with a local spy model and never sends a request to an external LLM.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence
from unittest.mock import patch

import pandas as pd
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import agent as agent_module
from agents.exploration_middleware import ExplorationStateMiddleware
from agents.exploration_state import IdeaAgentState
from agents.exploration_state import (
    ingest_tool_evidence,
    new_exploration_run,
    reconcile_data_dependencies,
    register_tool_steps,
)
from tools.dataset_registry import store_dataset
from tools.data_tools import make_tools
from tools.dataframe_cleanup import advance_dataframe_cleanup, hidden_dataframes
from tools.resource_inventory import build_resource_inventory
from tools.session_store import SessionStore
from tools.tool_catalog import build_tool_catalog


THREAD_ID = "six-dataframe-context-harness"
ACTIVE_VARIABLE = "df_uvp_net_candidates"
OLD_DERIVED_VARIABLE = "df_old_plot"
TRANSIENT_VARIABLES = (
    ACTIVE_VARIABLE,
    "df_station_summary",
    OLD_DERIVED_VARIABLE,
)
DATAFRAME_NAMES = (
    "df_neolabs_sample",
    "df_neolabs_abundance",
    "df_ecotaxa_cache_query",
    ACTIVE_VARIABLE,
    "df_station_summary",
    OLD_DERIVED_VARIABLE,
)

REMOVED_NET_UVP_TOOLS = frozenset({
    "prepare_net_uvp_audit_subsets",
    "find_uvp_matches_for_net_table",
    "join_net_uvp_enriched",
    "compare_local_net_uvp_profiles",
})
ROW_SENTINELS = (
    "ROW_VALUE_SAMPLE_SECRET",
    "ROW_VALUE_TAXON_SECRET",
    "ROW_VALUE_PROFILE_SECRET",
)
HYBRID_RESULT = "df_hybrid_metadata_result"
HYBRID_DESCRIPTION = (
    "Jointure des abondances NeoLabs avec les métadonnées de prélèvement; "
    "grain taxon, stade et analyse; identifiants, abondance et station."
)
HYBRID_GRAIN = "une ligne par taxon, stade et analyse"
MANY_DATAFRAME_COUNT = 26


@dataclass(frozen=True)
class ModelCapture:
    """Exact request facts observed at the model boundary."""

    system: str
    messages: tuple[BaseMessage, ...]
    tool_names: tuple[str, ...]
    tool_choice: object
    audit: dict[str, Any]
    state_messages: tuple[BaseMessage, ...]
    turn: int = 0
    tool_definitions: tuple[Any, ...] = ()

    @property
    def context_ledger(self) -> tuple[dict[str, Any], ...]:
        """Structured projection accounting emitted by the runtime seam."""

        return tuple(self.audit.get("context_projection_ledger") or ())

    @property
    def runtime_context(self) -> str:
        for message in reversed(self.messages):
            if message.type != "human":
                continue
            for block in message.content_blocks:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                text = str(block.get("text") or "")
                start = text.find("<application_turn_context>")
                end = text.find("</application_turn_context>")
                if start >= 0 and end > start:
                    return text[
                        start + len("<application_turn_context>"):end
                    ].strip()
        return ""

    @property
    def task_context(self) -> str:
        start = self.runtime_context.find("## CURRENT TASK")
        end = self.runtime_context.find("## AVAILABLE DATAFRAMES", start)
        if start < 0:
            return ""
        return self.runtime_context[start:] if end < 0 else self.runtime_context[start:end].rstrip()

    @property
    def dataset_context(self) -> str:
        start = self.runtime_context.find("## AVAILABLE DATAFRAMES")
        if start < 0:
            return ""
        endings = [
            position
            for position in (
                self.runtime_context.find("LAST GRAPH", start),
                self.runtime_context.find("## EXPLORATION FRONTIER", start),
            )
            if position >= 0
        ]
        end = min(endings, default=-1)
        return self.runtime_context[start:] if end < 0 else self.runtime_context[start:end].rstrip()

    @property
    def graph_facts_context(self) -> str:
        start = self.runtime_context.find("LAST GRAPH")
        if start < 0:
            return ""
        end = self.runtime_context.find("## EXPLORATION FRONTIER", start)
        return self.runtime_context[start:] if end < 0 else self.runtime_context[start:end].rstrip()

    @property
    def exploration_context(self) -> str:
        start = self.runtime_context.find("## EXPLORATION FRONTIER")
        return "" if start < 0 else self.runtime_context[start:].rstrip()

    @property
    def exact_user_request(self) -> str:
        for message in reversed(self.messages):
            if message.type != "human":
                continue
            text_blocks = [
                str(block.get("text") or "")
                for block in message.content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if text_blocks:
                return text_blocks[-1]
        return ""


@dataclass(frozen=True)
class ContractResult:
    name: str
    passed: bool
    detail: str


class _SpyChatModel(FakeMessagesListChatModel):
    """Local chat model that records exactly what LangChain gives the model."""

    capture: dict[str, Any] = Field(default_factory=dict, exclude=True)
    calls: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    current_turn: int = Field(default=0, exclude=True)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "_SpyChatModel":
        def provider_name(tool: Any) -> str:
            if isinstance(tool, dict):
                return str(tool.get("name") or tool.get("type") or "")
            return str(getattr(tool, "name", ""))

        self.capture["tool_names"] = tuple(
            provider_name(tool) for tool in tools
        )
        self.capture["tool_definitions"] = tuple(tools)
        self.capture["tool_choice"] = tool_choice
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any):
        self.capture["messages"] = tuple(messages)
        self.capture["system"] = "\n".join(
            str(message.content)
            for message in messages
            if message.type == "system"
        )
        self.calls.append({
            "turn": self.current_turn,
            "messages": tuple(messages),
            "system": self.capture["system"],
            "tool_names": tuple(self.capture.get("tool_names") or ()),
            "tool_definitions": tuple(
                self.capture.get("tool_definitions") or ()
            ),
            "tool_choice": self.capture.get("tool_choice"),
        })
        return super()._generate(messages, *args, **kwargs)


def seed_six_dataframes(store: SessionStore, thread_id: str) -> None:
    """Create six distinct resources with realistic schemas and metadata."""
    sample_columns: dict[str, Any] = {
            "SAMPLE_ID": ["ROW_VALUE_SAMPLE_SECRET", "NET-002"],
            "ANALYSIS_ID": [11, 12],
            "station": ["Hebron", "Sentinel"],
            **{
                f"auxiliary_note_{index:02d}": [f"note-{index}-a", f"note-{index}-b"]
                for index in range(70)
            },
            "DEPLOYMENT_DATE_START": ["2025-07-01", "2025-07-02"],
            "DEPLOYMENT_TIME_START": ["08:00:00", "09:30:00"],
            "latitude": [58.10, 58.30],
            "longitude": [-61.20, -61.50],
            "volume_m3": [4.2, 5.1],
    }
    sample = pd.DataFrame(sample_columns)
    abundance = pd.DataFrame(
        {
            "SAMPLE_ID": ["NET-001", "NET-002"],
            "ANALYSIS_ID": [11, 12],
            "taxon": ["ROW_VALUE_TAXON_SECRET", "Calanus finmarchicus"],
            "stage": ["C5", "adult"],
            "abundance_ind_m3": [12.5, 8.0],
        }
    )
    ecotaxa = pd.DataFrame(
        {
            "profile_id": ["ROW_VALUE_PROFILE_SECRET", "UVP-102"],
            "station": ["Hebron", "Sentinel"],
            "uvp_datetime": pd.to_datetime(["2025-07-01 12:00", "2025-07-02 16:00"]),
            "latitude": [58.11, 58.31],
            "longitude": [-61.19, -61.49],
            "instrument": ["UVP6", "UVP6"],
        }
    )
    candidates = pd.DataFrame(
        {
            "net_sample_id": ["NET-001", "NET-002"],
            "profile_id": ["UVP-101", "UVP-102"],
            "station": ["Hebron", "Sentinel"],
            "net_datetime": pd.to_datetime(["2025-07-01 08:00", "2025-07-02 09:30"]),
            "uvp_datetime": pd.to_datetime(["2025-07-01 12:00", "2025-07-02 16:00"]),
            "delta_h": [4.0, 6.5],
            "latitude": [58.11, 58.31],
            "longitude": [-61.19, -61.49],
        }
    )
    station_summary = pd.DataFrame(
        {
            "station": ["Hebron", "Sentinel"],
            "n_profiles": [1, 1],
            "delta_h_mean": [4.0, 6.5],
        }
    )
    old_plot = pd.DataFrame(
        {
            "station": ["Hebron", "Sentinel"],
            "latitude": [58.11, 58.31],
            "longitude": [-61.19, -61.49],
            "marker_size": [20.0, 20.0],
        }
    )

    store_dataset(
        store,
        thread_id,
        sample,
        variable_name="df_neolabs_sample",
        meta={
            "source": "file:/uploads/neolabs_sample.csv",
            "path": "/uploads/neolabs_sample.csv",
            "n_rows": 850,
            "n_cols": len(sample.columns),
            "grain": "un prélèvement ou déploiement horodaté",
            "description": (
                "Fichier NeoLabs sample; grain prélèvement/déploiement; "
                "dates, heures, stations, positions et volume filtré."
            ),
        },
        is_loaded_file=True,
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        abundance,
        variable_name="df_neolabs_abundance",
        meta={
            "source": "file:/uploads/neolabs_abundance.csv",
            "path": "/uploads/neolabs_abundance.csv",
            "n_rows": 12_400,
            "n_cols": len(abundance.columns),
            "grain": "une ligne par taxon, stade et analyse",
            "description": (
                "Fichier NeoLabs abundance; grain taxon/stade/analyse; "
                "identifiants et abondances biologiques."
            ),
        },
        is_loaded_file=True,
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        ecotaxa,
        variable_name="df_ecotaxa_cache_query",
        meta={
            "source": "ecotaxa_cache_query",
            "n_rows": 2_130,
            "n_cols": len(ecotaxa.columns),
            "grain": "un profil UVP",
            "description": (
                "Résultat du cache EcoTaxa; grain profil UVP; station, date/heure, "
                "position et instrument."
            ),
        },
        latest_alias="ecotaxa_cache_query",
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        station_summary,
        variable_name="df_station_summary",
        meta={
            "source": "analysis:derived",
            "n_rows": 48,
            "n_cols": len(station_summary.columns),
            "grain": "une ligne agrégée par station",
            "parent_variable": "df_uvp_net_candidates",
            "description": (
                "Agrégation des candidats Filet–UVP; grain station; nombre de "
                "profils et delta temporel moyen."
            ),
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        old_plot,
        variable_name=OLD_DERIVED_VARIABLE,
        meta={
            "source": "analysis:graph-plot",
            "n_rows": 48,
            "n_cols": len(old_plot.columns),
            "grain": "une ligne graphique par station",
            "parent_variable": "df_station_summary",
            "description": (
                "Ancienne préparation graphique dérivée; grain station; "
                "positions et tailles de marqueur."
            ),
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        candidates,
        variable_name=ACTIVE_VARIABLE,
        meta={
            "source": "analysis:join",
            "n_rows": 320,
            "n_cols": len(candidates.columns),
            "grain": "une paire candidate prélèvement Filet et profil UVP",
            "parent_variables": ["df_neolabs_sample", "df_ecotaxa_cache_query"],
            "filters": {"same_station": True, "delta_h_max": 10},
            "description": (
                "Jointure Filet–UVP; grain paire prélèvement/profil; même station "
                "et delta temporel maximal de 10 heures."
            ),
        },
    )


def seed_many_dataframes(store: SessionStore, thread_id: str) -> tuple[str, ...]:
    """Persist more resources than the former twenty-table display ceiling."""
    names = tuple(
        f"df_resource_{index:02d}" for index in range(MANY_DATAFRAME_COUNT)
    )
    for index, name in enumerate(names):
        frame = pd.DataFrame({"sample_id": [index], "value": [float(index)]})
        store_dataset(
            store,
            thread_id,
            frame,
            variable_name=name,
            meta={
                "source": f"file:/uploads/resource_{index:02d}.csv",
                "description": f"Ressource tabulaire numéro {index:02d}.",
                "grain": "une ligne par sample",
                "primary_key": "sample_id",
            },
            set_active=index == 0,
        )
    return names


def capture_model_request(
    store: SessionStore,
    thread_id: str,
    question: str,
    message_id: str,
    *,
    exploration: dict[str, Any] | None = None,
    input_messages: Sequence[BaseMessage] | None = None,
) -> ModelCapture:
    """Run the production middlewares and capture their final model request."""
    spy = _SpyChatModel(responses=[AIMessage(content="capture terminée")])
    with patch("tools.session_store.default_store", store):
        catalog = build_tool_catalog(thread_id)
        graph = create_agent(
            spy,
            list(catalog.tools),
            system_prompt=agent_module._SYSTEM_PROMPT,
            middleware=[
                ModelCallLimitMiddleware(
                    run_limit=agent_module._MAX_MODEL_CALLS_PER_TURN,
                    exit_behavior="end",
                ),
                ExplorationStateMiddleware(thread_id=thread_id),
                agent_module._ContextMiddleware(
                    user_id="context-harness",
                    thread_id=thread_id,
                    catalog_names=catalog.names,
                ),
            ],
            state_schema=IdeaAgentState,
            store=InMemoryStore(),
        )
        graph_input: dict[str, Any] = {
            "messages": list(input_messages)
            if input_messages is not None
            else [HumanMessage(content=question, id=message_id)]
        }
        if exploration is not None:
            graph_input["exploration"] = exploration
        result = graph.invoke(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
        )
    return ModelCapture(
        system=str(spy.capture.get("system") or ""),
        messages=tuple(spy.capture.get("messages") or ()),
        tool_names=tuple(spy.capture.get("tool_names") or ()),
        tool_choice=spy.capture.get("tool_choice"),
        audit=agent_module.get_context_audit(thread_id),
        state_messages=tuple(result.get("messages") or ()),
        tool_definitions=tuple(spy.capture.get("tool_definitions") or ()),
    )


def persist_hybrid_metadata_result(
    store: SessionStore,
    thread_id: str,
) -> str | None:
    """Create one real run_pandas result for the metadata contract."""
    run_pandas = next(
        tool
        for tool in make_tools(thread_id, store=store)
        if tool.name == "run_pandas"
    )
    try:
        run_pandas.invoke({
            "code": (
                "left = df_neolabs_abundance.dropna(subset=['SAMPLE_ID'])\n"
                "right = df_neolabs_sample[[\n"
                "    'SAMPLE_ID', 'ANALYSIS_ID', 'station'\n"
                "]]\n"
                "result = left.merge(\n"
                "    right, on=['SAMPLE_ID', 'ANALYSIS_ID'], how='inner'\n"
                ")"
            ),
            "persist_as": HYBRID_RESULT,
            "description": HYBRID_DESCRIPTION,
            "grain": HYBRID_GRAIN,
            "filters": {"sample_id_not_null": True},
        })
    except Exception as exc:  # Expected during the RED harness run.
        return f"{type(exc).__name__}: {exc}"
    return None


def _check(name: str, passed: bool, detail: str) -> ContractResult:
    return ContractResult(name=name, passed=bool(passed), detail=detail)


def validate_live_capture(capture: ModelCapture) -> list[ContractResult]:
    """Validate how six simultaneously live DataFrames are presented."""
    dataset = capture.dataset_context
    full_model_context = capture.system + capture.runtime_context
    missing = [name for name in DATAFRAME_NAMES if name not in dataset]
    entry_markers = {name: f"- {name}\n" for name in DATAFRAME_NAMES}
    descriptions_complete = all(
        f"- {name}\n" in dataset
        and "description=" in dataset.split(f"- {name}\n", 1)[1].split("\n- ", 1)[0]
        for name in DATAFRAME_NAMES
    )
    schema_complete = all(
        f"- {name}\n" in dataset
        and "schema_by_role=" in dataset.split(f"- {name}\n", 1)[1].split("\n- ", 1)[0]
        for name in DATAFRAME_NAMES
    )
    checkpoint_text = "\n".join(str(message.content) for message in capture.state_messages)
    probe_messages = [
        HumanMessage(content="requête originale", id="probe-human"),
        AIMessage(
            content="",
            id="probe-ai",
            tool_calls=[
                {"name": "run_pandas", "args": {"code": "result = df"}, "id": "probe-call"}
            ],
        ),
        ToolMessage(content="résultat", tool_call_id="probe-call", id="probe-tool"),
    ]
    contextualized_probe, probe_injected = (
        agent_module._inject_turn_context_into_current_user(
            probe_messages,
            "## CURRENT TASK\nObjective: test",
        )
    )
    probe_human_blocks = contextualized_probe[0].content_blocks
    results = [
        _check(
            "six DataFrames visible",
            not missing,
            "tous présents" if not missing else "absents: " + ", ".join(missing),
        ),
        _check(
            "une entrée uniforme par DataFrame",
            all(dataset.count(marker) == 1 for marker in entry_markers.values()),
            "chaque nom apparaît une seule fois comme entrée de catalogue",
        ),
        _check(
            "catalogue non hiérarchisé par DataFrame actif",
            dataset.find("* df_ecotaxa_cache_query\n")
            < dataset.find(f"* {ACTIVE_VARIABLE}\n")
            and f"- {ACTIVE_VARIABLE}\n  status=active" in dataset,
            "index alphabétique; le statut actif reste un simple attribut",
        ),
        _check(
            "description pour chaque DataFrame",
            descriptions_complete,
            "chaque ressource expose une description distincte",
        ),
        _check(
            "schéma typé pour chaque DataFrame",
            schema_complete,
            "chaque ressource expose ses colonnes classées par rôle et dtype",
        ),
        _check(
            "date et heure du fichier sample classées comme temps",
            "time=[DEPLOYMENT_DATE_START:object,DEPLOYMENT_TIME_START:object]" in dataset,
            "les deux colonnes de déploiement doivent être dans time",
        ),
        _check(
            "colonnes utiles conservées dans un DataFrame large",
            "space=[latitude:float64,longitude:float64]" in dataset
            and "measures=[volume_m3:float64]" in dataset
            and "schema_visibility=" in dataset
            and " partial; keys=" in dataset,
            "temps, position et mesure restent visibles parmi plus de 70 colonnes",
        ),
        _check(
            "grain, clés, portée et lignée affichés",
            all(field in dataset for field in ("  grain=", "  keys=", "  scope=", "  lineage=")),
            "les critères de capacité et d’appropriation sont visibles",
        ),
        _check(
            "groupes de colonnes affichés",
            "schema_by_role=" in dataset
            and "keys=[" in dataset
            and "space=[" in dataset
            and "measures=[" in dataset,
            "clés, position et mesures visibles",
        ),
        _check(
            "colonnes datetime classées comme temps",
            "time=[net_datetime:datetime64[ns],uvp_datetime:datetime64[ns]]" in dataset
            or "time=[uvp_datetime:datetime64[ns],net_datetime:datetime64[ns]]" in dataset,
            (
                "net_datetime et uvp_datetime sont dans time"
                if "time=[" in dataset
                else "aucun groupe time pour net_datetime et uvp_datetime"
            ),
        ),
        _check(
            "portée et lignée du résultat de jointure",
            '"filter.same_station":true' in dataset
            and '"filter.delta_h_max":10' in dataset
            and "parent_variables:df_neolabs_sample" in dataset
            and "parent_variables:df_ecotaxa_cache_query" in dataset,
            "filtres et deux parents explicites pour la jointure Filet–UVP",
        ),
        _check(
            "aucune valeur de ligne injectée",
            not any(value in full_model_context for value in ROW_SENTINELS),
            "aucun sentinel trouvé dans le contexte",
        ),
        _check(
            "ordre objectif puis données puis progression",
            0 <= capture.runtime_context.find("## CURRENT TASK")
            < capture.runtime_context.find("## AVAILABLE DATAFRAMES")
            < capture.runtime_context.find("## EXPLORATION FRONTIER"),
            "le besoin précède le choix des ressources",
        ),
        _check(
            "choix du DataFrame confié au planner",
            "## PLANNER DATASET CHOICE" in capture.task_context
            and "The application has not selected a DataFrame" in capture.task_context
            and "The first plan item must name the candidate DataFrame" in capture.task_context
            and "call run_pandas only" in capture.task_context
            and "wait for its result" in capture.task_context,
            "le plan qualifie un candidat avec run_pandas avant de choisir le départ",
        ),
        _check(
            "qualification séquentielle avant calcul ou graphe",
            "DataFrame qualification is a real ReAct gate" in capture.system
            and "do not batch the calculation or `run_graph` beside it" in capture.system,
            "run_pandas doit répondre avant la suite du plan",
        ),
        _check(
            "route de source visible mais non bloquante",
            "Preferred source route: file; primary=file" in capture.task_context
            and "never a DataFrame or tool restriction" in capture.task_context,
            "la préférence oriente le départ sans filtrer les ressources",
        ),
        _check(
            "contexte dynamique absent du system prompt",
            "<application_turn_context>" not in capture.system
            and "## AVAILABLE DATAFRAMES (current session" not in capture.system
            and capture.audit.get("dynamic_context_in_system") is False,
            "le kernel système reste permanent",
        ),
        _check(
            "contexte placé devant la demande exacte",
            capture.exact_user_request
            == "Fais une carte des profils UVP associés aux prélèvements avec un delta maximal de 10 heures."
            and capture.audit.get("runtime_context_position") == "current_user_prefix",
            "la demande originale est le dernier bloc du message humain courant",
        ),
        _check(
            "contexte transitoire non checkpointé",
            "<application_turn_context>" not in checkpoint_text,
            "aucun message artificiel n’est conservé dans l’état LangGraph",
        ),
        _check(
            "chronologie ReAct préservée après un tool",
            probe_injected
            and probe_human_blocks[-1].get("text") == "requête originale"
            and contextualized_probe[1].id == "probe-ai"
            and contextualized_probe[2].id == "probe-tool",
            "le contexte préfixe le tour sans déplacer l’appel ni son résultat",
        ),
        _check(
            "aucune ancienne capsule de skill",
            "ACTIVE SKILL RULES" not in full_model_context,
            "aucune ancienne capsule de skill injectée",
        ),
        _check(
            "requête capturée au niveau modèle",
            bool(capture.messages) and bool(capture.tool_names),
            f"{len(capture.messages)} messages; {len(capture.tool_names)} tools exposés",
        ),
        _check(
            "ressources non tabulaires séparées",
            "OTHER AVAILABLE RESOURCES:" in dataset
            and "Base de connaissances copépodes" in dataset,
            "le RAG est visible comme ressource, pas comme DataFrame",
        ),
        _check(
            "aucun workflow Filet–UVP injecté implicitement",
            "Comparaison filet–UVP" not in capture.runtime_context,
            "un fichier chargé ne déclenche aucun workflow métier spécialisé",
        ),
        _check(
            "aucun tool Filet–UVP exposé au modèle",
            not REMOVED_NET_UVP_TOOLS.intersection(capture.tool_names),
            "les fonctions internes restent disponibles dans le code, hors catalogue agent",
        ),
    ]
    return results


def validate_explicit_reference_capture(capture: ModelCapture) -> list[ContractResult]:
    """An exact user reference is promoted softly and never hides alternatives."""
    table_entries = [
        line[2:]
        for line in capture.dataset_context.splitlines()
        if line.startswith("- df_")
    ]
    anchor_names = {
        "df_ecotaxa_cache_query",
        "df_neolabs_abundance",
        "df_neolabs_sample",
    }
    intermediate_entries = [
        name for name in table_entries if name not in anchor_names
    ]
    return [
        _check(
            "référence DataFrame explicite en tête des intermédiaires",
            bool(intermediate_entries)
            and intermediate_entries[0] == "df_station_summary",
            "premier intermédiaire="
            f"{intermediate_entries[0] if intermediate_entries else 'aucun'}",
        ),
        _check(
            "promotion souple sans filtrage des alternatives",
            all(name in capture.dataset_context for name in DATAFRAME_NAMES),
            "les six DataFrames restent visibles",
        ),
    ]


def validate_aged_capture(capture: ModelCapture) -> list[ContractResult]:
    """Validate that only stale automatic derivatives leave model context."""
    dataset = capture.dataset_context
    still_visible = [name for name in TRANSIENT_VARIABLES if name in dataset]
    return [
        _check(
            "dérivés automatiques masqués après six tours inutilisés",
            not still_visible,
            (
                "tous les dérivés transitoires sont absents"
                if not still_visible
                else "encore exposés: " + ", ".join(still_visible)
            ),
        ),
        _check(
            "fichiers sources conservés après vieillissement",
            "df_neolabs_sample" in dataset and "df_neolabs_abundance" in dataset,
            "les deux fichiers NeoLabs restent visibles",
        ),
        _check(
            "ancrage actif revenu sur une ressource non transitoire",
            capture.audit.get("turn_active_variable") not in TRANSIENT_VARIABLES,
            f"actif={capture.audit.get('turn_active_variable')}",
        ),
    ]


def validate_hybrid_metadata_capture(
    capture: ModelCapture,
    execution_error: str | None,
) -> list[ContractResult]:
    """Validate metadata persisted by a real run_pandas call."""
    dataset = capture.dataset_context
    entry = (
        dataset.split(f"- {HYBRID_RESULT}\n", 1)[1].split("\n- ", 1)[0]
        if f"- {HYBRID_RESULT}\n" in dataset
        else ""
    )
    return [
        _check(
            "run_pandas accepte les métadonnées hybrides",
            execution_error is None,
            execution_error or "appel exécuté sans erreur",
        ),
        _check(
            "description LLM persistée",
            f"description={HYBRID_DESCRIPTION}" in entry,
            "la description spécifique est visible dans le catalogue",
        ),
        _check(
            "grain LLM persisté",
            f"grain={HYBRID_GRAIN}" in entry,
            "le grain déclaré est visible dans le catalogue",
        ),
        _check(
            "filtres LLM persistés comme portée",
            'scope={"filter.sample_id_not_null":true}' in entry,
            "la portée structurée reflète le filtre réellement appliqué",
        ),
        _check(
            "parents run_pandas détectés automatiquement",
            "parent_variables:df_neolabs_abundance" in entry
            and "parent_variables:df_neolabs_sample" in entry,
            "les deux DataFrames effectivement lus apparaissent dans la lignée",
        ),
    ]


def validate_many_dataframe_capture(
    capture: ModelCapture,
    names: tuple[str, ...],
) -> list[ContractResult]:
    """Validate that canonical file anchors all survive a large catalog."""
    dataset = capture.dataset_context
    missing = [name for name in names if name not in dataset]
    detailed = [name for name in names if f"- {name}\n" in dataset]
    return [
        _check(
            "index visible au-delà de vingt DataFrames",
            not missing,
            "tous les noms sont visibles" if not missing else "absents: " + ", ".join(missing),
        ),
        _check(
            "ressource explicitement demandée détaillée",
            f"- {names[-1]}\n" in dataset,
            f"cible={names[-1]}",
        ),
        _check(
            "toutes les sources fichier restent détaillées",
            len(detailed) == len(names),
            f"{len(detailed)} fiches détaillées pour {len(names)} ressources",
        ),
        _check(
            "catalogue DataFrame sous le budget",
            len(dataset) <= 12_000,
            f"{len(dataset)} caractères",
        ),
    ]


def validate_lineage_aware_cleanup(store: SessionStore) -> list[ContractResult]:
    """A visible descendant keeps its automatic parent alive."""
    thread_id = f"{THREAD_ID}-lineage-cleanup"
    parent = "df_join_parent"
    child = "df_persisted_child"
    unrelated = "df_unrelated_transient"
    frame = pd.DataFrame({"sample_id": [1], "value": [2.0]})
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name=parent,
        meta={"source": "analysis:join", "description": "Parent automatique."},
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        frame.copy(),
        variable_name=child,
        meta={
            "source": "analysis:explicit-derived",
            "description": "Résultat persistant dépendant du parent.",
            "parent_variables": [parent],
        },
    )
    store_dataset(
        store,
        thread_id,
        frame.copy(),
        variable_name=unrelated,
        meta={"source": "analysis:derived", "description": "Dérivé sans descendant."},
        set_active=False,
    )
    for turn in range(1, 22):
        advance_dataframe_cleanup(
            store,
            thread_id,
            marker=f"cleanup-turn-{turn}",
        )
    hidden = hidden_dataframes(store, thread_id)
    return [
        _check(
            "parent d’un résultat visible conservé",
            parent not in hidden
            and store.get(f"{thread_id}:dataset:{parent}") is not None,
            "le parent reste visible et persistant",
        ),
        _check(
            "dérivé transitoire sans dépendance supprimé",
            store.get(f"{thread_id}:dataset:{unrelated}") is None,
            "le nettoyage continue pour les tables réellement orphelines",
        ),
    ]


def validate_last_graph_facts_capture(
    capture: ModelCapture,
    *,
    facts: str,
    code_sentinel: str,
) -> list[ContractResult]:
    """Validate the transient, bounded last-graph facts layer."""
    checkpoint_text = "\n".join(
        str(message.content) for message in capture.state_messages
    )
    return [
        _check(
            "faits du dernier graphique injectés",
            facts in capture.graph_facts_context,
            "les faits vérifiés sont visibles au modèle",
        ),
        _check(
            "faits graphiques placés avant la frontière",
            capture.runtime_context.find("## AVAILABLE DATAFRAMES")
            < capture.runtime_context.find("LAST GRAPH")
            < capture.runtime_context.find("## EXPLORATION FRONTIER"),
            "ordre données puis faits graphiques puis progression",
        ),
        _check(
            "faits graphiques transitoires",
            facts not in capture.system and facts not in checkpoint_text,
            "ni le system prompt ni le checkpoint ne sont modifiés",
        ),
        _check(
            "script du dernier graphique non injecté",
            code_sentinel not in capture.runtime_context,
            "seuls les faits vérifiés sont projetés",
        ),
    ]


def build_frontier_payload(
    store: SessionStore,
    thread_id: str,
    objective: str,
) -> tuple[dict[str, Any], list[BaseMessage]]:
    """Build a real pending data dependency through exploration reducers."""
    human = HumanMessage(content=objective, id="frontier-human")
    payload = new_exploration_run(
        objective,
        build_resource_inventory(store, thread_id),
    )
    plan = AIMessage(
        content=(
            "### Plan\n"
            "- Inspecter les colonnes de df_ecotaxa_cache_query.\n"
            "- Calculer le nombre d’objets par profil."
        ),
        id="frontier-plan",
    )
    call = AIMessage(
        content="",
        id="frontier-call-message",
        tool_calls=[{
            "name": "run_pandas",
            "args": {"code": "result = df_ecotaxa_cache_query['object_count'].sum()"},
            "id": "frontier-call-1",
            "type": "tool_call",
        }],
    )
    payload = register_tool_steps(payload, [human, call]) or payload
    blocked_result = ToolMessage(
        content="La colonne object_count manque.",
        name="run_pandas",
        tool_call_id="frontier-call-1",
        id="frontier-tool-1",
        artifact={
            "status": "error",
            "summary": "Colonne object_count absente de la table active.",
            "metrics": {
                "dependency_recovery": True,
                "dependency_requirement": {
                    "kind": "column",
                    "name": "object_count",
                    "canonical_name": "object_count",
                    "source_hint": "ecotaxa",
                    "description": "Récupérer object_count avant de reprendre le calcul.",
                },
            },
        },
    )
    messages: list[BaseMessage] = [human, plan, call, blocked_result]
    payload = ingest_tool_evidence(payload, messages) or payload
    payload = reconcile_data_dependencies(payload) or payload
    return payload, messages


def resolve_frontier_payload(
    payload: dict[str, Any],
    messages: list[BaseMessage],
) -> dict[str, Any]:
    """Retry the failed analytical step successfully."""
    retry = AIMessage(
        content="",
        id="frontier-retry-message",
        tool_calls=[{
            "name": "run_pandas",
            "args": {"code": "result = df_ecotaxa_cache_query['object_count'].sum()"},
            "id": "frontier-call-2",
            "type": "tool_call",
        }],
    )
    payload = register_tool_steps(payload, [*messages, retry]) or payload
    success_result = ToolMessage(
        content="Calcul terminé.",
        name="run_pandas",
        tool_call_id="frontier-call-2",
        id="frontier-tool-2",
        artifact={
            "status": "success",
            "summary": "Nombre d’objets calculé par profil.",
            "data_ref": "df_object_count_by_profile",
            "persisted": True,
        },
    )
    payload = ingest_tool_evidence(
        payload,
        [*messages, retry, success_result],
    ) or payload
    return reconcile_data_dependencies(payload) or payload


def validate_frontier_capture(
    pending: ModelCapture,
    resolved: ModelCapture,
) -> list[ContractResult]:
    """Validate frontier population and dependency resolution."""
    pending_text = pending.exploration_context
    resolved_text = resolved.exploration_context
    return [
        _check(
            "plan visible non interprété par le harness",
            "Actual tool calls:" in pending_text
            and "Inspecter les colonnes" not in pending_text
            and "Calculer le nombre" not in pending_text,
            "le plan reste dans les messages du modèle sans classification lexicale",
        ),
        _check(
            "frontière avec preuve d’échec",
            "frontier-call-1" in pending_text
            and "Colonne object_count absente" in pending_text,
            "la preuve produite par le tool est conservée",
        ),
        _check(
            "frontière avec dépendance active",
            '"name":"object_count"' in pending_text
            and '"source":"ecotaxa"' in pending_text
            and "Resolve every pending data dependency" in pending_text,
            "la donnée manquante et la reprise sont explicites",
        ),
        _check(
            "directive checkpointée détaillée et en anglais",
            "DATA DEPENDENCY RECOVERY — CHECKPOINT CONTINUATION" in pending.runtime_context
            and "Recovery protocol:" in pending.runtime_context
            and "Completion condition:" in pending.runtime_context,
            "la reprise inter-tour explicite les actions et la condition de sortie",
        ),
        _check(
            "frontière évoluée après reprise",
            "frontier-call-2" in resolved_text
            and "Nombre d’objets calculé par profil" in resolved_text,
            "la réussite du second appel remplace l’état bloqué",
        ),
        _check(
            "dépendance résolue retirée de la frontière active",
            '"name":"object_count"' not in resolved_text
            and "Resolve every pending data dependency" not in resolved_text,
            "la dépendance reste dans l’historique de preuve, pas dans le travail restant",
        ),
    ]


def validate_code_retry_capture(capture: ModelCapture) -> list[ContractResult]:
    """Validate the one-shot local-code repair directive."""
    context = capture.runtime_context
    return [
        _check(
            "correction de code détaillée et en anglais",
            "DETERMINISTIC CODE RETRY — ONE ATTEMPT ONLY" in context
            and "Failure class: retryable local code execution" in context
            and "Failed tool: `run_pandas`" in context
            and "Retry protocol:" in context
            and "Completion condition:" in context,
            "le modèle reçoit le diagnostic, le protocole et la limite de reprise",
        ),
        _check(
            "aucun ancien titre français de récupération",
            "DÉTERMINISTIC" not in context
            and "DERNIER GRAPHIQUE" not in context,
            "les instructions internes contrôlées par le harness sont en anglais",
        ),
        _check(
            "run_pandas imposé pour l’unique correction",
            bool(capture.tool_choice),
            f"tool_choice={capture.tool_choice!r}",
        ),
    ]


def _capture_from_model_call(call: dict[str, Any]) -> ModelCapture:
    return ModelCapture(
        system=str(call.get("system") or ""),
        messages=tuple(call.get("messages") or ()),
        tool_names=tuple(call.get("tool_names") or ()),
        tool_choice=call.get("tool_choice"),
        audit={},
        state_messages=(),
        turn=int(call.get("turn") or 0),
        tool_definitions=tuple(call.get("tool_definitions") or ()),
    )


def run_checkpointed_multiturn_harness(
    store: SessionStore,
    thread_id: str,
    graph_dir: Path,
) -> tuple[list[ModelCapture], tuple[Any, ...]]:
    """Run three real LangGraph turns with a local scripted model."""
    object_counts = pd.DataFrame({
        "profile_id": ["ROW_VALUE_PROFILE_SECRET", "UVP-102"],
        "object_count": [12, 8],
    })
    store_dataset(
        store,
        thread_id,
        object_counts,
        variable_name="df_object_counts_source",
        meta={
            "source": "ecotaxa_cache_query",
            "description": "Comptages EcoTaxa persistés au grain profil.",
            "grain": "un profil UVP",
            "primary_key": "profile_id",
        },
        set_active=False,
    )
    responses = [
        AIMessage(
            content=(
                "### Plan\n"
                "- Vérifier la disponibilité de object_count.\n"
                "- Calculer le nombre total d’objets par profil."
            ),
            tool_calls=[{
                "name": "run_pandas",
                "args": {
                    "code": "result = df_ecotaxa_cache_query['object_count'].sum()"
                },
                "id": "multi-call-missing",
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "run_pandas",
                "args": {
                    "code": (
                        "result = df_ecotaxa_cache_query.merge(\n"
                        "    df_object_counts_source, on='profile_id', how='left'\n"
                        ")"
                    ),
                    "persist_as": "df_profiles_with_object_count",
                    "description": (
                        "Profils EcoTaxa enrichis par les comptages d’objets; "
                        "identifiants de profil et object_count."
                    ),
                    "grain": "un profil UVP",
                    "filters": {},
                },
                "id": "multi-call-recover",
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "run_pandas",
                "args": {
                    "code": (
                        "result = df_profiles_with_object_count[[\n"
                        "    'profile_id', 'object_count'\n"
                        "].copy()"
                    ),
                    "persist_as": "df_object_count_by_profile",
                    "description": (
                        "Nombre d’objets EcoTaxa par profil; identifiant de profil "
                        "et mesure object_count."
                    ),
                    "grain": "un profil UVP",
                    "filters": {},
                },
                "id": "multi-call-calculate",
                "type": "tool_call",
            }],
        ),
        AIMessage(content="Le tableau par profil est prêt."),
        AIMessage(
            content="### Plan\n- Tracer le nombre d’objets par profil.",
            tool_calls=[{
                "name": "run_graph",
                "args": {
                    "code": (
                        "plot_df = df_profiles_with_object_count[[\n"
                        "    'profile_id', 'object_count'\n"
                        "]].copy()\n"
                        "fig, ax = plt.subplots(figsize=(7, 4))\n"
                        "ax.bar(plot_df['profile_id'].astype(str), "
                        "plot_df['object_count'])\n"
                        "ax.set_xlabel('Profil')\n"
                        "ax.set_ylabel('Nombre d’objets')\n"
                        "ax.set_title('Objets par profil')\n"
                        "fig.tight_layout()"
                    )
                },
                "id": "multi-call-graph",
                "type": "tool_call",
            }],
        ),
        AIMessage(content="Le graphique est prêt."),
        AIMessage(content="Le graphique présente le nombre d’objets pour chaque profil."),
    ]
    spy = _SpyChatModel(responses=responses)
    with (
        patch("tools.session_store.default_store", store),
        patch("tools.data_tools.default_store", store),
        patch("tools.data_tools._GRAPHS_DIR", graph_dir),
    ):
        catalog = build_tool_catalog(thread_id)
        graph = create_agent(
            spy,
            list(catalog.tools),
            system_prompt=agent_module._SYSTEM_PROMPT,
            middleware=[
                ModelCallLimitMiddleware(
                    run_limit=agent_module._MAX_MODEL_CALLS_PER_TURN,
                    exit_behavior="end",
                ),
                ExplorationStateMiddleware(thread_id=thread_id),
                agent_module._ContextMiddleware(
                    user_id="multiturn-harness",
                    thread_id=thread_id,
                    catalog_names=catalog.names,
                ),
            ],
            state_schema=IdeaAgentState,
            checkpointer=MemorySaver(),
            store=InMemoryStore(),
        )
        config = {"configurable": {"thread_id": thread_id}}
        turn_results: list[Any] = []
        for turn, question in enumerate((
            "Calcule le nombre d’objets par profil EcoTaxa.",
            "Fais un graphique du nombre d’objets par profil.",
            "Résume le dernier graphique.",
        ), start=1):
            spy.current_turn = turn
            turn_results.append(
                graph.invoke(
                    {"messages": [HumanMessage(content=question, id=f"multi-turn-{turn}")]},
                    config=config,
                )
            )
    return [_capture_from_model_call(call) for call in spy.calls], tuple(turn_results)


def validate_checkpointed_multiturn(
    calls: list[ModelCapture],
    turn_results: tuple[Any, ...],
) -> list[ContractResult]:
    """Validate context evolution across one checkpointed conversation."""
    turn_1 = [capture for capture in calls if capture.turn == 1]
    turn_2 = [capture for capture in calls if capture.turn == 2]
    turn_3 = [capture for capture in calls if capture.turn == 3]
    graph_tool_result = next(
        (
            str(message.content)
            for capture in turn_2
            for message in reversed(capture.messages)
            if isinstance(message, ToolMessage) and message.name == "run_graph"
        ),
        "aucun résultat run_graph capturé",
    )
    turn_3_humans = (
        [message for message in turn_3[0].messages if message.type == "human"]
        if turn_3
        else []
    )
    return [
        _check(
            "conversation checkpointée sur trois tours",
            len(turn_results) == 3
            and [len(turn_1), len(turn_2), len(turn_3)] == [4, 2, 1],
            f"{len(turn_results)} tours; appels par tour="
            f"{[len(turn_1), len(turn_2), len(turn_3)]}",
        ),
        _check(
            "CURRENT TASK stable pendant le premier ReAct",
            len(turn_1) == 4
            and all(
                "Objective: Calcule le nombre d’objets par profil EcoTaxa."
                in capture.task_context
                for capture in turn_1
            ),
            "les appels internes conservent l’objectif du tour",
        ),
        _check(
            "frontière évolue après erreur puis récupération",
            "object_count" in turn_1[1].exploration_context
            and "Resolve every pending data dependency" in turn_1[1].exploration_context
            and "Resolve every pending data dependency" not in turn_1[2].exploration_context
            and "df_profiles_with_object_count" in turn_1[2].exploration_context,
            "la dépendance apparaît puis disparaît après la reprise",
        ),
        _check(
            "CURRENT TASK remplacé au deuxième tour",
            len(turn_2) == 2
            and all(
                "Objective: Fais un graphique du nombre d’objets par profil."
                in capture.task_context
                for capture in turn_2
            ),
            "le nouvel objectif remplace celui du calcul",
        ),
        _check(
            "faits graphiques disponibles après le rendu",
            not turn_2[0].graph_facts_context
            and "lignes tracées=" in turn_2[1].graph_facts_context,
            "les faits apparaissent au prochain appel modèle du même tour; "
            f"run_graph={graph_tool_result[:900]}",
        ),
        _check(
            "faits graphiques persistants au troisième tour",
            len(turn_3) == 1
            and "Objective: Résume le dernier graphique." in turn_3[0].task_context
            and "lignes tracées=" in turn_3[0].graph_facts_context,
            "le tour suivant reçoit les faits vérifiés du graphique",
        ),
        _check(
            "historique LangGraph conservé",
            len(turn_3) == 1
            and len(turn_3_humans) >= 3,
            "les trois demandes utilisateur sont présentes dans l’historique utile; "
            f"messages humains={len(turn_3_humans)}",
        ),
    ]


def _print_capture(capture: ModelCapture, *, view: str, title: str) -> None:
    print(f"\n{'=' * 24} {title} {'=' * 24}")
    if view == "full":
        print("\n--- SYSTEM MESSAGE EXACT ---\n")
        print(capture.system)
        print("\n--- MESSAGES EXACTS ---")
        for index, message in enumerate(capture.messages, start=1):
            print(f"[{index}] type={message.type} name={getattr(message, 'name', None)}")
            print(message.content)
        print("\n--- TOOLS EXPOSÉS AU MODÈLE ---")
        print(", ".join(capture.tool_names) or "aucun")
        print(f"tool_choice={capture.tool_choice!r}")
        print("\n--- AUDIT CONTEXTE ---")
        for key, value in sorted(capture.audit.items()):
            print(f"{key}={value}")
        return

    print("\n--- CURRENT TASK EXACT ---\n")
    print(capture.task_context or "[section absente]")
    print("\n--- AVAILABLE DATAFRAMES EXACT ---\n")
    print(capture.dataset_context or "[section absente]")
    print("\n--- EXPLORATION FRONTIER EXACT ---\n")
    print(capture.exploration_context or "[section absente]")
    print("\n--- RÉSUMÉ DE LA REQUÊTE MODÈLE ---")
    print(f"messages={len(capture.messages)}")
    print(f"tools_exposes={len(capture.tool_names)}")
    print(f"system_chars={len(capture.system)}")
    print(f"runtime_context_chars={len(capture.runtime_context)}")
    print(f"dataframe_context_chars={capture.audit.get('dataframe_context_chars')}")
    print(f"exploration_state_chars={capture.audit.get('exploration_state_chars')}")


def _print_results(results: Sequence[ContractResult]) -> int:
    print("\n--- VALIDATIONS ---")
    failures = 0
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")
        failures += int(not result.passed)
    if failures:
        print(f"\n{failures} CHECK(S) FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspecte le contexte exact vu par l'agent avec six DataFrames."
    )
    parser.add_argument(
        "--view",
        choices=("dataframes", "full"),
        default="dataframes",
        help="Affiche les sections DataFrame ou toute la requête modèle.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with TemporaryDirectory(prefix="idea-six-dataframe-context-") as directory:
        store = SessionStore(directory)
        seed_six_dataframes(store, THREAD_ID)
        live = capture_model_request(
            store,
            THREAD_ID,
            "Fais une carte des profils UVP associés aux prélèvements avec un delta maximal de 10 heures.",
            "harness-turn-1",
        )
        _print_capture(live, view=args.view, title="6 DATAFRAMES ACTIFS")
        results = validate_live_capture(live)

        explicit_thread = f"{THREAD_ID}-explicit-reference"
        seed_six_dataframes(store, explicit_thread)
        explicit = capture_model_request(
            store,
            explicit_thread,
            "Utilise df_station_summary pour résumer le delta temporel par station.",
            "harness-explicit-reference",
        )
        results.extend(validate_explicit_reference_capture(explicit))

        metadata_thread = f"{THREAD_ID}-hybrid-metadata"
        seed_six_dataframes(store, metadata_thread)
        execution_error = persist_hybrid_metadata_result(store, metadata_thread)
        metadata_capture = capture_model_request(
            store,
            metadata_thread,
            f"Décris la ressource {HYBRID_RESULT}.",
            "harness-hybrid-metadata",
        )
        results.extend(
            validate_hybrid_metadata_capture(metadata_capture, execution_error)
        )

        many_thread = f"{THREAD_ID}-many"
        many_names = seed_many_dataframes(store, many_thread)
        many_capture = capture_model_request(
            store,
            many_thread,
            f"Analyse précisément {many_names[-1]}.",
            "harness-many-dataframes",
        )
        _print_capture(
            many_capture,
            view=args.view,
            title=f"{MANY_DATAFRAME_COUNT} DATAFRAMES INDEXÉS",
        )
        results.extend(validate_many_dataframe_capture(many_capture, many_names))
        results.extend(validate_lineage_aware_cleanup(store))

        graph_thread = f"{THREAD_ID}-last-graph"
        seed_six_dataframes(store, graph_thread)
        graph_facts = (
            "lignes tracées=42 · colonnes utilisées=station,delta_h · "
            "table de rendu=df_graph_plot · encodages=x=station;y=delta_h"
        )
        graph_code_sentinel = "SECRET_LAST_GRAPH_SCRIPT_SENTINEL"
        store.set(
            f"{graph_thread}:last_graph_grounding",
            None,
            {"facts": graph_facts},
        )
        store.set(
            f"{graph_thread}:last_graph_state",
            None,
            {"code": graph_code_sentinel, "graph_id": "harness-graph"},
        )
        graph_capture = capture_model_request(
            store,
            graph_thread,
            "Résume le dernier graphique.",
            "harness-last-graph",
        )
        results.extend(
            validate_last_graph_facts_capture(
                graph_capture,
                facts=graph_facts,
                code_sentinel=graph_code_sentinel,
            )
        )

        frontier_thread = f"{THREAD_ID}-frontier"
        seed_six_dataframes(store, frontier_thread)
        frontier_objective = "Calcule le nombre d’objets par profil EcoTaxa."
        pending_payload, frontier_messages = build_frontier_payload(
            store,
            frontier_thread,
            frontier_objective,
        )
        pending_capture = capture_model_request(
            store,
            frontier_thread,
            frontier_objective,
            "harness-frontier-pending",
            exploration=pending_payload,
        )
        resolved_payload = resolve_frontier_payload(
            pending_payload,
            frontier_messages,
        )
        resolved_capture = capture_model_request(
            store,
            frontier_thread,
            frontier_objective,
            "harness-frontier-resolved",
            exploration=resolved_payload,
        )
        results.extend(
            validate_frontier_capture(pending_capture, resolved_capture)
        )

        retry_thread = f"{THREAD_ID}-code-retry"
        seed_six_dataframes(store, retry_thread)
        retry_messages: list[BaseMessage] = [
            HumanMessage(
                content="Calcule la moyenne de delta_h.",
                id="retry-human",
            ),
            AIMessage(
                content="",
                id="retry-ai",
                tool_calls=[{
                    "name": "run_pandas",
                    "args": {"code": "result = df_uvp_net_candidates['delta_h'].mean("},
                    "id": "retry-call",
                    "type": "tool_call",
                }],
            ),
            ToolMessage(
                content="SyntaxError: '(' was never closed",
                name="run_pandas",
                tool_call_id="retry-call",
                id="retry-tool",
                artifact={
                    "status": "error",
                    "retryable": True,
                    "summary": "Syntaxe pandas invalide.",
                },
            ),
        ]
        retry_capture = capture_model_request(
            store,
            retry_thread,
            "Calcule la moyenne de delta_h.",
            "harness-code-retry",
            input_messages=retry_messages,
        )
        results.extend(validate_code_retry_capture(retry_capture))

        multiturn_thread = f"{THREAD_ID}-checkpointed-multiturn"
        seed_six_dataframes(store, multiturn_thread)
        graph_dir = Path(directory) / "graphs"
        graph_dir.mkdir(parents=True, exist_ok=True)
        multiturn_calls, multiturn_results = run_checkpointed_multiturn_harness(
            store,
            multiturn_thread,
            graph_dir,
        )
        results.extend(
            validate_checkpointed_multiturn(multiturn_calls, multiturn_results)
        )
        immediate_dependency_context = multiturn_calls[1].runtime_context
        results.append(
            _check(
                "directive immédiate détaillée et en anglais",
                "DATA DEPENDENCY RECOVERY — REQUIRED NEXT ACTION"
                in immediate_dependency_context
                and "Failure class: missing data dependency"
                in immediate_dependency_context
                and "Recovery protocol:" in immediate_dependency_context
                and "Completion condition:" in immediate_dependency_context,
                "l’erreur courante indique données, tools, étapes et sortie attendue",
            )
        )

        aged = live
        for turn in range(2, 8):
            aged = capture_model_request(
                store,
                THREAD_ID,
                "Compare les prélèvements NeoLabs et les profils UVP disponibles.",
                f"harness-turn-{turn}",
            )
        _print_capture(aged, view=args.view, title="APRÈS 6 TOURS SANS L'ANCIEN DÉRIVÉ")
        results.extend(validate_aged_capture(aged))
        return _print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
