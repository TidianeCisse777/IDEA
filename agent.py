"""Agent factory + CLI copépodes (slices 4-5)."""
import asyncio
import os
import sys
import threading
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tracers import LangChainTracer
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from core.llm_config import chat_openai_connection_kwargs
from tools.tool_catalog import build_tool_catalog

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
    """Source de vérité : le fichier local `agents/copepod_system_prompt.py`.

    Le hub LangSmith a été retiré du chemin : `langchain.hub` n'existe plus
    en langchain 1.x, et `langsmith.Client.pull_prompt()` ne résout pas nos
    prompts personnels (stockés sans `owner` côté serveur). La migration
    via PR git est suffisamment ergonomique pour un projet mono-tenant ; on
    réactivera la lecture hub quand LangSmith aura fixé le bug d'owner.
    """
    return COPEPOD_SYSTEM_PROMPT


_SYSTEM_PROMPT = _load_system_prompt()

_MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "40000"))
_CONTEXT_RESERVE_TOKENS = int(os.getenv("CONTEXT_RESERVE_TOKENS", "2000"))
# Tool results over this many chars get truncated before being sent to the LLM
_MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "8000"))
_context_audit_by_thread: dict[str, dict] = {}


def get_context_audit(thread_id: str | None = None) -> dict:
    """Return latest context-management audit metrics."""
    if thread_id:
        return dict(_context_audit_by_thread.get(thread_id, {}))
    return {key: dict(value) for key, value in _context_audit_by_thread.items()}


def clear_context_audit(thread_id: str | None = None) -> None:
    """Clear context audit metrics, mainly for tests and debug endpoints."""
    if thread_id:
        _context_audit_by_thread.pop(thread_id, None)
    else:
        _context_audit_by_thread.clear()


def _approx_tokens(messages) -> int:
    """Fast, stable token estimate used by trimming and its audit."""
    return count_tokens_approximately(messages)


def compute_history_budget(
    *,
    max_input_tokens: int,
    system_tokens: int,
    tool_tokens: int,
    memory_tokens: int,
    reserve_tokens: int = 2000,
) -> int:
    """Return the history share after all fixed request costs are reserved."""
    maximum = max(1, int(max_input_tokens))
    available = (
        maximum
        - int(system_tokens)
        - int(tool_tokens)
        - int(memory_tokens)
        - int(reserve_tokens)
    )
    return min(maximum, max(1000, available))


def _tool_schema_tokens(tools) -> int:
    """Estimate the model-input cost of declared tool names, docs and schemas."""
    payload = []
    for item in tools or []:
        if isinstance(item, dict):
            payload.append(item)
            continue
        schema = getattr(item, "args_schema", None)
        if schema is not None and hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        payload.append({
            "name": getattr(item, "name", ""),
            "description": getattr(item, "description", ""),
            "parameters": schema or {},
        })
    if not payload:
        return 0
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return _approx_tokens([SystemMessage(content=serialized)])


def _truncate_tool_results(messages):
    """Return request-local ToolMessage copies capped to the configured size."""
    output = []
    metrics = {
        "tool_messages_seen": 0,
        "tool_messages_truncated": 0,
        "tool_result_chars_before": 0,
        "tool_result_chars_after": 0,
        "tool_result_chars_saved": 0,
        "max_tool_result_chars": _MAX_TOOL_RESULT_CHARS,
    }
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            metrics["tool_messages_seen"] += 1
            metrics["tool_result_chars_before"] += len(message.content)
            if len(message.content) > _MAX_TOOL_RESULT_CHARS:
                content = (
                    message.content[:_MAX_TOOL_RESULT_CHARS]
                    + f"\n[…tronqué — {len(message.content):,} chars total]"
                )
                metrics["tool_messages_truncated"] += 1
                output.append(message.model_copy(update={"content": content}))
            else:
                content = message.content
                output.append(message)
            metrics["tool_result_chars_after"] += len(content)
        else:
            output.append(message)
    metrics["tool_result_chars_saved"] = (
        metrics["tool_result_chars_before"] - metrics["tool_result_chars_after"]
    )
    return output, metrics


def _trim_request_messages(messages, *, max_tokens: int | None = None):
    """Keep a recent, valid conversation suffix for one model request."""
    trimmed = trim_messages(
        messages,
        max_tokens=max_tokens or _MAX_CONTEXT_TOKENS,
        strategy="last",
        token_counter=_approx_tokens,
        start_on="human",
        include_system=False,
        allow_partial=False,
    )
    if trimmed or not messages:
        return list(trimmed)

    # A single current turn can exceed the budget. Keep it whole rather than
    # sending orphaned ToolMessages or dropping the user's request entirely.
    last_human_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        len(messages) - 1,
    )
    return list(messages[last_human_index:])


