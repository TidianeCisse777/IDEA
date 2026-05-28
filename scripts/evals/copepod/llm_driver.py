from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import settings
from .harness import LIVE_OPENAI_TIMEOUT_SECONDS, _json_dumps


def _compact_tool_result(name: str | None, result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if name == "inspect_file":
        cols = result.get("columns") or []
        by_role: dict[str, list[str]] = {}
        unknown: list[str] = []
        for c in cols:
            role = c.get("semantic_guess") if isinstance(c, dict) else None
            if role:
                by_role.setdefault(role, []).append(c["name"])
            elif isinstance(c, dict):
                unknown.append(c["name"])
        known_summary = {
            role: names if len(names) <= 5 else {"count": len(names), "examples": names[:3]}
            for role, names in by_role.items()
        }
        # Keep all columns (needed for infer_column_roles) but strip to 3 fields.
        # Full 7-field compact at 161 cols = ~28K chars; 3-field = ~9K chars.
        # unit_guess/confidence/missing_rate are redundant at this stage — the LLM
        # can call describe_column for anything it needs to clarify.
        compact_columns = [
            {
                "name": col.get("name"),
                "dtype": col.get("dtype"),
                "semantic_guess": col.get("semantic_guess"),
            }
            for col in cols
            if isinstance(col, dict)
        ]
        return {
            "n_rows": result.get("n_rows"),
            "n_columns": result.get("n_columns"),
            "source_type_guess": result.get("source_type_guess"),
            "columns": compact_columns,
            "known_by_role": known_summary,
            "unknown_columns": unknown,
            "warnings": result.get("warnings") or [],
        }
    if name == "describe_column":
        # Truncate definition to avoid the LLM bloating summarize_understanding
        # arguments when it passes 10-16 describe_column results as column_definitions.
        definition = (result.get("definition") or "")[:300]
        return {
            "column": result.get("column"),
            "definition": definition,
            "unit": result.get("unit"),
            "confidence": result.get("confidence"),
            "critical_notes": (result.get("critical_notes") or [])[:3],
        }
    if name == "infer_column_roles":
        return {
            "matched_count": len(result.get("roles") or []),
            "unmatched_columns": result.get("unmatched_columns") or [],
            "warnings": result.get("warnings") or [],
        }
    if name == "summarize_understanding":
        return {
            "status": "ok",
            "file_or_source": result.get("file_or_source"),
            "probable_source_type": result.get("probable_source_type"),
            "taxonomic_validation_status": result.get("taxonomic_validation_status"),
            "column_count": len(result.get("column_catalogue") or []),
        }
    if name == "synthesize_file_understanding":
        global_block = result.get("global") or {}
        return {
            "file_count": len(result.get("file_summaries") or []),
            "global": {
                "possible_joins": global_block.get("possible_joins"),
                "complementarity": (global_block.get("complementarity") or "")[:200],
                "temporal_coverage": global_block.get("temporal_coverage"),
                "spatial_coverage": global_block.get("spatial_coverage"),
            },
        }
    if name in {
        "create_data_understanding_draft",
        "activate_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_data_understanding",
        "get_active_graph_context",
        "plan_remote_source_request",
        "fetch_remote_source_dataset",
    }:
        compact = {
            "version_id": result.get("version_id"),
            "artifact_type": result.get("artifact_type"),
            "status": result.get("status"),
            "created": result.get("created"),
            "blocking_reason": result.get("blocking_reason"),
            "error": result.get("error"),
            "source_id": result.get("source_id"),
            "intent": result.get("intent"),
            "missing_fields": result.get("missing_fields"),
            "recommended_next_step": result.get("recommended_next_step"),
        }
        if name == "plan_remote_source_request":
            compact["parameters"] = result.get("parameters")
            compact["clarification_question"] = result.get("clarification_question")
        if name == "fetch_remote_source_dataset":
            compact["file_path"] = result.get("file_path")
            compact["original_filename"] = result.get("original_filename")
            compact["row_count"] = result.get("row_count")
            compact["source_dataset_id"] = result.get("source_dataset_id")
            compact["source_dataset_title"] = result.get("source_dataset_title")
        return compact
    return result


def _message_to_dict(message: Any) -> dict:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    return dict(message)


def _tool_call_to_dict(tool_call: Any) -> dict:
    if isinstance(tool_call, dict):
        return tool_call
    if hasattr(tool_call, "model_dump"):
        return tool_call.model_dump(exclude_none=True)
    return dict(tool_call)


def _completion_message(response: Any) -> Any:
    if isinstance(response, dict):
        return response["choices"][0]["message"]
    return response.choices[0].message


def _tool_specs() -> list[dict]:
    def function_tool(name: str, description: str, properties: dict, required: list[str]):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    object_schema = {"type": "object", "additionalProperties": True}
    return [
        function_tool(
            "inspect_file",
            "Inspect an uploaded CSV/TSV file and return metadata, columns, dtypes, and samples.",
            {"file_path": {"type": "string"}, "sample_rows": {"type": "integer", "default": 20}},
            ["file_path"],
        ),
        function_tool(
            "infer_column_roles",
            "Infer semantic roles from inspected columns and metadata.",
            {"columns": {"type": "array", "items": object_schema}, "metadata": object_schema},
            ["columns"],
        ),
        function_tool(
            "describe_column",
            "Look up a column definition in the copepod RAG knowledge base.",
            {
                "column_name": {"type": "string"},
                "source_hint": {"type": "string"},
                "session_id": {"type": "string"},
            },
            ["column_name"],
        ),
        function_tool(
            "summarize_understanding",
            "Build a structured Data Understanding payload from inspection, role, and RAG reports. Pass all describe_column results in column_definitions.",
            {
                "inspect_report": object_schema,
                "role_report": object_schema,
                "column_definitions": {
                    "type": "array",
                    "items": object_schema,
                    "description": "List of describe_column results to enrich the column catalogue.",
                },
            },
            ["inspect_report", "role_report"],
        ),
        function_tool(
            "synthesize_file_understanding",
            "Synthesize the global Data Understanding block for a multi-file session. Call this after all per-file summarize_understanding calls, before create_data_understanding_draft. Provide the semantic synthesis: join possibilities, temporal/spatial coverage, and how the files complement each other.",
            {
                "file_summaries": {"type": "array", "items": object_schema, "description": "List of summarize_understanding outputs, one per file."},
                "possible_joins": {"type": "array", "items": {"type": "string"}, "description": "Join descriptions, e.g. 'EcoTaxa ↔ EcoPart via obj_orig_id → profile_id'. Empty list if none."},
                "complementarity": {"type": "string", "description": "How the files complement each other scientifically."},
                "temporal_coverage": {"type": "string", "description": "Temporal extent extracted from the data (dates, years, or time ranges in columns). Report what is present in each file even if sources differ (e.g. 'Green Edge: avril–mai 2015 ; Bio-Oracle: 2020'). Use 'non applicable' ONLY if no temporal information exists in any file."},
                "spatial_coverage": {"type": "string", "description": "Spatial extent extracted from the data (lat/lon ranges, region names, station names). Report what is present even if sources differ. Use 'non applicable' ONLY if no spatial information exists in any file."},
                "coverage_assessment": {**object_schema, "description": "Optional global coverage dict. Computed from per-file statuses if omitted."},
                "session_key": {"type": "string"},
            },
            ["file_summaries", "possible_joins", "complementarity", "temporal_coverage", "spatial_coverage"],
        ),
        function_tool(
            "create_data_understanding_draft",
            "Persist a draft Data Understanding artifact.",
            {"session_key": {"type": "string"}, "artifact": object_schema},
            ["session_key", "artifact"],
        ),
        function_tool(
            "activate_data_understanding",
            "Activate a Data Understanding artifact after user confirmation.",
            {"session_key": {"type": "string"}, "version_id": {"type": "string"}},
            ["session_key", "version_id"],
        ),
        function_tool(
            "get_active_data_understanding",
            "Read the active Data Understanding artifact.",
            {"session_key": {"type": "string"}},
            ["session_key"],
        ),
        function_tool(
            "create_graph_context_draft",
            "Persist a draft Graph Context artifact linked to active Data Understanding.",
            {"session_key": {"type": "string"}, "artifact": object_schema},
            ["session_key", "artifact"],
        ),
        function_tool(
            "activate_graph_context",
            "Activate a Graph Context artifact after user confirmation.",
            {"session_key": {"type": "string"}, "version_id": {"type": "string"}},
            ["session_key", "version_id"],
        ),
        function_tool(
            "get_active_graph_context",
            "Read the active Graph Context artifact.",
            {"session_key": {"type": "string"}},
            ["session_key"],
        ),
        function_tool(
            "list_available_sources",
            "List known copepod data sources and whether they are activated.",
            {"auth_token": {"type": "string"}, "session_id": {"type": "string"}},
            [],
        ),
        function_tool(
            "describe_source",
            "Return the full metadata for a copepod data source.",
            {"source_id": {"type": "string"}, "session_id": {"type": "string"}},
            ["source_id"],
        ),
        function_tool(
            "plan_remote_source_request",
            "Normalize an explicit OGSL or Bio-ORACLE request and extract the missing fields before a remote fetch.",
            {
                "request_text": {"type": "string"},
                "source_hint": {"type": "string"},
                "session_id": {"type": "string"},
            },
            ["request_text"],
        ),
        function_tool(
            "fetch_remote_source_dataset",
            "Fetch an allowed online source and persist the result as a derived CSV in the session uploads folder.",
            {
                "session_key": {"type": "string"},
                "source_id": {"type": "string"},
                "parameters": {"type": "object", "additionalProperties": True},
                "output_filename": {"type": "string"},
            },
            ["session_key", "source_id", "parameters"],
        ),
    ]


def _gc_only_tool_specs() -> list[dict]:
    gc_names = {
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
    }
    return [spec for spec in _tool_specs() if spec["function"]["name"] in gc_names]


def _live_tool_impls(tools: dict[str, Any], session_key: str) -> dict[str, Callable[..., Any]]:
    session_scoped = {
        "synthesize_file_understanding",
        "create_data_understanding_draft",
        "activate_data_understanding",
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
        "fetch_remote_source_dataset",
    }
    _cache: dict[str, Any] = {}

    def call_tool(name: str, arguments: dict) -> Any:
        if name in session_scoped:
            arguments = {**arguments, "session_key": session_key}
        if name == "describe_column" and not arguments.get("session_id"):
            arguments["session_id"] = session_key.split(":")[1]
        if name == "synthesize_file_understanding":
            # If the LLM passed fewer or incomplete file_summaries, replace with
            # the actual cached summarize_understanding outputs.
            llm_summaries = arguments.get("file_summaries") or []
            cached_summaries = _cache.get("all_summaries") or []
            if cached_summaries and (
                not llm_summaries
                or len(llm_summaries) < len(cached_summaries)
                or not all(
                    isinstance(s, dict) and s.get("column_catalogue")
                    for s in llm_summaries
                )
            ):
                arguments = {**arguments, "file_summaries": cached_summaries}
        if name == "create_data_understanding_draft":
            artifact = arguments.get("artifact")
            summary = _cache.get("summary_report") or {}
            if summary:
                if isinstance(artifact, dict):
                    patched_artifact = dict(artifact)
                    for key, value in summary.items():
                        if key not in patched_artifact or not patched_artifact.get(key):
                            patched_artifact[key] = value
                    arguments = {**arguments, "artifact": patched_artifact}
                else:
                    arguments = {**arguments, "artifact": dict(summary)}
        result = tools[name](**arguments)
        if name == "inspect_file":
            _cache["inspect_report"] = result
        elif name == "infer_column_roles":
            _cache["role_report"] = result
        elif name == "summarize_understanding":
            _cache["summary_report"] = result
        return result

    def call_summarize(**kwargs) -> Any:
        inspect_report = _cache.get("inspect_report") or kwargs.get("inspect_report")
        role_report = _cache.get("role_report") or kwargs.get("role_report") or {
            "roles": [], "unmatched_columns": [], "warnings": []
        }
        result = tools["summarize_understanding"](
            inspect_report, role_report, kwargs.get("column_definitions")
        )
        _cache["summary_report"] = result
        _cache.setdefault("all_summaries", []).append(result)
        return result

    tool_names = {
        "inspect_file", "infer_column_roles", "describe_column",
        "summarize_understanding", "synthesize_file_understanding",
        "create_data_understanding_draft",
        "activate_data_understanding", "get_active_data_understanding",
        "create_graph_context_draft", "activate_graph_context", "get_active_graph_context",
        "list_available_sources", "describe_source", "plan_remote_source_request",
        "fetch_remote_source_dataset",
    }
    impls = {name: (lambda _name=name, **kwargs: call_tool(_name, kwargs)) for name in tool_names}
    impls["summarize_understanding"] = call_summarize
    return impls


def _gc_only_tool_impls(tools: dict[str, Any], session_key: str) -> dict[str, Callable[..., Any]]:
    impls = _live_tool_impls(tools, session_key)
    blocked_reason = (
        "GC-only eval: Data Understanding is already active, so Phase 1 tools are disabled."
    )

    def _blocked_tool(name: str):
        def _call(**kwargs):
            return {"blocked": True, "blocking_reason": blocked_reason, "tool": name}
        return _call

    for name in {
        "inspect_file", "infer_column_roles", "describe_column",
        "summarize_understanding", "create_data_understanding_draft", "activate_data_understanding",
    }:
        impls[name] = _blocked_tool(name)
    return impls


def _run_llm_turn(
    *,
    messages: list[dict],
    tool_impls: dict[str, Callable[..., Any]],
    model: str,
    completion_fn: Callable[..., Any],
    metadata: dict,
    max_tool_rounds: int = 40,
    tool_specs: list[dict] | None = None,
    log_fn: Callable[[str], None] | None = None,
    log_fh=None,  # backward-compat: other eval scripts pass a file handle
) -> str:
    if log_fn is None and log_fh is not None:
        def log_fn(line: str):
            log_fh.write(line + "\n")
            log_fh.flush()

    phase = metadata.get("phase", "?")
    describe_column_round_seen = False
    # Resolve tool specs once so every round sends the identical object —
    # avoids rebuilding the list per-round, which would prevent prefix caching.
    _resolved_tool_specs = tool_specs if tool_specs is not None else _tool_specs()

    def _log(line: str):
        if log_fn is not None:
            log_fn(line)

    last_content = ""
    for round_index in range(max_tool_rounds):
        for attempt in range(2):
            try:
                completion_kwargs = {
                    "model": model,
                    "messages": messages,
                    "tools": _resolved_tool_specs,
                    "tool_choice": "auto",
                    "temperature": float(os.getenv("LLM_TEMPERATURE", settings.LLM_TEMPERATURE)),
                    "metadata": {**metadata, "round": round_index + 1},
                }
                if settings.LLM_REASONING_EFFORT is not None:
                    completion_kwargs["reasoning_effort"] = settings.LLM_REASONING_EFFORT
                response = completion_fn(**completion_kwargs)
                break
            except Exception as exc:
                _log(f"  [ERROR] phase={phase} round={round_index+1} llm_exception={exc}")
                if attempt == 0 and "rate limit" in str(exc).lower():
                    m = re.search(r"try again in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
                    wait = float(m.group(1)) + 2 if m else 30
                    _log(f"  [WAIT]  rate_limit — sleeping {wait:.0f}s before retry")
                    time.sleep(wait)
                    continue
                raise

        message = _message_to_dict(_completion_message(response))
        messages.append(message)
        last_content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        # Log token usage with cache details for every round.
        try:
            _u = getattr(response, "usage", None)
            if _u is not None:
                _d = getattr(_u, "prompt_tokens_details", None)
                _cached = getattr(_d, "cached_tokens", "n/a") if _d else "no_details"
                _log(
                    f"  [USAGE] phase={phase} round={round_index+1} "
                    f"prompt={getattr(_u, 'prompt_tokens', '?')} "
                    f"completion={getattr(_u, 'completion_tokens', '?')} "
                    f"cached={_cached}"
                )
        except Exception:
            pass

        if not tool_calls:
            _log(f"  [TEXT]  phase={phase} round={round_index+1} content={last_content[:120]!r}")
            return last_content

        tool_names = [
            (_tool_call_to_dict(c).get("function") or {}).get("name") for c in tool_calls
        ]
        _log(f"  [CALL]  phase={phase} round={round_index+1} tools={tool_names}")

        if "inspect_file" in tool_names:
            describe_column_round_seen = False

        if "describe_column" in tool_names:
            if describe_column_round_seen:
                _log(
                    "  [BLOCK] describe_column already used in this phase — "
                    "injecting tool rejection, next step must be summarize_understanding"
                )
                # Keep the assistant message with its tool_calls intact.
                # Append a tool response for every blocked call so the API sees
                # a valid assistant→tool sequence and the LLM gets a clear rejection.
                for raw_call in tool_calls:
                    call = _tool_call_to_dict(raw_call)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": (call.get("function") or {}).get("name") or "describe_column",
                        "content": _json_dumps({
                            "error": (
                                "describe_column already used for this file. "
                                "You MUST call summarize_understanding now."
                            )
                        }),
                    })
                continue
            describe_column_round_seen = True

        for raw_call in tool_calls:
            call = _tool_call_to_dict(raw_call)
            function = call.get("function") or {}
            name = function.get("name")
            if name not in tool_impls:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    result = tool_impls[name](**arguments)
                except Exception as exc:
                    result = {"error": str(exc)}
            compact_result = _compact_tool_result(name, result)
            err = compact_result.get("error") if isinstance(compact_result, dict) else None
            blocking = compact_result.get("blocking_reason") if isinstance(compact_result, dict) else None
            status = compact_result.get("status") if isinstance(compact_result, dict) else None
            detail = (
                f"status={status}" if status
                else (f"error={err}" if err
                      else (f"blocked={blocking[:80]}" if blocking else "ok"))
            )
            _log(f"  [TOOL]  {name} → {detail}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "name": name,
                "content": _json_dumps(compact_result),
            })

    _log(f"  [WARN]  phase={phase} max_tool_rounds={max_tool_rounds} reached — returning last_content")
    return last_content


