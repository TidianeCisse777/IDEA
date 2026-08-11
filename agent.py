"""Agent factory + CLI copépodes (slices 4-5)."""
import base64
import copy
import io
import os
import sys
import threading
import time
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
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from agents.exploration_middleware import ExplorationStateMiddleware
from agents.exploration_state import (
    IdeaAgentState,
    recovery_tool_names,
    render_dataframe_context,
    render_exploration_frontier,
    render_task_context,
)
from core.llm_config import chat_openai_connection_kwargs
from tools.tool_catalog import build_tool_catalog

load_dotenv()


def _configure_langsmith_tracing() -> None:
    """Normalize the legacy LangChain tracing variables for LangSmith.

    Existing deployments were configured with ``LANGCHAIN_TRACING_V2`` and
    ``LANGCHAIN_API_KEY``.  LangSmith clients now read ``LANGSMITH_TRACING``
    and ``LANGSMITH_API_KEY``.  Keep the legacy variables supported while
    making the active process observable by both integrations.  The API key
    is copied only in-process and is never logged.
    """
    if os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true":
        os.environ.setdefault("LANGSMITH_TRACING", "true")
    legacy_key = os.getenv("LANGCHAIN_API_KEY")
    if legacy_key:
        os.environ.setdefault("LANGSMITH_API_KEY", legacy_key)


_configure_langsmith_tracing()

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

# Quality ceiling, deliberately lower than the provider's technical context
# window: the agent must keep its instructions, tool evidence and user request
# in the high-attention portion of the context. Override only for controlled
# evaluations that need a larger window.
_MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "100000"))
_CONTEXT_RESERVE_TOKENS = int(os.getenv("CONTEXT_RESERVE_TOKENS", "2000"))
_MAX_MODEL_CALLS_PER_TURN = int(os.getenv("MAX_MODEL_CALLS_PER_TURN", "10"))
# Tool results over this many chars get truncated before being sent to the LLM
_MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "8000"))
_KEEP_FULL_TOOL_TURNS = int(os.getenv("KEEP_FULL_TOOL_TURNS", "1"))
# Second-pass budget: if total tool-result chars after first compaction exceeds
# this, oldest eligible messages are compacted further (never the current turn).
_MAX_TOTAL_TOOL_CHARS = int(os.getenv("MAX_TOTAL_TOOL_RESULT_CHARS", "40000"))
# A successful plot normally needs one more model call for its user-facing
# caption.  Give that already-required call a bounded thumbnail so the model
# can check the *actual* image, not merely assume that a PNG means a good plot.
# The configured OpenAI model accepts image input for this review. This can be
# disabled for a text-only provider without changing graph execution.
_GRAPH_VISION_REVIEW_ENABLED = os.getenv(
    "GRAPH_VISION_REVIEW_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}
_GRAPH_VISION_REVIEW_MAX_EDGE = max(
    256, int(os.getenv("GRAPH_VISION_REVIEW_MAX_EDGE", "768"))
)
_context_audit_by_thread: dict[str, dict] = {}
_harness_trace_by_thread: dict[str, dict] = {}
_harness_trace_lock = threading.Lock()

_RAG_TOOL_NAME = "query_copepod_knowledge_base"


def _wait_for_rag_response(response):
    """Keep only RAG calls when a model tries to launch them with other tools."""

    changed = False
    messages = []
    for message in response.result:
        calls = list(getattr(message, "tool_calls", None) or [])
        rag_calls = [
            call for call in calls
            if str(call.get("name") or "") == _RAG_TOOL_NAME
        ]
        if rag_calls and len(rag_calls) != len(calls):
            message = message.model_copy(update={"tool_calls": rag_calls})
            changed = True
        messages.append(message)
    if not changed:
        return response
    updated = copy.copy(response)
    updated.result = messages
    return updated


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


def get_harness_trace(thread_id: str | None = None) -> dict:
    """Return the current turn trace used by one-by-one curl diagnostics."""

    with _harness_trace_lock:
        if thread_id:
            return copy.deepcopy(_harness_trace_by_thread.get(thread_id, {}))
        return copy.deepcopy(_harness_trace_by_thread)


def clear_harness_trace(thread_id: str | None = None) -> None:
    """Clear curl-harness traces without touching conversation state."""

    with _harness_trace_lock:
        if thread_id:
            _harness_trace_by_thread.pop(thread_id, None)
        else:
            _harness_trace_by_thread.clear()


def record_harness_usage(thread_id: str, usage: dict) -> None:
    """Attach provider-reported usage once the HTTP/SSE turn completes."""

    with _harness_trace_lock:
        trace = _harness_trace_by_thread.get(thread_id)
        if trace is not None:
            model_usage = [
                call.get("provider_usage") or {}
                for call in trace.get("model_calls", [])
            ]
            cumulative = {
                "prompt_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in model_usage),
                "completion_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in model_usage),
                "cached_tokens": sum(int(item.get("cached_tokens", 0) or 0) for item in model_usage),
            }
            cumulative["total_tokens"] = (
                cumulative["prompt_tokens"] + cumulative["completion_tokens"]
            )
            trace["usage"] = {
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
                "cumulative_model_calls": cumulative,
                "final_response_call": copy.deepcopy(usage),
            }
            trace["completed_at"] = datetime.now(timezone.utc).isoformat()


def record_harness_fast_route(
    thread_id: str,
    *,
    route: str,
    timings_ms: dict[str, float],
    cache_hit: bool,
) -> None:
    """Record a deterministic response that intentionally made no model calls."""
    with _harness_trace_lock:
        _harness_trace_by_thread[thread_id] = {
            "thread_id": thread_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "timings_ms": dict(timings_ms),
            "cache_hit": bool(cache_hit),
            "model_calls": [],
            "tool_calls": [],
            "usage": {
                "total_tokens": 0,
                "cumulative_model_calls": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "total_tokens": 0,
                },
            },
        }


