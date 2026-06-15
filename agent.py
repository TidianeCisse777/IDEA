"""Agent factory + CLI copépodes (slices 4-5)."""
import os
import sys
import uuid
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tracers import LangChainTracer
from langchain_core.messages import AIMessage, ToolMessage, RemoveMessage
from langgraph.prebuilt import create_react_agent

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from tools.data_tools import make_tools
from tools.bio_oracle_sources import make_bio_oracle_tools
from tools.amundsen_sources import make_amundsen_tools
from tools.ecopart_sources import make_ecopart_tools
from tools.copepod_sources import make_source_tools
from tools.sql_workspace import make_sql_tools
from tools.rag_tool import make_rag_tool
from tools.skill_tool import make_skill_tool
from tools.deliverable_tool import export_deliverable
from tools.geo_tools import get_zone_filter

load_dotenv()

import langchain
langchain.verbose = os.getenv("LANGCHAIN_VERBOSE", "false").lower() == "true"

_CHECKPOINTS_DB = Path(os.getenv("CHECKPOINTS_DB", "data/checkpoints.sqlite"))
_CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)

# Default MemorySaver — overridden at startup by serve.py lifespan via AsyncSqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
_checkpointer = MemorySaver()
_store = InMemoryStore()  # overridden by serve.py lifespan via AsyncPostgresStore


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


_SYSTEM_PROMPT = _load_system_prompt()

_MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "40000"))
# Tool results over this many chars get truncated before being sent to the LLM
_MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "8000"))


def _make_context_hook(user_id: str = "anonymous"):
    """pre_model_hook: inject long-term memories + truncate tool results + trim history."""
    from langchain_core.messages import trim_messages, ToolMessage, SystemMessage

    def _approx_tokens(messages) -> int:
        return sum(len(str(m.content)) for m in messages) // 4

    def _truncate_tool_results(messages):
        out = []
        for m in messages:
            if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > _MAX_TOOL_RESULT_CHARS:
                truncated = m.content[:_MAX_TOOL_RESULT_CHARS] + f"\n[…tronqué — {len(m.content):,} chars total]"
                out.append(m.model_copy(update={"content": truncated}))
            else:
                out.append(m)
        return out

    def _inject_memories(messages):
        """Prepend stored long-term memories to the system message."""
        try:
            memories = _store.search((user_id, "memories"))
            if not memories:
                return messages
            mem_text = "\n".join(
                f"- {item.value.get('content', '')}"
                for item in memories
                if item.value.get("content")
            )
            if not mem_text:
                return messages
            memory_block = f"\n\n## Remembered preferences and corrections\n{mem_text}"
            updated = []
            injected = False
            for m in messages:
                if isinstance(m, SystemMessage) and not injected:
                    updated.append(m.model_copy(update={"content": m.content + memory_block}))
                    injected = True
                else:
                    updated.append(m)
            return updated
        except Exception:
            return messages

    def trim_context(state: dict) -> dict:
        msgs = _truncate_tool_results(state["messages"])
        msgs = _inject_memories(msgs)
        trimmed = trim_messages(
            msgs,
            max_tokens=_MAX_CONTEXT_TOKENS,
            strategy="last",
            token_counter=_approx_tokens,
            include_system=True,
            allow_partial=False,
        )
        return {"messages": trimmed}

    return trim_context


def _find_invalid_tool_history_cut_index(messages: Sequence) -> int | None:
    """Retourne l'index à partir duquel l'historique devient invalide.

    LangGraph exige qu'un `AIMessage` contenant des `tool_calls` soit suivi
    des `ToolMessage` correspondants. Si la fin de l'historique est orpheline,
    on coupe à partir du premier message non équilibré.
    """
    pending_tool_call_ids: set[str] = set()
    first_pending_ai_index: int | None = None

    for index, message in enumerate(messages):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            if pending_tool_call_ids:
                return first_pending_ai_index
            if first_pending_ai_index is None:
                first_pending_ai_index = index
            for tool_call in message.tool_calls:
                tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
                if tool_call_id:
                    pending_tool_call_ids.add(str(tool_call_id))
            continue

        if isinstance(message, ToolMessage):
            tool_call_id = getattr(message, "tool_call_id", None)
            if tool_call_id in pending_tool_call_ids:
                pending_tool_call_ids.remove(tool_call_id)
                if not pending_tool_call_ids:
                    first_pending_ai_index = None
                continue
            if pending_tool_call_ids:
                return first_pending_ai_index
            return index

        if pending_tool_call_ids:
            return first_pending_ai_index

    if pending_tool_call_ids:
        return first_pending_ai_index
    return None


