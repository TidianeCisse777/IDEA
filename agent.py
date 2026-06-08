"""Agent factory + CLI copépodes (slices 4-5)."""
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tracers import LangChainTracer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from tools.data_tools import make_tools
from tools.rag_tool import make_rag_tool
from tools.skill_tool import make_skill_tool

load_dotenv()

_checkpointer = MemorySaver()


def _load_system_prompt() -> str:
    """Charge le prompt depuis LangSmith Hub, fallback local."""
    try:
        from langchain import hub
        prompt = hub.pull("copepod-system-prompt")
        for msg in prompt.messages:
            if hasattr(msg, "prompt"):
                return msg.prompt.template
        return COPEPOD_SYSTEM_PROMPT
    except Exception:
        return COPEPOD_SYSTEM_PROMPT


def make_agent(thread_id: str):
    """Crée un agent ReAct copépodes pour un thread donné."""
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
        max_retries=2,
    )
    tools = make_tools(thread_id) + [make_rag_tool(), make_skill_tool()]
    system_prompt = _load_system_prompt()

    return create_react_agent(
        llm,
        tools,
        prompt=system_prompt,
        checkpointer=_checkpointer,
    )


def run_query(file_path: str, question: str, thread_id: str | None = None) -> str:
    """Exécute une question sur un fichier de données.

    Args:
        file_path: Chemin vers le fichier à analyser.
        question: Question en langage naturel.
        thread_id: ID de session (généré si absent).

    Returns:
        Réponse finale de l'agent.
    """
    thread_id = thread_id or str(uuid.uuid4())
    file_name = Path(file_path).name

    from tools.data_tools import _sessions
    n_rows = _sessions.get(thread_id, {}).get("meta", {}).get("n_rows", "?")

    tracer = LangChainTracer(
        project_name=os.getenv("LANGCHAIN_PROJECT", "copepod-agent"),
        tags=["copepod", "data-analysis"],
    )

    agent = make_agent(thread_id)
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [tracer],
    }

    # Charger le fichier en premier message
    load_msg = f"Charge ce fichier : {file_path}"
    agent.invoke({"messages": [{"role": "user", "content": load_msg}]}, config=config)

    # Poser la question
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        # Mode une question : python agent.py fichier.tsv "question"
        response = run_query(sys.argv[1], sys.argv[2])
        print(response)
    else:
        # Mode REPL interactif
        tid = str(uuid.uuid4())
        ag = make_agent(tid)
        cfg = {"configurable": {"thread_id": tid}}
        print("Agent copépodes prêt. 'exit' pour quitter.\n")
        while True:
            q = input("Vous : ").strip()
            if q.lower() in ("exit", "quit", "q"):
                break
            if not q:
                continue
            res = ag.invoke({"messages": [{"role": "user", "content": q}]}, config=cfg)
            print(f"\nAgent : {res['messages'][-1].content}\n")