def _begin_harness_turn(thread_id: str, messages: list) -> None:
    if not (messages and isinstance(messages[-1], HumanMessage)):
        return
    content = messages[-1].content
    with _harness_trace_lock:
        _harness_trace_by_thread[thread_id] = {
            "thread_id": thread_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "user_message": str(content),
            "model_calls": [],
            "tool_calls": [],
            "usage": {},
        }


def _append_harness_model_call(thread_id: str, audit: dict) -> None:
    with _harness_trace_lock:
        trace = _harness_trace_by_thread.get(thread_id)
        if trace is None:
            return
        calls = trace["model_calls"]
        calls.append({
            "index": len(calls) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "approx_tokens_model_request": audit.get("approx_tokens_model_request", 0),
            "approx_tokens_base_system": audit.get("approx_tokens_base_system", 0),
            "approx_tokens_tool_schemas": audit.get("approx_tokens_tool_schemas", 0),
            "approx_tokens_history": audit.get("approx_tokens_after_trim", 0),
            "approx_tokens_memory_and_capsule": audit.get("approx_tokens_memory_and_capsule", 0),
            "approx_tokens_runtime_context": audit.get("approx_tokens_runtime_context", 0),
            "tool_messages_seen": audit.get("tool_messages_seen", 0),
            "tool_messages_truncated": audit.get("tool_messages_truncated", 0),
            "tools_exposed": list(audit.get("tools_exposed") or []),
            "tool_exposure_groups": list(audit.get("tool_exposure_groups") or []),
            "authorized_sources": list(audit.get("turn_authorized_sources") or []),
            "active_variable": audit.get("turn_active_variable"),
            "policy_overflow": bool(audit.get("policy_overflow", False)),
            "_started_epoch": time.time(),
        })


def _finish_harness_model_call(thread_id: str, result) -> None:
    with _harness_trace_lock:
        trace = _harness_trace_by_thread.get(thread_id)
        if trace is None or not trace.get("model_calls"):
            return
        call = next(
            (
                item
                for item in reversed(trace["model_calls"])
                if "provider_usage" not in item
            ),
            None,
        )
        if call is None:
            return
        started = float(call.pop("_started_epoch", time.time()))
        usage = getattr(result, "usage_metadata", None) or {}
        response = getattr(result, "response_metadata", None) or {}
        cached = (
            response.get("token_usage", {})
            .get("prompt_tokens_details", {})
            .get("cached_tokens", 0)
            or usage.get("input_token_details", {}).get("cache_read", 0)
        )
        call["provider_usage"] = {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cached_tokens": int(cached or 0),
        }
        call["duration_seconds"] = round(max(0.0, time.time() - started), 3)