def repair_invalid_tool_history(agent, config: dict) -> bool:
    """Nettoie un thread LangGraph si un tool_call est resté sans ToolMessage.

    Retourne True si l'historique a été modifié.
    """
    try:
        snapshot = agent.get_state(config)
    except Exception:
        return False

    values = getattr(snapshot, "values", {}) or {}
    messages = list(values.get("messages") or [])
    cut_index = _find_invalid_tool_history_cut_index(messages)
    if cut_index is None:
        return False

    removals = [
        RemoveMessage(id=message.id)
        for message in messages[cut_index:]
        if getattr(message, "id", None)
    ]
    if not removals:
        return False

    try:
        agent.update_state(config, {"messages": removals})
        return True
    except Exception:
        return False


async def arepair_invalid_tool_history(agent, config: dict) -> bool:
    """Async version of repair_invalid_tool_history for AsyncSqliteSaver."""
    try:
        snapshot = await agent.aget_state(config)
    except Exception:
        return False

    values = getattr(snapshot, "values", {}) or {}
    messages = list(values.get("messages") or [])
    cut_index = _find_invalid_tool_history_cut_index(messages)
    if cut_index is None:
        return False

    removals = [
        RemoveMessage(id=message.id)
        for message in messages[cut_index:]
        if getattr(message, "id", None)
    ]
    if not removals:
        return False

    try:
        await agent.aupdate_state(config, {"messages": removals})
        return True
    except Exception:
        return False


def make_agent(thread_id: str, user_id: str = "anonymous"):
    """Crée un agent ReAct copépodes pour un thread donné."""
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
        max_retries=2,
        max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "16000")),
    )
    tools = (
        make_tools(thread_id)
        + make_source_tools(thread_id)
        + make_bio_oracle_tools(thread_id)
        + make_amundsen_tools(thread_id)
        + make_ecopart_tools(thread_id)
        + [make_rag_tool(), make_skill_tool(), export_deliverable, get_zone_filter]
    )
    try:
        tools += make_sql_tools(thread_id)
    except ValueError:
        pass

    return create_react_agent(
        llm,
        tools,
        prompt=_SYSTEM_PROMPT,
        pre_model_hook=_make_context_hook(user_id=user_id),
        checkpointer=_checkpointer,
        store=_store,
    )


def _make_tracer(thread_id: str, user_id: str = "anonymous", user_email: str | None = None) -> LangChainTracer | None:
    """Retourne un LangChainTracer si LANGCHAIN_TRACING_V2 est activé."""
    if os.getenv("LANGCHAIN_TRACING_V2", "false").lower() != "true":
        return None
    project = os.getenv("LANGCHAIN_PROJECT", "copepod-agent")
    user_tag = f"user:{user_email or user_id}"
    return LangChainTracer(project_name=project, tags=["copepod", thread_id[:8], user_tag])


def invoke_verbose(agent, messages: dict, config: dict) -> dict:
    """Invoke agent with streaming, printing tool calls to stdout in real time."""
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    meta = config.get("metadata", {}) or {}
    tracer = _make_tracer(thread_id, user_id=meta.get("user_id", "anonymous"), user_email=meta.get("user_email"))
    if tracer and "callbacks" not in config:
        config = {**config, "callbacks": [tracer]}

    repair_invalid_tool_history(agent, config)

    final_state = None
    for chunk in agent.stream(messages, config=config, stream_mode="values"):
        final_state = chunk
        msgs = chunk.get("messages", [])
        if msgs:
            last = msgs[-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                for tc in last.tool_calls:
                    name = tc["name"] if isinstance(tc, dict) else tc.name
                    args = tc.get("args", {}) if isinstance(tc, dict) else tc.args
                    print(f"  → tool: {name}  args: {str(args)[:120]}")
    return final_state or {}


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
    repair_invalid_tool_history(agent, config)
    agent.invoke({"messages": [{"role": "user", "content": load_msg}]}, config=config)

    # Poser la question
    repair_invalid_tool_history(agent, config)
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
            repair_invalid_tool_history(ag, cfg)
            res = ag.invoke({"messages": [{"role": "user", "content": q}]}, config=cfg)
            print(f"\nAgent : {res['messages'][-1].content}\n")