def _build_memory_block(memories) -> tuple[str, dict]:
    """Construit le bloc mémoire long-terme à ajouter au system prompt.

    Retourne (bloc_texte, metrics). `bloc_texte` est vide si aucune mémoire
    exploitable n'a été trouvée.
    """
    if not memories:
        return "", {"memories_found": 0, "memory_chars": 0, "memory_injected": False}
    mem_text = "\n".join(
        f"- {item.value.get('content', '')}"
        for item in memories
        if item.value.get("content")
    )
    if not mem_text:
        return "", {"memories_found": len(memories), "memory_chars": 0, "memory_injected": False}
    block = f"\n\n## Remembered preferences and corrections\n{mem_text}"
    return block, {
        "memories_found": len(memories),
        "memory_chars": len(block),
        "memory_injected": True,
    }


class _ContextMiddleware(AgentMiddleware):
    """Prepare the exact request seen by the model without mutating checkpoints."""

    def __init__(
        self,
        user_id: str = "anonymous",
        thread_id: str = "unknown",
        output_intent_classifier=None,
    ):
        super().__init__()
        self.user_id = user_id
        self.thread_id = thread_id
        self.output_intent_classifier = output_intent_classifier
        self._output_intent_cache = {}
        self._output_intent_classifier_calls = {}
        self._output_intent_sync_lock = threading.Lock()
        self._output_intent_async_lock = asyncio.Lock()

    def _prepare_request(self, request, memories):
        original_messages = list(request.messages)
        try:
            from tools.data_tools import reset_graph_block_on_new_turn
            from tools.session_store import default_store as session_store

            reset_graph_block_on_new_turn(
                session_store, self.thread_id, original_messages
            )
        except Exception:
            pass

        original_tokens = _approx_tokens(original_messages)
        truncated_messages, truncate_metrics = _truncate_tool_results(
            original_messages
        )
        truncated_tokens = _approx_tokens(truncated_messages)

        block, metrics = _build_memory_block(memories)
        from tools.session_context import build_dataset_state_capsule
        from tools.session_store import default_store as session_store

        dataset_block = build_dataset_state_capsule(session_store, self.thread_id)
        system_message = request.system_message
        base = system_message.content if system_message is not None else ""
        injected_context = block + dataset_block
        base_system_tokens = (
            _approx_tokens([SystemMessage(content=base)]) if base else 0
        )
        memory_tokens = (
            _approx_tokens([SystemMessage(content=injected_context)])
            if injected_context
            else 0
        )
        tool_schema_tokens = _tool_schema_tokens(request.tools)
        history_budget = compute_history_budget(
            max_input_tokens=_MAX_CONTEXT_TOKENS,
            system_tokens=base_system_tokens,
            tool_tokens=tool_schema_tokens,
            memory_tokens=memory_tokens,
            reserve_tokens=_CONTEXT_RESERVE_TOKENS,
        )
        trimmed_messages = _trim_request_messages(
            truncated_messages,
            max_tokens=history_budget,
        )
        final_tokens = _approx_tokens(trimmed_messages)
        prepared_system_message = (
            SystemMessage(content=base + injected_context)
            if injected_context
            else system_message
        )
        system_tokens = (
            _approx_tokens([prepared_system_message])
            if prepared_system_message is not None
            else 0
        )

        _context_audit_by_thread[self.thread_id] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "messages_before": len(original_messages),
            "messages_after_tool_truncation": len(truncated_messages),
            "messages_after_trim": len(trimmed_messages),
            "messages_trimmed": max(
                0, len(truncated_messages) - len(trimmed_messages)
            ),
            "approx_tokens_before": original_tokens,
            "approx_tokens_after_tool_truncation": truncated_tokens,
            "approx_tokens_after_memory": system_tokens + truncated_tokens,
            "approx_tokens_after_trim": final_tokens,
            "approx_tokens_system_message": system_tokens,
            "approx_tokens_base_system": base_system_tokens,
            "approx_tokens_memory_and_capsule": memory_tokens,
            "approx_tokens_tool_schemas": tool_schema_tokens,
            "history_budget_tokens": history_budget,
            "context_reserve_tokens": _CONTEXT_RESERVE_TOKENS,
            "approx_tokens_model_request": (
                base_system_tokens + memory_tokens + tool_schema_tokens + final_tokens
            ),
            "total_estimated": (
                base_system_tokens + memory_tokens + tool_schema_tokens + final_tokens
            ),
            "approx_tokens_saved_by_tool_truncation": max(
                0, original_tokens - truncated_tokens
            ),
            "approx_tokens_saved_by_trim": max(
                0, truncated_tokens - final_tokens
            ),
            "max_context_tokens": _MAX_CONTEXT_TOKENS,
            "context_limit_exceeded_by_latest_turn": (
                final_tokens > _MAX_CONTEXT_TOKENS
            ),
            **truncate_metrics,
            **metrics,
            "dataset_capsule_injected": bool(dataset_block),
            "dataset_capsule_chars": len(dataset_block),
        }
        # Source policy: one deterministic decision filters every external
        # family before the model and is reused by the tool-call guard.
        try:
            from tools.source_scope import (
                filter_tools_for_decision,
                source_decision_for_turn,
            )
            from tools.tool_catalog import TOOL_POLICIES

            source_decision = source_decision_for_turn(
                session_store,
                self.thread_id,
                original_messages,
            )
            scoped_tools = filter_tools_for_decision(
                list(request.tools),
                source_decision,
                TOOL_POLICIES,
            )
            return request.override(
                messages=trimmed_messages,
                system_message=prepared_system_message,
                tools=scoped_tools,
            )
        except TypeError:
            # request.override may not accept tools on this build; the
            # wrap_tool_call guard still enforces the scope hard.
            return request.override(
                messages=trimmed_messages,
                system_message=prepared_system_message,
            )

    def _source_scope_rejection(self, request) -> str | None:
        from tools.session_store import default_store as session_store
        from tools.source_scope import (
            source_decision_for_turn,
            source_rejection_for_call,
        )
        from tools.tool_catalog import TOOL_POLICIES

        tool_call = request.tool_call
        name = str(tool_call.get("name") or "")
        args = dict(tool_call.get("args") or {})
        messages = request.state.get("messages") or []
        decision = source_decision_for_turn(
            session_store,
            self.thread_id,
            messages,
        )
        return source_rejection_for_call(
            decision,
            name,
            args,
            TOOL_POLICIES,
        )

    @staticmethod
    def _blocked_tool_message(
        request,
        rejection: str,
        *,
        provenance_source: str = "source_policy",
        method: str = "deterministic source guard",
    ) -> ToolMessage:
        from tools.tool_result import blocked

        content, artifact = blocked(
            rejection,
            provenance={"source": provenance_source},
            method=method,
        )
        return ToolMessage(
            content=content,
            artifact=artifact,
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def _tool_identifier_rejection(self, request) -> str | None:
        from tools.session_context import reject_ungrounded_ecotaxa_identifiers
        from tools.session_store import default_store as session_store

        tool_call = request.tool_call
        return reject_ungrounded_ecotaxa_identifiers(
            session_store,
            self.thread_id,
            request.state.get("messages") or [],
            str(tool_call.get("name") or ""),
            dict(tool_call.get("args") or {}),
        )

    def _persist_output_intent(self, decision) -> None:
        from tools.session_store import default_store as session_store

        fingerprint = decision.turn_fingerprint
        session_store.update_meta(
            self.thread_id,
            {
                "output_intent_decision": decision.model_dump(mode="json"),
                "output_intent_classifier_calls": self._output_intent_classifier_calls.get(
                    fingerprint, 0
                ),
            },
        )

    def _output_intent_decision(self, messages):
        from tools.output_intent import OutputIntentDecision, turn_fingerprint

        fingerprint = turn_fingerprint(messages)
        cached = self._output_intent_cache.get(fingerprint)
        if cached is not None:
            return cached
        with self._output_intent_sync_lock:
            cached = self._output_intent_cache.get(fingerprint)
            if cached is not None:
                return cached
            try:
                if self.output_intent_classifier is None:
                    raise RuntimeError("output intent classifier unavailable")
                decision = self.output_intent_classifier.classify(messages)
                if decision.turn_fingerprint != fingerprint:
                    raise ValueError("classifier returned a mismatched turn fingerprint")
            except Exception:
                decision = OutputIntentDecision(
                    intent="ambiguous",
                    confidence="low",
                    reason="classifier unavailable",
                    turn_fingerprint=fingerprint,
                )
            self._output_intent_classifier_calls[fingerprint] = (
                self._output_intent_classifier_calls.get(fingerprint, 0) + 1
            )
            self._output_intent_cache[fingerprint] = decision
            self._persist_output_intent(decision)
            return decision

    async def _aoutput_intent_decision(self, messages):
        from tools.output_intent import OutputIntentDecision, turn_fingerprint

        fingerprint = turn_fingerprint(messages)
        cached = self._output_intent_cache.get(fingerprint)
        if cached is not None:
            return cached
        async with self._output_intent_async_lock:
            cached = self._output_intent_cache.get(fingerprint)
            if cached is not None:
                return cached
            try:
                if self.output_intent_classifier is None:
                    raise RuntimeError("output intent classifier unavailable")
                decision = await self.output_intent_classifier.aclassify(messages)
                if decision.turn_fingerprint != fingerprint:
                    raise ValueError("classifier returned a mismatched turn fingerprint")
            except Exception:
                decision = OutputIntentDecision(
                    intent="ambiguous",
                    confidence="low",
                    reason="classifier unavailable",
                    turn_fingerprint=fingerprint,
                )
            self._output_intent_classifier_calls[fingerprint] = (
                self._output_intent_classifier_calls.get(fingerprint, 0) + 1
            )
            self._output_intent_cache[fingerprint] = decision
            self._persist_output_intent(decision)
            return decision

    @staticmethod
    def _decision_rejection(decision) -> str | None:
        if decision.intent == "visual":
            return None
        if decision.intent == "non_visual":
            return (
                "Graph workflow blocked: the requested output is non-visual. "
                "Return the requested number, calculation, ranking, summary, "
                "coordinates, or table without graph skills."
            )
        return (
            "Graph workflow blocked: the requested output format is ambiguous. "
            "Clarify whether a visual figure is required before using graph skills."
        )

    def _output_intent_rejection(self, request) -> str | None:
        from tools.output_intent import graph_attempt, graph_workflow_rejection

        tool_call = request.tool_call
        name = str(tool_call.get("name") or "")
        args = dict(tool_call.get("args") or {})
        if not graph_attempt(name, args):
            return None
        messages = list(request.state.get("messages") or [])
        decision = self._output_intent_decision(messages)
        return self._decision_rejection(decision) or graph_workflow_rejection(
            name, args, messages
        )

    async def _aoutput_intent_rejection(self, request) -> str | None:
        from tools.output_intent import graph_attempt, graph_workflow_rejection

        tool_call = request.tool_call
        name = str(tool_call.get("name") or "")
        args = dict(tool_call.get("args") or {})
        if not graph_attempt(name, args):
            return None
        messages = list(request.state.get("messages") or [])
        decision = await self._aoutput_intent_decision(messages)
        return self._decision_rejection(decision) or graph_workflow_rejection(
            name, args, messages
        )

    def wrap_tool_call(self, request, handler):
        rejection = self._source_scope_rejection(request) or self._tool_identifier_rejection(request)
        if rejection:
            return self._blocked_tool_message(request, rejection)
        rejection = self._output_intent_rejection(request)
        if rejection:
            return self._blocked_tool_message(
                request,
                rejection,
                provenance_source="output_intent_guard",
                method="typed output intent guard",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        rejection = self._source_scope_rejection(request) or self._tool_identifier_rejection(request)
        if rejection:
            return self._blocked_tool_message(request, rejection)
        rejection = await self._aoutput_intent_rejection(request)
        if rejection:
            return self._blocked_tool_message(
                request,
                rejection,
                provenance_source="output_intent_guard",
                method="typed output intent guard",
            )
        return await handler(request)

    def wrap_model_call(self, request, handler):
        store = getattr(request.runtime, "store", None)
        memories = []
        if store is not None:
            try:
                memories = store.search((self.user_id, "memories"))
            except Exception:
                memories = []
        return handler(self._prepare_request(request, memories))

    async def awrap_model_call(self, request, handler):
        store = getattr(request.runtime, "store", None)
        memories = []
        if store is not None:
            try:
                memories = await store.asearch((self.user_id, "memories"))
            except Exception:
                memories = []
        return await handler(self._prepare_request(request, memories))


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
        model=os.getenv("LLM_MODEL", "gpt-5.4-mini"),
        max_retries=2,
        max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "16000")),
        **chat_openai_connection_kwargs(),
    )
    catalog = build_tool_catalog(thread_id)
    from tools.output_intent import OpenAIOutputIntentClassifier

    output_intent_classifier = OpenAIOutputIntentClassifier(llm)

    return create_agent(
        llm,
        list(catalog.tools),
        system_prompt=_SYSTEM_PROMPT,
        middleware=[
            _ContextMiddleware(
                user_id=user_id,
                thread_id=thread_id,
                output_intent_classifier=output_intent_classifier,
            )
        ],
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