def _safe_trace_args(value):
    """Redact secret-bearing fields and bound debug payload size."""

    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in ("password", "token", "secret", "api_key", "database_url")):
                safe[str(key)] = "[REDACTED]"
            else:
                safe[str(key)] = _safe_trace_args(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_trace_args(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 2_000:
        return value[:2_000] + f"… [{len(value)} chars]"
    return value


def _start_harness_tool_call(thread_id: str, tool_call: dict) -> int | None:
    with _harness_trace_lock:
        trace = _harness_trace_by_thread.get(thread_id)
        if trace is None:
            return None
        calls = trace["tool_calls"]
        trace_id = len(calls) + 1
        calls.append({
            "index": trace_id,
            "tool_call_id": str(tool_call.get("id") or ""),
            "name": str(tool_call.get("name") or ""),
            "arguments": _safe_trace_args(dict(tool_call.get("args") or {})),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "_started_epoch": time.time(),
        })
        return trace_id


def _finish_harness_tool_call(
    thread_id: str,
    trace_id: int | None,
    result=None,
    *,
    blocked_by: str | None = None,
    error_text: str | None = None,
) -> None:
    if trace_id is None:
        return
    with _harness_trace_lock:
        trace = _harness_trace_by_thread.get(thread_id)
        if trace is None or trace_id > len(trace["tool_calls"]):
            return
        entry = trace["tool_calls"][trace_id - 1]
        started = float(entry.pop("_started_epoch", time.time()))
        entry["duration_seconds"] = round(max(0.0, time.time() - started), 3)
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        if error_text:
            entry.update({"status": "exception", "error": error_text[:1_000]})
            return

        artifact = getattr(result, "artifact", None)
        artifact = artifact if isinstance(artifact, dict) else {}
        entry["status"] = str(artifact.get("status") or getattr(result, "status", None) or "completed")
        entry["blocked_by"] = blocked_by
        entry["persisted"] = bool(artifact.get("persisted", False))
        entry["data_ref"] = artifact.get("data_ref")
        entry["artifact_refs"] = list(artifact.get("artifact_refs") or [])
        entry["provenance"] = _safe_trace_args(dict(artifact.get("provenance") or {}))
        entry["metrics"] = _safe_trace_args(dict(artifact.get("metrics") or {}))
        content = str(getattr(result, "content", "") or "")
        entry["result_preview"] = content[:500]


def _approx_tokens(messages) -> int:
    """Fast, stable token estimate used by trimming and its audit."""
    return count_tokens_approximately(messages)


_CODE_RETRY_TOOL_NAMES = frozenset({"run_pandas", "run_graph"})


def _has_dependency_recovery(artifact: object) -> bool:
    """Return whether a tool failure needs another tool, not the same code."""
    if not isinstance(artifact, dict):
        return False
    metrics = artifact.get("metrics")
    return bool(
        isinstance(metrics, dict)
        and metrics.get("dependency_recovery") is True
    )


def _dependency_recovery_plan(messages: Sequence) -> tuple[str, str, dict] | None:
    """Describe the latest missing-data dependency that needs tool recovery."""
    last_human_index = max(
        (index for index, message in enumerate(messages)
         if isinstance(message, HumanMessage)),
        default=-1,
    )
    current_turn = list(messages[last_human_index + 1:])
    dependency_errors = [
        message
        for message in current_turn
        if isinstance(message, ToolMessage)
        and _has_dependency_recovery(message.artifact)
    ]
    if len(dependency_errors) != 1 or not current_turn:
        return None
    failed = dependency_errors[0]
    if current_turn[-1] is not failed:
        return None
    artifact = failed.artifact if isinstance(failed.artifact, dict) else {}
    metrics = artifact.get("metrics")
    if not isinstance(metrics, dict):
        return None
    diagnostic = str(failed.content or "").strip()
    if not diagnostic:
        return None
    return str(failed.name or "tool"), diagnostic, metrics


def _code_retry_plan(messages: Sequence) -> tuple[str, str] | None:
    """Return the one permitted deterministic repair for local execution.

    The agent may repair one retryable failed/empty local execution per user
    turn. The failed ``ToolMessage`` stays in the model history and its full
    diagnostic is also injected into the forced retry instruction. A second
    failed execution ends the retry budget and lets the model report its final
    diagnostic normally.
    """
    last_human_index = max(
        (index for index, message in enumerate(messages)
         if isinstance(message, HumanMessage)),
        default=-1,
    )
    current_turn = list(messages[last_human_index + 1:])
    code_errors = [
        message
        for message in current_turn
        if isinstance(message, ToolMessage)
        and message.name in _CODE_RETRY_TOOL_NAMES
        and isinstance(message.artifact, dict)
        and message.artifact.get("status") in {"error", "empty"}
        and message.artifact.get("retryable") is True
        and not _has_dependency_recovery(message.artifact)
    ]
    if len(code_errors) != 1 or not current_turn or current_turn[-1] is not code_errors[0]:
        return None
    failed = code_errors[0]
    diagnostic = str(failed.content or "").strip()
    if not diagnostic:
        return None
    return str(failed.name), diagnostic


def _compact_old_tool_results(
    messages,
    *,
    keep_turns: int = _KEEP_FULL_TOOL_TURNS,
    max_total_chars: int | None = None,
):
    """Replace stale tool payloads while preserving recent conversational turns.

    Two-pass strategy:
    1. First pass: compact every tool result older than ``keep_turns`` human turns.
    2. Second pass (when ``max_total_chars`` is set): if total tool-result chars
       still exceeds the budget, compact the oldest eligible messages in the recent
       window — never the current turn (messages after the last HumanMessage).
    """
    human_indexes = [
        index for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
    ]
    keep_turns = max(1, int(keep_turns))
    # `cutoff` is the index of the first message in the "keep full" window; tool
    # results BEFORE it are compacted. With few turns (≤ keep_turns) nothing is
    # old yet, so cutoff must be 0 — compact nothing. Using len(messages) here
    # would instead compact every tool result, including the CURRENT turn's,
    # leaving the model only a 240-char prefix and making it hallucinate the rest.
    cutoff = (
        human_indexes[-keep_turns]
        if len(human_indexes) > keep_turns
        else 0
    )
    output: list = []
    metrics = {
        "old_tool_messages_compacted": 0,
        "old_tool_result_chars_before": 0,
        "old_tool_result_chars_after": 0,
        "old_tool_result_chars_saved": 0,
    }

    def _record_compaction(before: int, compact: str) -> None:
        metrics["old_tool_messages_compacted"] += 1
        metrics["old_tool_result_chars_before"] += before
        metrics["old_tool_result_chars_after"] += len(compact)

    def _semantic_tool_summary(message, *, reason: str, limit: int = 1200) -> str:
        """Keep durable facts rather than an arbitrary leading excerpt."""
        raw = str(message.content or "")
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        lines = [line for line in lines if line]
        signals = (
            "status", "résultat", "result", "error", "erreur", "failed",
            "blocked", "warning", "variable", "persist", "selection",
            "export", "project", "sample", "rows", "lignes", "coverage",
            "couverture", "ctd", "limit", "limite",
        )
        chosen: list[str] = []

        def add(line: str) -> None:
            line = line[:260]
            if line and line not in chosen:
                chosen.append(line)

        for line in lines[:3]:
            add(line)
        for line in lines:
            if any(marker in line.lower() for marker in signals):
                add(line)
            if len(chosen) >= 12:
                break
        for line in lines[-2:]:
            add(line)

        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        facts: list[str] = []
        for key in ("status", "persisted", "data_ref"):
            value = artifact.get(key)
            if value not in (None, "", [], {}):
                facts.append(f"{key}={value}")
        metrics_data = artifact.get("metrics")
        if isinstance(metrics_data, dict):
            for key in ("rows", "columns", "samples", "projects"):
                value = metrics_data.get(key)
                if value not in (None, "", [], {}):
                    facts.append(f"{key}={value}")
        fact_text = ("; ".join(facts))[:320]
        body = "\n".join(f"- {line}" for line in chosen)
        compact = (
            f"[Résultat compacté — tool={message.name or 'unknown'}; {reason}]"
            + (f"\nFaits: {fact_text}" if fact_text else "")
            + (f"\n{body}" if body else "")
        )
        return compact[:limit]

    # ── First pass: compact by turn-age ───────────────────────────────────────
    for index, message in enumerate(messages):
        if not (
            isinstance(message, ToolMessage)
            and isinstance(message.content, str)
            and len(message.content) > 320
        ):
            output.append(message)
            continue

        if index < cutoff:
            compact = _semantic_tool_summary(
                message, reason="hors fenêtre récente"
            )
            _record_compaction(len(message.content), compact)
            output.append(message.model_copy(update={"content": compact}))
        else:
            output.append(message)

    # ── Second pass: total-chars budget ───────────────────────────────────────
    # Applied even when keep_turns kept many messages full: if the aggregate
    # size still exceeds the budget, compact oldest eligible messages from the
    # recent window — but NEVER the current turn (after the last HumanMessage).
    if max_total_chars is not None and max_total_chars > 0:
        last_human_idx = max(
            (i for i, m in enumerate(output) if isinstance(m, HumanMessage)),
            default=len(output),
        )
        total_chars = sum(
            len(m.content)
            for m in output
            if isinstance(m, ToolMessage) and isinstance(m.content, str)
        )
        if total_chars > max_total_chars:
            for i in range(len(output)):
                if total_chars <= max_total_chars:
                    break
                if i >= last_human_idx:
                    break
                m = output[i]
                if not (isinstance(m, ToolMessage) and isinstance(m.content, str)):
                    continue
                if len(m.content) <= 320:
                    continue  # Already compacted or inherently short
                before = len(m.content)
                compact = _semantic_tool_summary(
                    m, reason="budget global", limit=700
                )
                output[i] = m.model_copy(update={"content": compact})
                total_chars -= before - len(compact)
                _record_compaction(before, compact)

    metrics["old_tool_result_chars_saved"] = (
        metrics["old_tool_result_chars_before"]
        - metrics["old_tool_result_chars_after"]
    )
    return output, metrics


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
            if item.get("type") == "namespace":
                # OpenAI hosted Tool Search receives the full index, but the
                # model's initial context contains only the namespace identity.
                # Deferred member schemas are appended after a search result and
                # must not evict useful history before they are selected.
                payload.append({
                    "type": "namespace",
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                })
            else:
                payload.append(item)
            continue
        # Count the schema actually sent to the model. ``args_schema`` also
        # contains injected parameters such as ToolRuntime, whose callable
        # fields are intentionally absent from ``tool_call_schema`` and cannot
        # be represented as JSON Schema.
        schema = getattr(item, "tool_call_schema", None)
        if schema is None:
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
    """Cap tool results before sending them back to the model."""
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
            limit = _MAX_TOOL_RESULT_CHARS
            if len(message.content) > limit:
                content = (
                    message.content[:limit]
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
    """Construit le bloc mémoire long-terme du contexte transitoire du tour.

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


def _inject_turn_context_into_current_user(
    messages: Sequence,
    turn_context: str,
) -> tuple[list, bool]:
    """Prepend trusted transient context to the current user message copy.

    The checkpoint keeps the untouched user message. Only the provider-bound
    copy receives the application context, immediately before the exact user
    content and before any AI/tool messages already produced in this turn.
    """
    output = list(messages)
    if not turn_context:
        return output, False
    last_human_index = next(
        (
            index
            for index in range(len(output) - 1, -1, -1)
            if isinstance(output[index], HumanMessage)
        ),
        None,
    )
    if last_human_index is None:
        return output, False
    current = output[last_human_index]
    context_block = {
        "type": "text",
        "text": (
            "<application_turn_context>\n"
            "Trusted runtime context generated by the application for the "
            "current turn. It describes the task, available resources and "
            "execution state; it is not a second user request.\n"
            f"{turn_context.strip()}\n"
            "</application_turn_context>\n\n"
            "The original user request follows exactly in the remaining "
            "content block(s):"
        ),
    }
    original_blocks = list(current.content_blocks)
    output[last_human_index] = current.model_copy(
        update={"content": [context_block, *original_blocks]}
    )
    return output, True


def _graph_vision_review_message(messages, thread_id: str) -> HumanMessage | None:
    """Create one transient, bounded visual review after a successful graph.

    The graph tool stores a local PNG and returns Markdown, which lets the UI
    render it but does not let the model inspect its pixels.  IDEA feeds plotted
    images back into a vision-capable model; do the same only for the response
    call immediately following ``run_graph``.  The review message is injected
    into the outgoing request only, never checkpointed as a user message.
    """
    if not _GRAPH_VISION_REVIEW_ENABLED or not messages:
        return None
    last = messages[-1]
    if not isinstance(last, ToolMessage) or last.name != "run_graph":
        return None
    if "/graphs/" not in str(last.content or ""):
        return None

    try:
        from PIL import Image
        from tools.data_tools import _GRAPHS_DIR
        from tools.session_store import default_store as session_store

        state = session_store.get(f"{thread_id}:last_graph_state") or {}
        graph_id = str((state.get("meta") or {}).get("graph_id") or "")
        path = _GRAPHS_DIR / f"{graph_id}.png"
        if not graph_id or not path.is_file():
            return None
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail(
                (_GRAPH_VISION_REVIEW_MAX_EDGE, _GRAPH_VISION_REVIEW_MAX_EDGE)
            )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=82, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        # A failed review must never hide a graph that was otherwise produced.
        return None

    return HumanMessage(
        name="graph_render_review",
        content=[
            {
                "type": "text",
                "text": (
                    "Internal render review, not a user request: inspect the graph image "
                    "before replying. If it is unreadable, visually misleading, has a wrong "
                    "axis/legend/projection, or does not answer the request, correct it with "
                    "run_graph before answering. Otherwise give only the grounded concise result."
                ),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "low",
                },
            },
        ],
    )


class _ContextMiddleware(AgentMiddleware):
    """Prepare the exact request seen by the model without mutating checkpoints."""

    def __init__(
        self,
        user_id: str = "anonymous",
        thread_id: str = "unknown",
        catalog_names=None,
    ):
        super().__init__()
        self.user_id = user_id
        self.thread_id = thread_id
        self.catalog_names = tuple(catalog_names or ())

    def _prepare_request(self, request, memories):
        original_messages = list(request.messages)
        exploration_payload = (
            (getattr(request, "state", None) or {}).get("exploration")
        )
        exploration_block = render_exploration_frontier(exploration_payload)
        checkpoint_recovery_tools = recovery_tool_names(
            (getattr(request, "state", None) or {}).get("exploration")
        )
        dependency_recovery = _dependency_recovery_plan(original_messages)
        code_retry = _code_retry_plan(original_messages)
        _begin_harness_turn(self.thread_id, original_messages)
        try:
            from tools.data_tools import reset_graph_block_on_new_turn
            from tools.session_store import default_store as session_store

            reset_graph_block_on_new_turn(
                session_store, self.thread_id, original_messages
            )
        except Exception:
            pass

        original_tokens = _approx_tokens(original_messages)
        compacted_messages, compact_metrics = _compact_old_tool_results(
            original_messages,
            max_total_chars=_MAX_TOTAL_TOOL_CHARS,
        )
        truncated_messages, truncate_metrics = _truncate_tool_results(
            compacted_messages
        )
        truncated_tokens = _approx_tokens(truncated_messages)

        block, metrics = _build_memory_block(memories)
        from tools.session_store import default_store as session_store
        from tools.turn_context import build_turn_context

        # Rendering quality, provenance and safety are enforced by run_graph;
        # graph planning/writing skills are deliberately outside the runtime.
        from tools.source_scope import source_decision_for_turn

        # Resolve the turn's preferred sources before projecting the resource
        # catalog. Reused below for tool exposure.
        source_decision = source_decision_for_turn(
            session_store, self.thread_id, original_messages
        )

        graph_reference_phase = "none"

        # Rebuild typed runtime state once. The active variable remains metadata
        # for the uniform resource catalog; it never determines catalog order.
        turn_ctx = build_turn_context(
            session_store, self.thread_id, original_messages, persist_source=False
        )
        task_block = render_task_context(
            exploration_payload,
            preferred_sources=source_decision.authorized_sources,
            primary_source=source_decision.primary_source,
        )
        dataset_block = render_dataframe_context(
            exploration_payload,
            active_variable=turn_ctx.active_variable,
        )
        from agents.domain_profiles import domain_profile_prompt

        domain_profile_block = domain_profile_prompt(turn_ctx.domain_profile)
        system_message = request.system_message
        base = system_message.content if system_message is not None else ""
        # Surface the last render's verified facts so the answer's `Données`
        # line reports real counts/encodings instead of fabricating them. Kept
        # in transient application context, never in the streamed tool output.
        graph_grounding_block = ""
        graph_edit_block = ""
        try:
            grounding = session_store.get(f"{self.thread_id}:last_graph_grounding")
            facts = ((grounding or {}).get("meta") or {}).get("facts")
            if facts:
                graph_grounding_block = (
                    "\n\nLAST GRAPH — verified rendering facts for the response's "
                    "data summary. Paraphrase these facts; never expose this "
                    f"internal label: {facts}"
                )
        except Exception:
            pass
        # The last graph code remains in normal short-term history. Do not
        # inject it on every turn merely to predict a graph edit.
        # Keep the permanent kernel byte-stable for prompt caching. Everything
        # that varies by user/thread/turn is composed separately and injected
        # into only the provider-bound copy of the current HumanMessage.
        static_reference_block = ""
        dynamic_context_block = (
            block
            + task_block
            + domain_profile_block
            + dataset_block
            + graph_grounding_block
            + graph_edit_block
            + exploration_block
        )
        if dependency_recovery is not None:
            failed_tool, diagnostic, recovery_metrics = dependency_recovery
            missing_names = ", ".join(
                f"`{name}`"
                for name in recovery_metrics.get("missing_names", [])
            ) or "the requested data"
            recovery_tools = ", ".join(
                f"`{name}`"
                for name in recovery_metrics.get("recovery_tools", [])
            ) or "the appropriate recovery tool"
            dynamic_context_block += (
                "\n\nDATA DEPENDENCY RECOVERY — REQUIRED NEXT ACTION\n"
                "Failure class: missing data dependency.\n"
                f"Failed tool: `{failed_tool}`.\n"
                f"Missing data: {missing_names}.\n"
                f"Diagnostic: {diagnostic[:4_000]}\n"
                f"Allowed recovery tools: {recovery_tools}.\n"
                "Recovery protocol:\n"
                "1. Do not repeat the failed code unchanged.\n"
                "2. Inspect the relevant schema or retrieve the missing table or "
                "column with one of the allowed recovery tools.\n"
                "3. Use the exact persisted DataFrame returned by that operation.\n"
                "4. Rerun the blocked local analysis with the original user scope, "
                "grain, filters and requested output unchanged.\n"
                "5. Continue through the requested deliverable before answering.\n"
                "Do not ask the user for data that is available through the listed "
                "resources. Do not substitute a different metric or silently weaken "
                "the scope.\n"
                "Completion condition: the missing dependency is present, the failed "
                "analytical step has succeeded, and its result is recorded as evidence."
            )
        elif checkpoint_recovery_tools:
            dynamic_context_block += (
                "\n\nDATA DEPENDENCY RECOVERY — CHECKPOINT CONTINUATION\n"
                "Failure class: unresolved data dependency from an earlier ReAct step.\n"
                "The exploration checkpoint records a missing table or column that "
                "still blocks the requested deliverable.\n"
                "Recovery protocol:\n"
                "1. Read the active dependency in EXPLORATION FRONTIER.\n"
                "2. Inspect or retrieve it from the available resources; do not ask "
                "the user when the application can access it.\n"
                "3. Reuse the exact persisted result and rerun the blocked analytical "
                "step.\n"
                "4. Preserve the original scope, grain, filters and requested output.\n"
                "5. Continue until the dependency is satisfied and the deliverable is "
                "complete.\n"
                "Do not restart completed steps, repeat identical calls, substitute "
                "another metric or stop after retrieval.\n"
                "Completion condition: EXPLORATION FRONTIER no longer contains an "
                "active data dependency and the resumed analytical step has successful "
                "evidence."
            )
        elif code_retry is not None:
            retry_tool, diagnostic = code_retry
            dynamic_context_block += (
                "\n\nDETERMINISTIC CODE RETRY — ONE ATTEMPT ONLY\n"
                "Failure class: retryable local code execution.\n"
                f"Failed tool: `{retry_tool}`.\n"
                f"Diagnostic:\n{diagnostic[:4_000]}\n"
                "Retry protocol:\n"
                "1. Identify the exact syntax, variable, dtype, column or plotting "
                "error described by the diagnostic.\n"
                "2. Issue exactly one corrected call to the same tool.\n"
                "3. Keep the same DataFrame scope, grain, filters and analytical "
                "intent; do not switch sources or weaken the request.\n"
                "4. Do not answer the user before the corrected call returns.\n"
                "5. If the corrected call also fails, stop retrying and report that "
                "final diagnostic accurately.\n"
                "Completion condition: the corrected call succeeds once, or the single "
                "retry budget is exhausted and the second failure is reported."
            )
        injected_context = static_reference_block + dynamic_context_block
        base_system_tokens = (
            _approx_tokens([SystemMessage(content=base)]) if base else 0
        )
        runtime_context_tokens = (
            _approx_tokens([HumanMessage(content=injected_context)])
            if injected_context
            else 0
        )
        # Build the provider-facing tool surface before pricing schemas or
        # assigning the remaining history budget. With OpenAI Tool Search the
        # provider sees compact namespaces and loads specialized schemas on
        # demand; the LangGraph ToolNode still owns every executable BaseTool.
        from tools.openai_tool_search import (
            build_openai_tool_search_projection,
            openai_tool_search_enabled,
        )
        from tools.tool_catalog import TOOL_POLICIES
        from tools.tool_exposure import decide_tool_exposure

        original_tools = list(request.tools)
        scoped_tools = original_tools
        exposure_decision = decide_tool_exposure(
            [getattr(item, "name", "") for item in scoped_tools],
            TOOL_POLICIES,
            turn_ctx,
            source_decision,
            original_messages,
        )
        scoped_by_name = {
            getattr(item, "name", ""): item for item in scoped_tools
        }
        dependency_recovery_names = (
            dependency_recovery[2].get("recovery_tools", [])
            if dependency_recovery is not None
            else checkpoint_recovery_tools
        )
        forced_immediate_names = {
            str(name) for name in dependency_recovery_names
        }
        if code_retry is not None:
            forced_immediate_names.add(code_retry[0])

        tool_search_active = openai_tool_search_enabled()
        tool_search_projection = None
        if tool_search_active:
            tool_search_projection = build_openai_tool_search_projection(
                original_tools,
                TOOL_POLICIES,
                force_immediate=tuple(forced_immediate_names),
            )
            exposed_tools = list(tool_search_projection.provider_tools)
        else:
            exposed_tools = [
                scoped_by_name[name]
                for name in exposure_decision.tool_names
                if name in scoped_by_name
            ]
        retry_tool_choice = None
        if code_retry is not None:
            retry_tool = code_retry[0]
            retry_tool_instance = scoped_by_name.get(retry_tool)
            if retry_tool_instance is not None:
                if not tool_search_active and retry_tool_instance not in exposed_tools:
                    exposed_tools.append(retry_tool_instance)
                retry_tool_choice = {
                    "type": "function",
                    "function": {"name": retry_tool},
                }
        if dependency_recovery is not None or checkpoint_recovery_tools:
            for recovery_name in dependency_recovery_names:
                recovery_tool = scoped_by_name.get(str(recovery_name))
                if (
                    not tool_search_active
                    and recovery_tool is not None
                    and recovery_tool not in exposed_tools
                ):
                    exposed_tools.append(recovery_tool)
        effective_tool_names = (
            list(tool_search_projection.provider_surface_names)
            if tool_search_projection is not None
            else [getattr(item, "name", "") for item in exposed_tools]
        )
        tool_schema_tokens_before = _tool_schema_tokens(original_tools)
        tool_schema_tokens_after_source = _tool_schema_tokens(scoped_tools)
        tool_schema_tokens = _tool_schema_tokens(exposed_tools)
        history_budget = compute_history_budget(
            max_input_tokens=_MAX_CONTEXT_TOKENS,
            system_tokens=base_system_tokens,
            tool_tokens=tool_schema_tokens,
            memory_tokens=runtime_context_tokens,
            reserve_tokens=_CONTEXT_RESERVE_TOKENS,
        )
        trimmed_messages = _trim_request_messages(
            truncated_messages,
            max_tokens=history_budget,
        )
        final_tokens = _approx_tokens(trimmed_messages)
        prepared_system_message = system_message
        system_tokens = (
            _approx_tokens([prepared_system_message])
            if prepared_system_message is not None
            else 0
        )

        audit_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "messages_before": len(original_messages),
            "messages_after_tool_truncation": len(truncated_messages),
            "messages_after_old_tool_compaction": len(compacted_messages),
            "messages_after_trim": len(trimmed_messages),
            "messages_trimmed": max(
                0, len(truncated_messages) - len(trimmed_messages)
            ),
            "approx_tokens_before": original_tokens,
            "approx_tokens_after_tool_truncation": truncated_tokens,
            "approx_tokens_after_memory": (
                system_tokens + runtime_context_tokens + truncated_tokens
            ),
            "approx_tokens_after_trim": final_tokens,
            "approx_tokens_system_message": system_tokens,
            "approx_tokens_base_system": base_system_tokens,
            "approx_tokens_memory_and_capsule": runtime_context_tokens,
            "approx_tokens_runtime_context": runtime_context_tokens,
            "approx_tokens_tool_schemas": tool_schema_tokens,
            "approx_tokens_tool_schemas_before": tool_schema_tokens_before,
            "approx_tokens_tool_schemas_after_source": tool_schema_tokens_after_source,
            "approx_tokens_tool_schemas_after": tool_schema_tokens,
            "approx_tokens_tool_schemas_saved": max(
                0, tool_schema_tokens_before - tool_schema_tokens
            ),
            "history_budget_tokens": history_budget,
            "context_reserve_tokens": _CONTEXT_RESERVE_TOKENS,
            "approx_tokens_model_request": (
                base_system_tokens
                + runtime_context_tokens
                + tool_schema_tokens
                + final_tokens
            ),
            "total_estimated": (
                base_system_tokens
                + runtime_context_tokens
                + tool_schema_tokens
                + final_tokens
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
            **compact_metrics,
            "max_total_tool_result_chars": _MAX_TOTAL_TOOL_CHARS,
            **metrics,
            "dataset_capsule_injected": bool(dataset_block),
            "dataset_capsule_chars": len(dataset_block),
            "dataframe_context_injected": bool(dataset_block),
            "dataframe_context_chars": len(dataset_block),
            "task_context_injected": bool(task_block),
            "task_context_chars": len(task_block),
            "exploration_state_injected": bool(exploration_block),
            "exploration_state_chars": len(exploration_block),
            "runtime_context_injected": bool(injected_context),
            "runtime_context_chars": len(injected_context),
            "runtime_context_position": "current_user_prefix",
            "dynamic_context_in_system": False,
            "turn_active_variable": turn_ctx.active_variable,
            "turn_domain_profile": turn_ctx.domain_profile,
            "turn_authorized_sources": list(turn_ctx.authorized_sources),
            "turn_derived_subsets": len(turn_ctx.derived_zone_subsets),
            "turn_output_intent": "agent_decides",
            "turn_output_intent_confidence": "not_applicable",
            "preseeded_graph_skills": [],
            "preseeded_source_skills": [],
            "graph_reference_phase": graph_reference_phase,
            "graph_reference_chars": 0,
            "source_reference_chars": 0,
            "neolabs_reference_chars": 0,
            "fish_larvae_reference_chars": 0,
            "static_reference_chars": len(static_reference_block),
            "dynamic_context_chars": len(dynamic_context_block),
            "tools_before_policy": [
                getattr(item, "name", "") for item in original_tools
            ],
            "tools_after_source_scope": [
                getattr(item, "name", "") for item in scoped_tools
            ],
            "tools_exposed": effective_tool_names,
            "tool_exposure_count": len(effective_tool_names),
            "tool_exposure_alert": len(effective_tool_names) >= 12,
            "tool_exposure_groups": list(exposure_decision.active_groups),
            "tool_exposure_reasons": list(exposure_decision.reasons),
            "tools_dropped": list(exposure_decision.dropped_tool_names),
            "policy_overflow": exposure_decision.policy_overflow,
            "openai_tool_search_enabled": tool_search_active,
            "openai_tool_search_immediate": (
                list(tool_search_projection.immediate_names)
                if tool_search_projection is not None
                else []
            ),
            "openai_tool_search_namespaces": (
                {
                    namespace.name: list(namespace.member_names)
                    for namespace in tool_search_projection.namespaces
                }
                if tool_search_projection is not None
                else {}
            ),
            "openai_tool_search_searchable_members": (
                list(tool_search_projection.searchable_member_names)
                if tool_search_projection is not None
                else []
            ),
            "openai_tool_search_excluded": (
                list(tool_search_projection.excluded_names)
                if tool_search_projection is not None
                else []
            ),
            "code_retry_forced_tool": code_retry[0] if code_retry else None,
            "dependency_recovery": bool(dependency_recovery),
            "dependency_recovery_tools": (
                list(dependency_recovery[2].get("recovery_tools", []))
                if dependency_recovery is not None else []
            ),
            "checkpoint_dependency_recovery_tools": list(checkpoint_recovery_tools),
        }
        _context_audit_by_thread[self.thread_id] = audit_entry
        _append_harness_model_call(self.thread_id, audit_entry)
        try:
            # This is deliberately appended only to the provider request.  It
            # must not become a fabricated persistent HumanMessage in the
            # checkpoint, nor inflate the text-history budget with base64.
            contextualized_messages, context_injected = (
                _inject_turn_context_into_current_user(
                    trimmed_messages,
                    injected_context,
                )
            )
            _context_audit_by_thread[self.thread_id][
                "runtime_context_injected"
            ] = context_injected
            graph_vision_review = _graph_vision_review_message(
                trimmed_messages, self.thread_id
            )
            outgoing_messages = (
                [*contextualized_messages, graph_vision_review]
                if graph_vision_review is not None
                else contextualized_messages
            )
            _context_audit_by_thread[self.thread_id]["graph_vision_review"] = bool(
                graph_vision_review
            )
            overrides = {
                "messages": outgoing_messages,
                "system_message": prepared_system_message,
                "tools": exposed_tools,
            }
            if retry_tool_choice is not None:
                overrides["tool_choice"] = retry_tool_choice
            prepared = request.override(
                **overrides,
            )
            _context_audit_by_thread[self.thread_id][
                "tool_filter_override_supported"
            ] = True
            return prepared
        except TypeError:
            # request.override may not accept tools on this build; the
            # wrap_tool_call guard still enforces the scope hard.
            _context_audit_by_thread[self.thread_id][
                "tool_filter_override_supported"
            ] = False
            fallback_overrides = {
                "messages": outgoing_messages,
                "system_message": prepared_system_message,
            }
            if retry_tool_choice is not None:
                fallback_overrides["tool_choice"] = retry_tool_choice
            return request.override(**fallback_overrides)

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

    def wrap_tool_call(self, request, handler):
        trace_id = _start_harness_tool_call(self.thread_id, request.tool_call)
        rejection = self._tool_identifier_rejection(request)
        if rejection:
            result = self._blocked_tool_message(request, rejection)
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="source_policy")
            return result
        try:
            result = handler(request)
        except Exception as exc:
            _finish_harness_tool_call(self.thread_id, trace_id, error_text=str(exc))
            raise
        _finish_harness_tool_call(self.thread_id, trace_id, result)
        return result

    async def awrap_tool_call(self, request, handler):
        trace_id = _start_harness_tool_call(self.thread_id, request.tool_call)
        rejection = self._tool_identifier_rejection(request)
        if rejection:
            result = self._blocked_tool_message(request, rejection)
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="source_policy")
            return result
        try:
            result = await handler(request)
        except Exception as exc:
            _finish_harness_tool_call(self.thread_id, trace_id, error_text=str(exc))
            raise
        _finish_harness_tool_call(self.thread_id, trace_id, result)
        return result

    def wrap_model_call(self, request, handler):
        store = getattr(request.runtime, "store", None)
        memories = []
        if store is not None:
            try:
                memories = store.search((self.user_id, "memories"))
            except Exception:
                memories = []
        response = handler(self._prepare_request(request, memories))
        return _wait_for_rag_response(response)

    async def awrap_model_call(self, request, handler):
        store = getattr(request.runtime, "store", None)
        memories = []
        if store is not None:
            try:
                memories = await store.asearch((self.user_id, "memories"))
            except Exception:
                memories = []
        response = await handler(self._prepare_request(request, memories))
        return _wait_for_rag_response(response)


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
    from tools.openai_tool_search import openai_tool_search_enabled

    tool_search_active = openai_tool_search_enabled()
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "gpt-5.6-luna"),
        max_retries=2,
        max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "16000")),
        use_responses_api=tool_search_active,
        **chat_openai_connection_kwargs(),
    )
    catalog = build_tool_catalog(thread_id)
    return create_agent(
        llm,
        list(catalog.tools),
        system_prompt=_SYSTEM_PROMPT,
        middleware=[
            ModelCallLimitMiddleware(
                run_limit=_MAX_MODEL_CALLS_PER_TURN,
                exit_behavior="end",
            ),
            ExplorationStateMiddleware(thread_id=thread_id),
            _ContextMiddleware(
                user_id=user_id,
                thread_id=thread_id,
                catalog_names=catalog.names,
            )
        ],
        state_schema=IdeaAgentState,
        checkpointer=_checkpointer,
        store=_store,
    )


def _make_tracer(thread_id: str, user_id: str = "anonymous", user_email: str | None = None) -> LangChainTracer | None:
    """Retourne un LangChainTracer si LANGCHAIN_TRACING_V2 est activé."""
    if os.getenv("LANGCHAIN_TRACING_V2", "false").lower() != "true":
        return None
    project = os.getenv("LANGCHAIN_PROJECT", "copepod-agent")
    tags = ["copepod", thread_id[:8], f"user_id:{user_id}", f"user:{user_email or user_id}"]
    if user_email:
        tags.append(f"user_email:{user_email}")
    return LangChainTracer(project_name=project, tags=tags)


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
