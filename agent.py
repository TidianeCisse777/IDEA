"""Agent factory — Planner + Executor copépodes (slice 4)."""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from tools.data_tools import make_tools
from tools.rag_tool import make_rag_tool

load_dotenv()

_checkpointer = MemorySaver()


def _load_system_prompt() -> str:
    """Charge le prompt depuis LangSmith Hub, fallback local."""
    try:
        from langchain import hub
        prompt = hub.pull("copepod-system-prompt")
        # hub.pull retourne un ChatPromptTemplate — on extrait le contenu système
        messages = prompt.messages
        for msg in messages:
            if hasattr(msg, "prompt"):
                return msg.prompt.template
        return COPEPOD_SYSTEM_PROMPT
    except Exception:
        return COPEPOD_SYSTEM_PROMPT


def make_agent(thread_id: str):
    """Crée un agent ReAct copépodes pour un thread donné.

    Args:
        thread_id: Identifiant de session (conversation). Utilisé pour la mémoire
                   et le store de DataFrame.

    Returns:
        CompiledStateGraph LangGraph prêt à invoquer.
    """
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
        max_retries=2,
    )
    tools = make_tools(thread_id) + [make_rag_tool()]
    system_prompt = _load_system_prompt()

    return create_react_agent(
        llm,
        tools,
        prompt=system_prompt,
        checkpointer=_checkpointer,
    )


if __name__ == "__main__":
    import uuid

    thread_id = str(uuid.uuid4())
    agent = make_agent(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    print("Agent copépodes prêt. 'exit' pour quitter.\n")
    while True:
        question = input("Vous : ").strip()
        if question.lower() in ("exit", "quit", "q"):
            break
        if not question:
            continue
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config=config,
        )
        print(f"\nAgent : {result['messages'][-1].content}\n")
