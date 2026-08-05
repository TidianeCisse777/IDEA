"""Agent factory + CLI copépodes (slices 4-5)."""
import asyncio
import copy
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
from langchain.agents.middleware import AgentMiddleware

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
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
# Raw ReAct history is useful only for the immediately preceding work.  Older
# user choices are carried separately below, while dataset/source/graph facts
# are restored from the persisted session state.  This is deliberately below
# the quality ceiling so a long conversation cannot consume it by itself.
_MAX_HISTORY_TOKENS = int(os.getenv("MAX_HISTORY_TOKENS", "16000"))
# Tool results over this many chars get truncated before being sent to the LLM
_MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "8000"))
# A manifest may budget a substantial skill, but it must not override the
# context safety ceiling.  A single 40k-character skill body repeatedly fed to
# a ReAct loop is enough to drown out both the user request and tool results.
_MAX_SKILL_RESULT_CHARS = int(os.getenv("MAX_SKILL_RESULT_CHARS", "12000"))
_KEEP_FULL_TOOL_TURNS = int(os.getenv("KEEP_FULL_TOOL_TURNS", "1"))
# Second-pass budget: if total tool-result chars after first compaction exceeds
# this, oldest eligible messages are compacted further (never the current turn).
_MAX_TOTAL_TOOL_CHARS = int(os.getenv("MAX_TOTAL_TOOL_RESULT_CHARS", "16000"))
_MAX_STALE_TOOL_RESULT_CHARS = 700
_context_audit_by_thread: dict[str, dict] = {}
_harness_trace_by_thread: dict[str, dict] = {}
_harness_trace_lock = threading.Lock()


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