def _default_live_completion(*, metadata: dict | None = None, **kwargs):
    from openai import OpenAI

    langfuse_metadata = metadata or {}
    model = kwargs.get("model")
    messages = kwargs.get("messages")
    tools = kwargs.get("tools")
    phase = langfuse_metadata.get("phase", "llm-turn")
    round_index = langfuse_metadata.get("round", 1)
    lf_phase_span = langfuse_metadata.get("lf_phase_span")

    response = OpenAI(timeout=LIVE_OPENAI_TIMEOUT_SECONDS, max_retries=0).chat.completions.create(
        **kwargs,
        max_completion_tokens=4000,
    )
    message = _message_to_dict(_completion_message(response))

    if lf_phase_span is not None:
        try:
            raw_usage = getattr(response, "usage", None)
            lf_usage = None
            lf_usage_details = None
            if raw_usage is not None:
                prompt_tokens = getattr(raw_usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(raw_usage, "completion_tokens", 0) or 0
                lf_usage = {
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "total": getattr(raw_usage, "total_tokens", 0) or 0,
                }
                details = getattr(raw_usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", None) if details else None
                # Log whenever details is present so Langfuse shows 0 vs. absent.
                # `if cached:` swallows 0, making it impossible to distinguish
                # "no cache hits" from "model doesn't return this field at all".
                if details is not None:
                    lf_usage_details = {"input_cached": cached or 0}
            tool_calls_out = message.get("tool_calls") or []
            tool_names_out = [c.get("function", {}).get("name") for c in tool_calls_out]
            lf_phase_span.generation(
                name=f"round-{round_index}",
                model=model,
                input={"messages": messages[-2:] if messages else [], "tools_count": len(tools or [])},
                output={"tool_calls": tool_names_out, "content": message.get("content") or ""},
                usage=lf_usage,
                usage_details=lf_usage_details,
                level="DEFAULT",
                metadata={"phase": phase, "round": round_index, "tool_calls": tool_names_out},
            )
        except Exception:
            pass

    return response