def _code_retry_plan(messages: Sequence) -> tuple[str, str] | None:
    """Return the one permitted deterministic retry for local code execution.

    The agent may repair one retryable code failure per user turn.  The failed
    ``ToolMessage`` stays in the model history and its full diagnostic is also
    injected into the forced retry instruction.  A second code failure ends the
    retry budget and lets the model report its final diagnostic normally.
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
        and message.artifact.get("status") == "error"
        and message.artifact.get("retryable") is True
    ]
    if len(code_errors) != 1 or not current_turn or current_turn[-1] is not code_errors[0]:
        return None
    failed = code_errors[0]
    diagnostic = str(failed.content or "").strip()
    if not diagnostic:
        return None
    return str(failed.name), diagnostic


def _render_net_uvp_progress_context(progress) -> str:
    """Return one human-facing Filet–UVP readiness line for the model.

    Persisted variable names and implementation handles are deliberately not
    projected here: the model only needs the scientific workflow readiness.
    """
    if progress.phase == "no_file":
        return ""
    exploratory_notice = (
        " Cette chaîne reste exploratoire et exige un accord explicite."
        if progress.ctd_status == "unavailable"
        else ""
    )
    if progress.phase == "needs_subset":
        return (
            "\n\nComparaison filet–UVP : table filet disponible; "
            "préparer le sous-ensemble d’audit avant la vérification UVP."
            + exploratory_notice
        )
    if progress.phase == "needs_audit":
        return (
            "\n\nComparaison filet–UVP : sous-ensemble d’audit disponible; "
            "la vérification UVP reste à effectuer."
            + exploratory_notice
        )
    if progress.phase == "audited":
        if progress.ctd_status == "unavailable":
            return (
                "\n\nComparaison filet–UVP : audit disponible, mais la "
                "vérification CTD est indisponible; toute suite est exploratoire "
                "et exige un accord explicite."
            )
        if progress.ctd_status == "no_match":
            return (
                "\n\nComparaison filet–UVP : audit disponible, sans "
                "correspondance CTD certifiée; ne pas présenter de comparaison "
                "d’abondance comme validée."
            )
        if progress.ctd_status != "verified":
            return (
                "\n\nComparaison filet–UVP : audit disponible, mais le statut "
                "CTD reste à confirmer; ne pas présenter de comparaison "
                "d’abondance comme validée."
            )
        return (
            "\n\nComparaison filet–UVP : audit certifié disponible; les actions "
            "d’analyse, de graphique et de préparation d’export restent possibles. "
            "La comparaison d’abondance attend encore l’export UVP puis les volumes EcoPart."
        )
    if progress.phase == "exported":
        return (
            "\n\nComparaison filet–UVP : export UVP disponible; l’enrichissement "
            "par les volumes EcoPart reste à préparer avant la comparaison d’abondance."
            + exploratory_notice
        )
    if progress.phase == "enriched":
        return (
            "\n\nComparaison filet–UVP : données UVP enrichies disponibles; "
            "la comparaison finale par strate de profondeur peut continuer."
            + exploratory_notice
        )
    return (
        "\n\nComparaison filet–UVP : comparaison finale disponible; analyses, "
        "graphiques et export restent possibles."
        + exploratory_notice
    )


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
    # A skill's full body is expensive and re-loaded per turn when needed
    # (exposure gates on the current turn; the run_graph execution guard reads
    # the session record, not this message). So keep only the LATEST load of each
    # skill full: earlier duplicates are dead weight, and a load outside the
    # recent window is stale. Both compact to a short reference.
    def _skill_name(message) -> str | None:
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        provenance = artifact.get("provenance")
        if isinstance(provenance, dict):
            skill = provenance.get("skill")
            return str(skill) if skill else None
        return None

    latest_skill_index: dict[str, int] = {}
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage) and message.name == "load_skill":
            skill = _skill_name(message)
            if skill:
                latest_skill_index[skill] = index

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

    def _semantic_tool_summary(
        message,
        *,
        reason: str,
        limit: int = _MAX_STALE_TOOL_RESULT_CHARS,
    ) -> str:
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

        if message.name == "load_skill":
            skill = _skill_name(message)
            superseded = skill is not None and latest_skill_index.get(skill) != index
            stale = index < cutoff
            if superseded or stale:
                reason = "déjà rechargé plus tard" if superseded else "hors fenêtre récente"
                compact = (
                    f"[Skill {skill or 'inconnu'} compacté — {reason} ; "
                    "recharger avec load_skill si besoin]"
                )
                _record_compaction(len(message.content), compact)
                output.append(message.model_copy(update={"content": compact}))
            else:
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
                    m, reason="budget global", limit=480
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
    """Cap tool results, including manifest-validated skill bodies."""
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
            artifact = message.artifact if isinstance(message.artifact, dict) else {}
            provenance = artifact.get("provenance")
            if (
                message.name == "load_skill"
                and artifact.get("status") == "success"
                and artifact.get("method") == "skill loader"
                and isinstance(provenance, dict)
                and isinstance(provenance.get("max_tokens"), int)
            ):
                declared_tokens = min(12_000, max(1, provenance["max_tokens"]))
                limit = max(
                    limit,
                    min(_MAX_SKILL_RESULT_CHARS, declared_tokens * 4),
                )
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


def _graph_reference_phase(
    messages,
    *,
    active_variable: str | None,
    has_graph_edit: bool,
) -> str:
    """Choose the full graph skill needed for the current ReAct phase.

    The skill text is authoritative and must not be summarised away.  The
    phase selector merely stops planner and writer manuals from being repeated
    together after a graph has already been rendered.
    """
    last_human = max(
        (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
        default=-1,
    )
    current_tools = [
        message for message in messages[last_human + 1:]
        if isinstance(message, ToolMessage)
    ]

    graph_results = [message for message in current_tools if message.name == "run_graph"]
    if graph_results:
        latest = graph_results[-1]
        artifact = latest.artifact if isinstance(latest.artifact, dict) else {}
        if artifact.get("status") == "success":
            return "none"
        return "writer"

    if any(message.name == "run_pandas" for message in current_tools):
        return "writer"
    if has_graph_edit or active_variable == "df_graph_plot":
        return "writer"
    return "planner"


def _message_text_content(message) -> str:
    """Return the textual portion of a LangChain message without inventing it."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for part in content:
            if isinstance(part, str):
                fragments.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                fragments.append(part["text"])
        return "\n".join(fragments)
    return str(content or "")


def _build_prior_user_instruction_ledger(messages) -> tuple[str, dict]:
    """Preserve prior user choices when raw history is capped.

    This is a deterministic, verbatim projection of older HumanMessages, not
    an LLM-generated summary.  The active dataset, source scope and graph
    facts stay in their dedicated persisted capsules; this ledger covers the
    remaining user directives.  The current user message remains in normal
    history, so it is never duplicated and always takes precedence.
    """
    human_messages = [
        message for message in messages if isinstance(message, HumanMessage)
    ]
    prior_messages = human_messages[:-1]
    entries = [
        _message_text_content(message).strip()
        for message in prior_messages
    ]
    entries = [entry for entry in entries if entry]
    if not entries:
        return "", {
            "prior_user_instruction_count": 0,
            "prior_user_instruction_chars": 0,
            "prior_user_instruction_injected": False,
        }

    rendered_entries = "\n".join(
        f"{index}. {entry}" for index, entry in enumerate(entries, start=1)
    )
    block = (
        "\n\n## PRIOR USER INSTRUCTIONS (verbatim)\n"
        "Use these as continuity only. Later entries and the current user "
        "message override earlier ones.\n"
        f"{rendered_entries}"
    )
    return block, {
        "prior_user_instruction_count": len(entries),
        "prior_user_instruction_chars": len(block),
        "prior_user_instruction_injected": True,
    }


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
        catalog_names=None,
    ):
        super().__init__()
        self.user_id = user_id
        self.thread_id = thread_id
        self.output_intent_classifier = output_intent_classifier
        self.catalog_names = tuple(catalog_names or ())
        self._output_intent_cache = {}
        self._output_intent_classifier_calls = {}
        self._output_intent_sync_lock = threading.Lock()
        self._output_intent_async_lock = asyncio.Lock()

    def _prepare_request(self, request, memories):
        original_messages = list(request.messages)
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

        # Resolve output format before exposing tools.  A visual request must
        # expose the graph workflow on its first model call; waiting for a
        # graph skill to be loaded first makes the workflow impossible.
        output_intent = self._output_intent_decision(original_messages)

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
        from dataclasses import replace

        # A visual turn always ends in run_graph, whose Cartopy/matplotlib
        # contracts live in graph_planner + graph_writer. Both are represented
        # by static runtime capsules, so seeding them here — before the capsule
        # is projected — lets the model render directly instead of spending one
        # model round-trip per skill on load_skill. run_graph already self-heals
        # the same capsule, so this only removes latency, never changes output.
        from tools.skill_tool import preseed_capsule_skills
        from tools.source_scope import source_decision_for_turn

        # Resolve the turn's authorized sources up front so a source-procedure
        # skill can be pre-activated before the capsule is projected (same
        # round-trip saving as graph skills). Reused below for tool scoping.
        source_decision = source_decision_for_turn(
            session_store, self.thread_id, original_messages
        )

        preseeded_graph_skills: list[str] = []
        graph_reference_block = ""
        graph_reference_phase = "none"
        visual_turn = output_intent.intent == "visual" and os.getenv(
            "DISABLE_GRAPH_PRESEED", ""
        ).lower() not in ("1", "true", "yes")
        if visual_turn:
            preseeded_graph_skills = preseed_capsule_skills(
                session_store, self.thread_id, ("graph_planner", "graph_writer")
            )

        # EcoTaxa's read procedure lives in ecotaxa_navigation, whose full rules
        # are captured by a runtime capsule. When EcoTaxa is authorized this turn,
        # pre-activate it so the model queries the cache directly instead of
        # spending a load_skill round-trip first (the cache query itself is ~0.1ms).
        preseeded_source_skills: list[str] = []
        source_reference_block = ""
        active_before_context = session_store.get(self.thread_id) or {}
        active_profile = ((active_before_context.get("meta") or {}).get("domain_profile") or {}).get("name")
        if active_profile != "fish_larvae" and "ecotaxa" in source_decision.authorized_sources and os.getenv(
            "DISABLE_SOURCE_PRESEED", ""
        ).lower() not in ("1", "true", "yes"):
            from tools.skill_tool import source_navigation_reference

            preseeded_source_skills = preseed_capsule_skills(
                session_store, self.thread_id, ("ecotaxa_navigation",)
            )
            # Inject the full reviewed ecotaxa_navigation body (not just the
            # capsule), same rationale as the graph templates.
            source_reference_block = source_navigation_reference(
                ("ecotaxa_navigation",)
            )

        # Pre-activate the NeoLabs analysis skill when a NeoLabs abundance file is
        # the active dataset. The model does not reliably load_skill it, and this
        # file's column traps (aggregate double-counting, single-stratum
        # "profiles") otherwise produce wrong numbers.
        neolabs_reference_block = ""
        if os.getenv("DISABLE_SOURCE_PRESEED", "").lower() not in (
            "1", "true", "yes"
        ):
            try:
                from tools.data_tools import _is_neolabs_columns

                active = session_store.get(self.thread_id) or {}
                active_df = active.get("df")
                if active_df is not None and _is_neolabs_columns(active_df.columns):
                    from tools.skill_tool import dataset_analysis_reference

                    neolabs_reference_block = dataset_analysis_reference(
                        ("neolabs_abundance_analysis",)
                    )
            except Exception:
                pass

        # Do not inject a runtime capsule when the same skill's complete,
        # authoritative reference is already injected for this request. The
        # persisted capsule remains intact for later turns where no full guide
        # is needed; this only removes duplicated prompt text.
        excluded_capsule_skills: set[str] = set()
        if visual_turn:
            excluded_capsule_skills.update(("graph_planner", "graph_writer"))
        if source_reference_block:
            excluded_capsule_skills.add("ecotaxa_navigation")

        # Rebuild the typed turn state once; the model-facing capsule (active
        # dataset, live zone subsets, authorized source scope) is its projection.
        turn_ctx = build_turn_context(
            session_store,
            self.thread_id,
            original_messages,
            persist_source=False,
            exclude_skill_names=excluded_capsule_skills,
        )
        # Keep the decision local to this model request as well as persisted in
        # session metadata. This avoids a race with a store reload and makes
        # first-call visual exposure independent of an active dataframe.
        turn_ctx = replace(turn_ctx, output_intent=output_intent.intent)
        dataset_block = turn_ctx.capsule
        from agents.domain_profiles import domain_profile_prompt

        domain_profile_block = domain_profile_prompt(turn_ctx.domain_profile)
        fish_larvae_reference_block = ""
        if turn_ctx.domain_profile == "fish_larvae":
            from tools.skill_tool import dataset_analysis_reference

            fish_larvae_reference_block = dataset_analysis_reference(
                ("fish_larvae_analysis",)
            )
        system_message = request.system_message
        base = system_message.content if system_message is not None else ""
        # Surface the last render's verified facts so the answer's `Données`
        # line reports real counts/encodings instead of fabricating them. Kept
        # in the system context, never in the streamed tool output.
        graph_grounding_block = ""
        graph_edit_block = ""
        try:
            grounding = session_store.get(f"{self.thread_id}:last_graph_grounding")
            facts = ((grounding or {}).get("meta") or {}).get("facts")
            if facts:
                graph_grounding_block = (
                    "\n\nDERNIER GRAPHIQUE — faits vérifiés pour la ligne Données "
                    f"(reformuler, ne pas citer ce libellé) : {facts}"
                )
        except Exception:
            pass
        try:
            from tools.graph_state import graph_edit_reference

            if visual_turn:
                graph_edit_block = graph_edit_reference(session_store, self.thread_id)
        except Exception:
            pass
        if visual_turn:
            from tools.skill_tool import graph_planning_reference, graph_writing_reference

            graph_reference_phase = _graph_reference_phase(
                original_messages,
                active_variable=turn_ctx.active_variable,
                has_graph_edit=bool(graph_edit_block),
            )
            if graph_reference_phase == "planner":
                graph_reference_block = graph_planning_reference()
            elif graph_reference_phase == "writer":
                graph_reference_block = graph_writing_reference()
        net_uvp_progress_block = ""
        try:
            from tools.net_uvp_workflow import resolve_net_uvp_progress

            net_uvp_progress_block = _render_net_uvp_progress_context(
                resolve_net_uvp_progress(session_store, self.thread_id)
            )
        except Exception:
            # Workflow context is a convenience for recovery, never a reason
            # to prevent a regular request from reaching the model.
            pass

        # Cache-stable prefix first: the permanent kernel is already ``base``;
        # append every invariant reference before anything that can vary with a
        # user, a thread or a turn.  Exact-prefix prompt caches can then reuse
        # this whole block. Session memory, active tables and graph facts must
        # remain at the tail.
        static_reference_block = (
            graph_reference_block
            + source_reference_block
            + neolabs_reference_block
            + fish_larvae_reference_block
        )
        user_instruction_block, user_instruction_metrics = (
            _build_prior_user_instruction_ledger(original_messages)
        )
        dynamic_context_block = (
            block
            + user_instruction_block
            + dataset_block
            + domain_profile_block
            + graph_grounding_block
            + graph_edit_block
            + net_uvp_progress_block
        )
        if code_retry is not None:
            retry_tool, diagnostic = code_retry
            dynamic_context_block += (
                "\n\nDÉTERMINISTIC CODE RETRY — the immediately preceding "
                f"`{retry_tool}` call failed with this diagnostic:\n{diagnostic[:4_000]}"
                "\nIssue exactly one corrected call to that same tool now, "
                "using the same DataFrame scope. Do not answer the user before "
                "that call. A second code failure must be reported without another retry."
            )
        injected_context = static_reference_block + dynamic_context_block
        base_system_tokens = (
            _approx_tokens([SystemMessage(content=base)]) if base else 0
        )
        memory_tokens = (
            _approx_tokens([SystemMessage(content=injected_context)])
            if injected_context
            else 0
        )
        # Apply the deterministic source and exposure policies before pricing
        # tool schemas or assigning the remaining history budget.
        from tools.source_scope import filter_tools_for_decision
        from tools.tool_catalog import TOOL_POLICIES
        from tools.tool_exposure import decide_tool_exposure

        original_tools = list(request.tools)
        scoped_tools = filter_tools_for_decision(
            original_tools,
            source_decision,
            TOOL_POLICIES,
        )
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
                if retry_tool_instance not in exposed_tools:
                    exposed_tools.append(retry_tool_instance)
                retry_tool_choice = {
                    "type": "function",
                    "function": {"name": retry_tool},
                }
        tool_schema_tokens_before = _tool_schema_tokens(original_tools)
        tool_schema_tokens_after_source = _tool_schema_tokens(scoped_tools)
        tool_schema_tokens = _tool_schema_tokens(exposed_tools)
        available_history_budget = compute_history_budget(
            max_input_tokens=_MAX_CONTEXT_TOKENS,
            system_tokens=base_system_tokens,
            tool_tokens=tool_schema_tokens,
            memory_tokens=memory_tokens,
            reserve_tokens=_CONTEXT_RESERVE_TOKENS,
        )
        history_budget = min(_MAX_HISTORY_TOKENS, available_history_budget)
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
            "approx_tokens_after_memory": system_tokens + truncated_tokens,
            "approx_tokens_after_trim": final_tokens,
            "approx_tokens_system_message": system_tokens,
            "approx_tokens_base_system": base_system_tokens,
            "approx_tokens_memory_and_capsule": memory_tokens,
            "approx_tokens_tool_schemas": tool_schema_tokens,
            "approx_tokens_tool_schemas_before": tool_schema_tokens_before,
            "approx_tokens_tool_schemas_after_source": tool_schema_tokens_after_source,
            "approx_tokens_tool_schemas_after": tool_schema_tokens,
            "approx_tokens_tool_schemas_saved": max(
                0, tool_schema_tokens_before - tool_schema_tokens
            ),
            "history_budget_tokens": history_budget,
            "history_budget_available_tokens": available_history_budget,
            "max_history_tokens": _MAX_HISTORY_TOKENS,
            "history_budget_capped": history_budget < available_history_budget,
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
            **compact_metrics,
            "max_total_tool_result_chars": _MAX_TOTAL_TOOL_CHARS,
            **metrics,
            "dataset_capsule_injected": bool(dataset_block),
            "dataset_capsule_chars": len(dataset_block),
            "turn_active_variable": turn_ctx.active_variable,
            "turn_domain_profile": turn_ctx.domain_profile,
            "turn_authorized_sources": list(turn_ctx.authorized_sources),
            "turn_derived_subsets": len(turn_ctx.derived_zone_subsets),
            "turn_output_intent": output_intent.intent,
            "turn_output_intent_confidence": output_intent.confidence,
            "preseeded_graph_skills": list(preseeded_graph_skills),
            "preseeded_source_skills": list(preseeded_source_skills),
            "graph_reference_phase": graph_reference_phase,
            "graph_reference_chars": len(graph_reference_block),
            "source_reference_chars": len(source_reference_block),
            "neolabs_reference_chars": len(neolabs_reference_block),
            "fish_larvae_reference_chars": len(fish_larvae_reference_block),
            "static_reference_chars": len(static_reference_block),
            "dynamic_context_chars": len(dynamic_context_block),
            **user_instruction_metrics,
            "tools_before_policy": [
                getattr(item, "name", "") for item in original_tools
            ],
            "tools_after_source_scope": [
                getattr(item, "name", "") for item in scoped_tools
            ],
            "tools_exposed": list(exposure_decision.tool_names),
            "tool_exposure_count": len(exposure_decision.tool_names),
            "tool_exposure_alert": len(exposure_decision.tool_names) >= 12,
            "tool_exposure_groups": list(exposure_decision.active_groups),
            "tool_exposure_reasons": list(exposure_decision.reasons),
            "tools_dropped": list(exposure_decision.dropped_tool_names),
            "policy_overflow": exposure_decision.policy_overflow,
            "code_retry_forced_tool": code_retry[0] if code_retry else None,
        }
        _context_audit_by_thread[self.thread_id] = audit_entry
        _append_harness_model_call(self.thread_id, audit_entry)
        try:
            overrides = {
                "messages": trimmed_messages,
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
                "messages": trimmed_messages,
                "system_message": prepared_system_message,
            }
            if retry_tool_choice is not None:
                fallback_overrides["tool_choice"] = retry_tool_choice
            return request.override(**fallback_overrides)

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

    def _tool_exposure_rejection(self, request) -> str | None:
        """Reject a tool absent from the deterministic allowlist for this turn."""

        from tools.session_store import default_store as session_store
        from tools.source_scope import source_decision_for_turn
        from tools.tool_catalog import TOOL_POLICIES
        from tools.tool_exposure import decide_tool_exposure
        from tools.turn_context import build_turn_context
        from dataclasses import replace

        messages = list(request.state.get("messages") or [])
        source_decision = source_decision_for_turn(
            session_store,
            self.thread_id,
            messages,
            persist=False,
        )
        turn_ctx = build_turn_context(
            session_store,
            self.thread_id,
            messages,
            persist_source=False,
        )
        turn_ctx = replace(
            turn_ctx,
            output_intent=self._output_intent_decision(messages).intent,
        )
        available_names = self.catalog_names or tuple(TOOL_POLICIES)
        decision = decide_tool_exposure(
            available_names,
            TOOL_POLICIES,
            turn_ctx,
            source_decision,
            messages,
        )
        name = str(request.tool_call.get("name") or "")
        if name in decision.tool_names:
            return None
        retry = _code_retry_plan(messages)
        if retry is not None and retry[0] == name:
            return None
        return (
            "Action unavailable in the current turn of the workflow. "
            "Continue with the visible actions or request the missing "
            "information before retrying."
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
        retry = _code_retry_plan(messages)
        if retry is not None and retry[0] == name:
            return None
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
        retry = _code_retry_plan(messages)
        if retry is not None and retry[0] == name:
            return None
        decision = await self._aoutput_intent_decision(messages)
        return self._decision_rejection(decision) or graph_workflow_rejection(
            name, args, messages
        )

    def wrap_tool_call(self, request, handler):
        trace_id = _start_harness_tool_call(self.thread_id, request.tool_call)
        rejection = self._source_scope_rejection(request) or self._tool_identifier_rejection(request)
        if rejection:
            result = self._blocked_tool_message(request, rejection)
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="source_policy")
            return result
        rejection = self._tool_exposure_rejection(request)
        if rejection:
            result = self._blocked_tool_message(
                request,
                rejection,
                provenance_source="tool_exposure_policy",
                method="deterministic tool exposure guard",
            )
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="tool_exposure_policy")
            return result
        rejection = self._output_intent_rejection(request)
        if rejection:
            result = self._blocked_tool_message(
                request,
                rejection,
                provenance_source="output_intent_guard",
                method="typed output intent guard",
            )
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="output_intent_guard")
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
        rejection = self._source_scope_rejection(request) or self._tool_identifier_rejection(request)
        if rejection:
            result = self._blocked_tool_message(request, rejection)
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="source_policy")
            return result
        rejection = self._tool_exposure_rejection(request)
        if rejection:
            result = self._blocked_tool_message(
                request,
                rejection,
                provenance_source="tool_exposure_policy",
                method="deterministic tool exposure guard",
            )
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="tool_exposure_policy")
            return result
        rejection = await self._aoutput_intent_rejection(request)
        if rejection:
            result = self._blocked_tool_message(
                request,
                rejection,
                provenance_source="output_intent_guard",
                method="typed output intent guard",
            )
            _finish_harness_tool_call(self.thread_id, trace_id, result, blocked_by="output_intent_guard")
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
                catalog_names=catalog.names,
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
