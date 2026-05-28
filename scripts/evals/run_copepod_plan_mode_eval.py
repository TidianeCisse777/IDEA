from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.copepod_profile  # noqa: F401
from core.auth import get_auth_token
from core.chat_stream_events import chat_stream_events
from core.config import settings
from core.langfuse_guard import validate_langfuse_configuration
from core.session_store import InMemorySessionStore
from routers.file_routes import router as file_router
from routers.session_routes import router as session_router

import core.instruction_renderer.blocks.copepod_mode_plan  # noqa: F401
import core.instruction_renderer.blocks.copepod_tool_signatures  # noqa: F401
from core.copepod_plan_workflow import PLAN_READY
from core.copepod_observability import should_enable_langfuse


DATASET_NAME = "copepod-plan-mode-v1"
LIVE_OPENAI_TIMEOUT_SECONDS = float(os.getenv("COPEPOD_LIVE_OPENAI_TIMEOUT_SECONDS", "120"))
FIXTURES = Path(
    "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv"
)
ECOTAXA = FIXTURES / "ecotaxa_green_edge_sample_200.tsv"
ECOPART = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"


def _load_tools() -> dict[str, Any]:
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_columns  # noqa: F401
    from core.tool_registry.tools import copepod_data  # noqa: F401
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    ns: dict[str, Any] = {}
    exec(registry.render({"copepod_data", "copepod_columns", "copepod_artifacts"}), ns)
    return ns


def _test_client(store: InMemorySessionStore) -> tuple[TestClient, ExitStack]:
    # Some tests clear the global profile registry; eval routes need copepod registered.
    import agents.copepod_profile
    import agents.generic_profile

    importlib.reload(agents.generic_profile)
    importlib.reload(agents.copepod_profile)

    app = FastAPI()
    app.include_router(file_router)
    app.include_router(session_router)
    app.dependency_overrides[get_auth_token] = lambda: "eval-token"

    fake_user = SimpleNamespace(id="eval-user")
    stack = ExitStack()
    stack.enter_context(patch("routers.file_routes.get_current_user", return_value=fake_user))
    stack.enter_context(patch("routers.session_routes.get_current_user", return_value=fake_user))
    stack.enter_context(patch("routers.session_routes.session_store", store))
    stack.enter_context(patch("core.session_store.session_store", store))
    return TestClient(app), stack


def _stage_fixture(session_id: str, path: Path) -> dict:
    """Copy a fixture into the eval upload directory without hitting the HTTP rate limiter."""
    user_id = "eval-user"
    upload_dir = ROOT / "static" / user_id / session_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / path.name
    shutil.copy2(path, destination)
    return {
        "filename": path.name,
        "size": destination.stat().st_size,
        "path": str(destination.relative_to(upload_dir)),
        "scan_result": "Staged locally for eval (HTTP upload bypassed)",
    }


def _upload_fixture(client: TestClient, session_id: str, path: Path) -> dict:
    """Backward-compatible alias used by other eval runners."""
    return _stage_fixture(session_id, path)


def _uploaded_path(session_id: str, filename: str) -> Path:
    return Path("static") / "eval-user" / session_id / "uploads" / filename


def _uploaded_path_label(session_id: str, filename: str) -> tuple[str, str]:
    """Return the local tool path plus the canonical /app/static label."""
    local_path = _uploaded_path(session_id, filename).resolve()
    canonical_path = Path("/app/static") / "eval-user" / session_id / "uploads" / filename
    return str(local_path), str(canonical_path)


def _file_entry(path: Path, inspect_report: dict) -> dict:
    return {
        "file_path": str(path),
        "original_filename": path.name,
        "size_bytes": path.stat().st_size,
        "content_hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        "uploaded_at": "2026-05-26T12:00:00+00:00",
        "inspection_tool_version": "inspect_file:v1",
        "source_type_guess": inspect_report["source_type_guess"],
    }


def _data_understanding_artifact(tools: dict[str, Any], path: Path) -> dict:
    inspected = tools["inspect_file"](str(path), sample_rows=10)
    roles = tools["infer_column_roles"](inspected["columns"], inspected["metadata"])
    summary = tools["summarize_understanding"](inspected, roles)
    return {
        "files": [
            {
                **_file_entry(path, inspected),
                "columns": inspected["columns"],
                "roles": roles["roles"],
                "taxonomic_validation_status": summary["taxonomic_validation_status"],
                "quality_limits": summary["quality_limits"],
            }
        ],
        "global": {
            "column_catalogue": summary["column_catalogue"],
            "possible_joins_or_couplings": summary["possible_joins_or_couplings"],
            "missing_or_ambiguous_data": summary["missing_or_ambiguous_data"],
        },
        "column_catalogue": summary["column_catalogue"],
        "coverage_assessment": summary["coverage_assessment"],
        "overrides": [],
    }


def _post_analyse(client: TestClient, session_id: str):
    return client.post(
        "/session/mode",
        json={"mode": "analyse"},
        headers={"x-session-id": session_id, "x-agent-type": "copepod"},
    )


def _plan_ready_allowed(store: InMemorySessionStore, session_key: str) -> bool:
    return (
        store.get_copepod_plan_phase(session_key) == PLAN_READY
        and store.has_active_copepod_plan_artifacts(session_key)
    )


def _result(name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "metadata": metadata or {},
    }


def _browser_trace_url(url: str | None) -> str | None:
    """Replace the internal Docker hostname with the browser-accessible one if set."""
    if not url:
        return url
    fallback = os.getenv("LANGFUSE_HOST_LOCAL")
    if fallback and "://langfuse:3000" in url:
        return url.replace("http://langfuse:3000", fallback.rstrip("/"))
    return url


def _configure_local_langfuse_host() -> None:
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or ""
    if "://langfuse:3000" not in host:
        return
    fallback = os.getenv("LANGFUSE_HOST_LOCAL")
    if not fallback:
        return
    try:
        req = Request(f"{fallback}/api/public/projects", method="GET")
        urlopen(req, timeout=2)
    except Exception as exc:
        if getattr(exc, "code", None) not in {200, 401}:
            return
    os.environ["LANGFUSE_HOST"] = fallback
    os.environ["LANGFUSE_BASE_URL"] = fallback


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _cleanup_old_logs(log_dir: Path, prefix: str, keep: int = 3) -> None:
    logs = sorted(log_dir.glob(f"{prefix}*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        old.unlink(missing_ok=True)



def _compact_tool_result(name: str | None, result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if name == "inspect_file":
        # Group columns by semantic role (compact summary).
        # For large groups (>5), show count only. For small groups, show names.
        # Unknown columns (no semantic_guess) get the full list — LLM needs
        # them to decide which describe_column calls to make.
        cols = result.get("columns") or []
        compact_columns = [
            {
                "name": col.get("name"),
                "dtype": col.get("dtype"),
                "semantic_guess": col.get("semantic_guess"),
                "unit_guess": col.get("unit_guess"),
                "confidence": col.get("confidence"),
                "missing_rate": col.get("missing_rate"),
                "missing_count": col.get("missing_count"),
            }
            for col in cols
            if isinstance(col, dict)
        ]
        by_role: dict[str, list[str]] = {}
        unknown: list[str] = []
        for c in cols:
            role = c.get("semantic_guess")
            if role:
                by_role.setdefault(role, []).append(c["name"])
            else:
                unknown.append(c["name"])
        known_summary = {
            role: names if len(names) <= 5 else {"count": len(names), "examples": names[:3]}
            for role, names in by_role.items()
        }
        return {
            "n_rows": result.get("n_rows"),
            "n_columns": result.get("n_columns"),
            "source_type_guess": result.get("source_type_guess"),
            "columns": compact_columns,
            "known_by_role": known_summary,
            "unknown_columns": unknown,
            "warnings": result.get("warnings") or [],
        }
    if name == "infer_column_roles":
        # LLM only needs the unmatched list to decide which describe_column to call.
        return {
            "matched_count": len(result.get("roles") or []),
            "unmatched_columns": result.get("unmatched_columns") or [],
            "warnings": result.get("warnings") or [],
        }
    if name == "summarize_understanding":
        # LLM doesn't need the full catalogue in context — just confirmation.
        return {
            "status": "ok",
            "file_or_source": result.get("file_or_source"),
            "probable_source_type": result.get("probable_source_type"),
            "taxonomic_validation_status": result.get("taxonomic_validation_status"),
            "column_count": len(result.get("column_catalogue") or []),
        }
    if name in {
        "create_data_understanding_draft",
        "activate_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_data_understanding",
        "get_active_graph_context",
    }:
        # Strip payload — LLM only needs version_id + status to proceed.
        return {
            "version_id": result.get("version_id"),
            "artifact_type": result.get("artifact_type"),
            "status": result.get("status"),
            "created": result.get("created"),
            "blocking_reason": result.get("blocking_reason"),
            "error": result.get("error"),
        }
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
            {
                "file_path": {"type": "string"},
                "sample_rows": {"type": "integer", "default": 20},
            },
            ["file_path"],
        ),
        function_tool(
            "infer_column_roles",
            "Infer semantic roles from inspected columns and metadata.",
            {
                "columns": {"type": "array", "items": object_schema},
                "metadata": object_schema,
            },
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
            "create_data_understanding_draft",
            "Persist a draft Data Understanding artifact.",
            {
                "session_key": {"type": "string"},
                "artifact": object_schema,
            },
            ["session_key", "artifact"],
        ),
        function_tool(
            "activate_data_understanding",
            "Activate a Data Understanding artifact after user confirmation.",
            {
                "session_key": {"type": "string"},
                "version_id": {"type": "string"},
            },
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
            {
                "session_key": {"type": "string"},
                "artifact": object_schema,
            },
            ["session_key", "artifact"],
        ),
        function_tool(
            "activate_graph_context",
            "Activate a Graph Context artifact after user confirmation.",
            {
                "session_key": {"type": "string"},
                "version_id": {"type": "string"},
            },
            ["session_key", "version_id"],
        ),
        function_tool(
            "get_active_graph_context",
            "Read the active Graph Context artifact.",
            {"session_key": {"type": "string"}},
            ["session_key"],
        ),
    ]


def _gc_only_tool_specs() -> list[dict]:
    tool_names = {
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
    }
    return [
        spec for spec in _tool_specs()
        if spec["function"]["name"] in tool_names
    ]


def _live_tool_impls(tools: dict[str, Any], session_key: str) -> dict[str, Callable[..., Any]]:
    session_scoped = {
        "create_data_understanding_draft",
        "activate_data_understanding",
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
    }
    # Cache full (non-compact) results so summarize_understanding receives
    # complete inspect_report and role_report without the LLM re-serializing them.
    _cache: dict[str, Any] = {}

    def call_tool(name: str, arguments: dict) -> Any:
        if name in session_scoped:
            arguments = {**arguments, "session_key": session_key}
        if name == "describe_column" and not arguments.get("session_id"):
            arguments["session_id"] = session_key.split(":")[1]
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
        return result

    tool_names = {
        "inspect_file", "infer_column_roles", "describe_column",
        "summarize_understanding", "create_data_understanding_draft",
        "activate_data_understanding", "get_active_data_understanding",
        "create_graph_context_draft", "activate_graph_context", "get_active_graph_context",
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
        "inspect_file",
        "infer_column_roles",
        "describe_column",
        "summarize_understanding",
        "create_data_understanding_draft",
        "activate_data_understanding",
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
    log_fh=None,
) -> str:
    phase = metadata.get("phase", "?")
    describe_column_round_seen = False

    def _log(line: str):
        if log_fh is not None:
            log_fh.write(line + "\n")
            log_fh.flush()

    last_content = ""
    for round_index in range(max_tool_rounds):
        for attempt in range(2):
            try:
                completion_kwargs = {
                    "model": model,
                    "messages": messages,
                    "tools": tool_specs or _tool_specs(),
                    "tool_choice": "auto",
                    "temperature": float(os.getenv("LLM_TEMPERATURE", settings.LLM_TEMPERATURE)),
                    "metadata": {**metadata, "round": round_index + 1},
                }
                if settings.LLM_REASONING_EFFORT is not None:
                    completion_kwargs["reasoning_effort"] = settings.LLM_REASONING_EFFORT
                response = completion_fn(
                    **completion_kwargs,
                )
                break
            except Exception as exc:
                _log(f"  [ERROR] phase={phase} round={round_index+1} llm_exception={exc}")
                if attempt == 0 and "rate limit" in str(exc).lower():
                    import re as _re
                    m = _re.search(r"try again in (\d+(?:\.\d+)?)s", str(exc), _re.IGNORECASE)
                    wait = float(m.group(1)) + 2 if m else 30
                    _log(f"  [WAIT]  rate_limit — sleeping {wait:.0f}s before retry")
                    time.sleep(wait)
                    continue
                raise
        message = _message_to_dict(_completion_message(response))
        messages.append(message)
        last_content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            _log(f"  [TEXT]  phase={phase} round={round_index+1} content={last_content[:120]!r}")
            return last_content

        tool_names = [(_tool_call_to_dict(c).get("function") or {}).get("name") for c in tool_calls]
        _log(f"  [CALL]  phase={phase} round={round_index+1} tools={tool_names}")

        if "describe_column" in tool_names:
            if describe_column_round_seen:
                _log(
                    "  [BLOCK] describe_column already used in this phase — "
                    "returning control to summarize_understanding"
                )
                messages[-1] = {
                    "role": "assistant",
                    "content": (
                        "describe_column already completed for this phase. "
                        "Continue with summarize_understanding."
                    ),
                    "tool_calls": [],
                }
                return messages[-1]["content"]
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
            detail = f"status={status}" if status else (f"error={err}" if err else (f"blocked={blocking[:80]}" if blocking else "ok"))
            _log(f"  [TOOL]  {name} → {detail}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "content": _json_dumps(compact_result),
                }
            )
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
    # lf_phase_span is a Langfuse StatefulSpanClient passed from run_live_eval
    lf_phase_span = langfuse_metadata.get("lf_phase_span")

    response = OpenAI(
        timeout=LIVE_OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    ).chat.completions.create(
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
                if cached:
                    lf_usage_details = {"input_cached": cached}
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


_EVAL_CANONICAL_SESSION_ID = "eval-canonical"


def _build_eval_system_message(store, session_id: str) -> str:
    """Build the real production system message for eval: COPEPOD_SYSTEM_PROMPT + rendered instruction blocks.

    session_id is accepted for API compatibility but the system message is always rendered
    with _EVAL_CANONICAL_SESSION_ID so the prefix is identical across all eval runs —
    enabling cross-run prompt caching (OpenAI prefix cache, TTL 5–10 min).
    The actual session_key is injected into tool calls by _live_tool_impls, and the real
    file path is passed explicitly in user messages, so no functional regression.
    """
    from agents.copepod_profile import CopepodProfile
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    profile = CopepodProfile(session_store=store)
    custom_instructions = profile.get_custom_instructions(
        host="http://localhost:8001",
        user_id="eval-user",
        session_id=_EVAL_CANONICAL_SESSION_ID,
        static_dir="/app/static",
        upload_dir=f"/app/data/uploads/eval-user/{_EVAL_CANONICAL_SESSION_ID}",
        mcp_tools=[],
    )
    eval_addendum = """---
Eval constraints (do not mention these to the user):
- You are under live evaluation. Do not claim any artifact is created, confirmed, or active unless the tool result explicitly states it.
- Tool calling order: call `inspect_file`, `infer_column_roles`, `summarize_understanding`, and `create_data_understanding_draft` each in its own response (one tool per turn). Exception: call ALL `describe_column` for unmatched columns in a single response, then continue directly with `summarize_understanding`; do not return to `describe_column` again in the same phase.
- Graph context artifact must include: data_understanding_version_id, objective, columns, filters, units, chart_type, language, output_artifacts, feasibility, blockers.
- When a file path appears in the eval prompt, use the exact local filesystem path shown there for tool calls. The `/app/static/...` label is informational only.
- If a tool returns an error or blocking_reason, report it and do not proceed to the next phase."""
    return COPEPOD_SYSTEM_PROMPT + "\n\n" + custom_instructions + "\n\n" + eval_addendum


def _live_eval_system_prompt(store=None, session_id: str = "") -> str:
    """Backward-compat shim — prefer _build_eval_system_message(store, session_id)."""
    if store is not None and session_id:
        return _build_eval_system_message(store, session_id)
    # Fallback: minimal prompt used when store/session_id not available (e.g. synthetic histories)
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
    return COPEPOD_SYSTEM_PROMPT


def _live_eval_runtime_context(session_id: str) -> str:
    session_key = f"eval-user:{session_id}:copepod"
    return f"""Runtime context:
- Use this exact session key for artifact tools: `{session_key}`."""


def _build_gc_only_system_message(store, session_id: str) -> str:
    base_prompt = _build_eval_system_message(store, session_id)
    gc_only_addendum = """---
GC-only eval constraints (do not mention these to the user):
- An active Data Understanding already exists for this session.
- Do not call Phase 1 tools: `inspect_file`, `infer_column_roles`, `describe_column`, `summarize_understanding`, or `create_data_understanding_draft`.
- First tool call in each scenario should be `get_active_data_understanding(session_key)` unless the user is explicitly correcting an existing Graph Context.
- If mandatory Graph Context fields are missing, ask one targeted question instead of guessing.
- Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded.
- If the user asks for code or analysis output before Graph Context is validated, refuse in Plan Mode before any tool call."""
    return base_prompt + "\n\n" + gc_only_addendum


def _seed_active_data_understanding(
    *,
    client: TestClient,
    tools: dict[str, Any],
    session_id: str,
    session_key: str,
    fixture_paths: list[Path],
) -> dict[str, Any]:
    uploaded_paths: list[Path] = []
    for path in fixture_paths:
        upload = _stage_fixture(session_id, path)
        uploaded_paths.append(_uploaded_path(session_id, upload["filename"]).resolve())

    draft_payload = {
        "files": [
            {
                "file_path": str(path),
                "original_filename": path.name,
            }
            for path in uploaded_paths
        ],
        "global": {},
        "overrides": [],
    }
    du_draft = tools["create_data_understanding_draft"](session_key, draft_payload)
    du_active = tools["activate_data_understanding"](session_key, du_draft["version_id"])
    return {
        "draft": du_draft,
        "active": du_active,
        "uploaded_paths": uploaded_paths,
    }


def _push_scores_to_langfuse(session_key: str, results: list[dict]) -> str | None:
    if not should_enable_langfuse():
        return None
    try:
        validate_langfuse_configuration()
        from langfuse import Langfuse
        _configure_local_langfuse_host()
        lf = Langfuse()
        trace = lf.trace(
            name="copepod-plan-mode-eval-scores",
            user_id="eval-user",
            session_id=session_key,
            input={"dataset": DATASET_NAME},
            output={
                "passed_count": sum(1 for result in results if result["passed"]),
                "total_count": len(results),
            },
            metadata={"created_at": datetime.now(timezone.utc).isoformat()},
            tags=["eval", "copepod", "scores"],
        )
        for result in results:
            trace.score(
                name=result["name"],
                value=1.0 if result["passed"] else 0.0,
                data_type="BOOLEAN",
                comment=result["detail"],
            )
        lf.flush()
        return _browser_trace_url(trace.get_trace_url())
    except Exception:
        return None


def run_langfuse_trace_smoke(
    *,
    prompt: str,
) -> dict:
    if not should_enable_langfuse():
        return {
            "dataset": DATASET_NAME,
            "mode": "trace-smoke",
            "model": settings.LLM_MODEL,
            "session_key": None,
            "passed": False,
            "response": "",
            "langfuse_trace_url": None,
        }
    validate_langfuse_configuration()
    from langfuse import Langfuse
    from openai import OpenAI

    _configure_local_langfuse_host()
    model_name = settings.LLM_MODEL
    session_key = f"eval-user:trace-smoke-{uuid.uuid4().hex[:8]}:copepod"
    lf = Langfuse()
    trace = lf.trace(
        name="copepod-langfuse-trace-smoke",
        user_id="eval-user",
        session_id=session_key,
        input={"prompt": prompt},
        tags=["eval", "copepod", "trace-smoke"],
        metadata={"model": model_name},
    )
    response = OpenAI(
        timeout=LIVE_OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    ).chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Reply concisely in French."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=80,
        **({"reasoning_effort": settings.LLM_REASONING_EFFORT} if settings.LLM_REASONING_EFFORT is not None else {}),
    )
    output = response.choices[0].message.content or ""
    raw_usage = getattr(response, "usage", None)
    lf_usage = None
    lf_usage_details = None
    if raw_usage is not None:
        lf_usage = {
            "input": getattr(raw_usage, "prompt_tokens", 0) or 0,
            "output": getattr(raw_usage, "completion_tokens", 0) or 0,
            "total": getattr(raw_usage, "total_tokens", 0) or 0,
        }
        details = getattr(raw_usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            lf_usage_details = {"input_cached": cached}
    trace.generation(
        name="trace-smoke-prompt",
        model=model_name,
        input=prompt,
        output=output,
        usage=lf_usage,
        usage_details=lf_usage_details,
        level="DEFAULT",
        metadata={"purpose": "verify trace and level"},
    )
    trace.score(
        name="trace_smoke_prompt_returned_output",
        value=1.0 if output.strip() else 0.0,
        data_type="BOOLEAN",
        comment="Prompt returned a non-empty output and generation was traced with level DEFAULT.",
    )
    trace.update(output={"response": output})
    lf.flush()
    return {
        "dataset": DATASET_NAME,
        "mode": "trace-smoke",
        "model": model_name,
        "session_key": session_key,
        "passed": bool(output.strip()),
        "response": output,
        "langfuse_trace_url": _browser_trace_url(trace.get_trace_url()),
    }


def run_live_du_only_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    """Run the live LLM only through Data Understanding, then stop."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"du-only-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    model_name = settings.LLM_MODEL
    completion_fn = completion_fn or _default_live_completion
    results: list[dict] = []
    tags = ["eval", "copepod", "plan-mode", "live", "du-only"]

    lf, eval_trace = _make_eval_trace(session_key, session_id, model_name, tags)

    log_dir = ROOT / "logs" / "evals"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"live_du_only_eval_{session_id}.log"

    client, stack = _test_client(store)
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== LIVE DU-ONLY EVAL {session_id} model={model_name} ===\n")
        log_fh.write(f"    file={ECOTAXA.name}  session={session_key}\n\n")
        log_fh.flush()
        try:
            with stack:
                upload = _stage_fixture(session_id, ECOTAXA)
                uploaded_ecotaxa_local, uploaded_ecotaxa_canonical = _uploaded_path_label(
                    session_id, upload["filename"]
                )
                tool_impls = _live_tool_impls(tools, session_key)
                messages: list[dict] = [
                    {
                        "role": "system",
                        "content": _build_eval_system_message(store, session_id),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"J'ai chargé un export EcoTaxa de la campagne Green Edge. "
                            f"Chemin réel à utiliser pour `inspect_file` : `{uploaded_ecotaxa_local}`. "
                            f"Chemin canonique du projet : `{uploaded_ecotaxa_canonical}`. "
                            "Je veux explorer comment les organismes planctoniques se répartissent en profondeur. "
                            "Commence par analyser le fichier."
                        ),
                    },
                ]
                base_metadata = {
                    "session_id": session_key,
                    "tags": tags,
                    "dataset": DATASET_NAME,
                }

                log_fh.write("--- PHASE 1: du-draft ---\n")
                log_fh.flush()
                du_span = eval_trace.span(name="phase/du-draft", input={"phase": "data-understanding-draft"}) if eval_trace else None
                first_reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "du-draft", "lf_phase_span": du_span},
                    log_fh=log_fh,
                )
                du_versions = store.get_artifact_versions(session_key, "data_understanding")
                du_draft = du_versions[-1] if du_versions else None
                results.append(_result(
                    "live_du_only_created_data_understanding_draft",
                    du_draft is not None and du_draft.get("status") == "draft",
                    "LLM created a draft Data Understanding artifact during Phase 1.",
                    {"case_type": "live", "model": model_name, "reply": first_reply[:500]},
                ))
                results.append(_result(
                    "live_du_only_waited_for_data_understanding_confirmation",
                    store.get_active_artifact(session_key, "data_understanding") is None
                    and store.get_artifact_versions(session_key, "graph_context") == [],
                    "LLM did not activate DU or create Graph Context before user confirmation.",
                    {"case_type": "live", "model": model_name},
                ))

                phase1_msgs = messages[2:]
                phase1_rounds = sum(1 for m in phase1_msgs if m.get("role") == "assistant")
                describe_calls = sum(
                    1
                    for m in phase1_msgs
                    if m.get("role") == "assistant"
                    for tc in (m.get("tool_calls") or [])
                    if (_tool_call_to_dict(tc).get("function") or {}).get("name") == "describe_column"
                )
                unmatched_count = 0
                for m in phase1_msgs:
                    if m.get("role") == "tool" and m.get("name") == "infer_column_roles":
                        unmatched_count = len(json.loads(m.get("content", "{}")).get("unmatched_columns", []))
                        break
                results.append(_result(
                    "live_du_only_phase1_efficient",
                    phase1_rounds <= 10,
                    f"Phase 1 completed in {phase1_rounds} rounds (limit: 10).",
                    {"case_type": "edge", "rounds": phase1_rounds},
                ))
                du_payload = (du_draft.get("payload") or {}) if du_draft else {}
                results.append(_result(
                    "live_du_only_payload_has_column_catalogue",
                    bool(du_payload.get("column_catalogue")),
                    f"DU artifact payload contains column_catalogue with {len(du_payload.get('column_catalogue') or [])} entries.",
                    {"case_type": "edge"},
                ))
                coverage_assessment = du_payload.get("coverage_assessment") or {}
                results.append(_result(
                    "live_du_only_payload_has_sufficient_coverage",
                    coverage_assessment.get("status") == "sufficient",
                    f"DU artifact coverage status is {coverage_assessment.get('status')!r}.",
                    {"case_type": "edge", "coverage": coverage_assessment},
                ))
                results.append(_result(
                    "live_du_only_describe_column_covered_all_unmatched",
                    unmatched_count == 0 or describe_calls >= unmatched_count,
                    f"describe_column called {describe_calls}× for {unmatched_count} unmatched columns.",
                    {"case_type": "edge", "describe_calls": describe_calls, "unmatched_count": unmatched_count},
                ))

                messages.append(
                    {
                        "role": "user",
                        "content": "Oui, c'est correct. Je confirme l'analyse du fichier.",
                    }
                )
                if du_span is not None:
                    du_span.end()

                log_fh.write("--- PHASE 2: du-confirmation ---\n")
                log_fh.flush()
                confirm_span = eval_trace.span(name="phase/du-confirmation", input={"phase": "du-confirmation"}) if eval_trace else None
                second_reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "du-confirmation", "lf_phase_span": confirm_span},
                    log_fh=log_fh,
                )
                active_du = store.get_active_artifact(session_key, "data_understanding")
                results.append(_result(
                    "live_du_only_activated_data_understanding",
                    active_du is not None
                    and du_draft is not None
                    and active_du.get("version_id") == du_draft.get("version_id"),
                    "LLM activated the confirmed Data Understanding.",
                    {"case_type": "live", "model": model_name, "reply": second_reply[:500]},
                ))
                results.append(_result(
                    "live_du_only_no_graph_context_created",
                    store.get_artifact_versions(session_key, "graph_context") == [],
                    "No Graph Context was created in DU-only mode.",
                    {"case_type": "edge"},
                ))

                _FORBIDDEN_USER_TERMS = [
                    "graph context", "plan_ready", "analyse mode", "version_id",
                ]
                all_llm_text = "\n".join([first_reply, second_reply]).lower()
                leaked = [t for t in _FORBIDDEN_USER_TERMS if t in all_llm_text]
                results.append(_result(
                    "live_du_only_no_internal_terms_in_llm_text",
                    not leaked,
                    (
                        "No forbidden downstream terms in LLM text."
                        if not leaked
                        else f"LLM leaked internal terms: {leaked}"
                    ),
                    {"case_type": "edge", "leaked": leaked},
                ))

                if confirm_span is not None:
                    confirm_span.end()

        except Exception as exc:
            import traceback
            log_fh.write(f"\n[CRASH] {type(exc).__name__}: {exc}\n")
            log_fh.write(traceback.format_exc())
            log_fh.flush()
            raise
        finally:
            passed_count = sum(1 for r in results if r["passed"])
            log_fh.write(f"\n=== SCORES {passed_count}/{len(results)} ===\n")
            for r in results:
                log_fh.write(f"  {'PASS' if r['passed'] else 'FAIL'} {r['name']}\n")
                if not r["passed"]:
                    log_fh.write(f"       {r['detail']}\n")
            log_fh.write(f"\nlog: {log_path}\n")
            log_fh.flush()

    passed_count = sum(1 for result in results if result["passed"])
    trace_url = _close_eval_trace(lf, eval_trace, results, push_scores=push_langfuse)
    _cleanup_old_logs(log_dir, "live_du_only_eval_")
    print(f"eval log → {log_path}")
    report = {
        "dataset": DATASET_NAME,
        "mode": "live-du-only",
        "model": model_name,
        "session_id": session_id,
        "session_key": session_key,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": trace_url,
    }
    return report


def run_live_gc_only_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
    scenario_slugs: list[str] | None = None,
) -> dict:
    """Run the live LLM through Graph Context only, starting from an already active DU."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"gc-only-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    model_name = settings.LLM_MODEL
    completion_fn = completion_fn or _default_live_completion
    results: list[dict] = []
    tags = ["eval", "copepod", "plan-mode", "live", "gc-only"]
    phase1_tool_names = {
        "inspect_file",
        "infer_column_roles",
        "describe_column",
        "summarize_understanding",
        "create_data_understanding_draft",
    }
    forbidden_terms = [
        "data understanding",
        "graph context",
        "version_id",
        "du-",
        "gc-",
    ]

    def _looks_like_self_introduction(text: str) -> bool:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in [
                "je suis le copepod graphing assistant",
                "je suis un assistant",
                "je suis l'assistant",
                "spécialisé dans",
                "specialisé dans",
                "i am the",
                "i’m the",
                "i am an assistant",
            ]
        )

    def _looks_like_targeted_context_question(text: str) -> bool:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in [
                "objectif",
                "contexte",
                "question",
                "précision",
                "precision",
                "graphe",
                "graphique",
                "explorer",
                "clarifier",
                "cadrer",
                "quelle",
            ]
        )

    lf, eval_trace = _make_eval_trace(session_key, session_id, model_name, tags)

    log_dir = ROOT / "logs" / "evals"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"live_gc_only_eval_{session_id}.log"

    client, stack = _test_client(store)

    def _scenario_turn(
        *,
        scenario_slug: str,
        scenario_label: str,
        scenario_session_id: str,
        scenario_session_key: str,
        user_messages: list[str],
        seed_paths: list[Path],
        should_confirm_gc: bool = False,
    ) -> dict[str, Any]:
        seed = _seed_active_data_understanding(
            client=client,
            tools=tools,
            session_id=scenario_session_id,
            session_key=scenario_session_key,
            fixture_paths=seed_paths,
        )
        messages: list[dict] = [
            {
                "role": "system",
                "content": _build_gc_only_system_message(store, scenario_session_id),
            }
        ]
        tool_calls_seen: list[str] = []
        replies: list[str] = []
        phase1_attempts = 0
        phase1_blocked = 0
        question_marks = 0

        base_metadata = {
            "session_id": scenario_session_key,
            "tags": tags + [scenario_slug],
            "dataset": DATASET_NAME,
            "scenario": scenario_slug,
        }

        def _run_turn(turn_label: str, user_text: str, span_name: str) -> str:
            messages.append({"role": "user", "content": user_text})
            span = eval_trace.span(name=span_name, input={"scenario": scenario_slug, "turn": turn_label}) if eval_trace else None
            reply = _run_llm_turn(
                messages=messages,
                tool_impls=_gc_only_tool_impls(tools, scenario_session_key),
                model=model_name,
                completion_fn=completion_fn,
                metadata={**base_metadata, "phase": turn_label, "lf_phase_span": span},
                tool_specs=_gc_only_tool_specs(),
                log_fh=log_fh,
            )
            if span is not None:
                span.end()
            replies.append(reply)
            return reply

        try:
            first_reply = _run_turn("gc-only-turn-1", user_messages[0], f"phase/gc-only/{scenario_slug}/turn-1")
            if "?" in first_reply:
                question_marks += 1
            if should_confirm_gc and len(user_messages) > 1:
                second_reply = _run_turn("gc-only-turn-2", user_messages[1], f"phase/gc-only/{scenario_slug}/turn-2")
                if "?" in second_reply:
                    question_marks += 1
            for message in messages:
                if message.get("role") == "tool" and message.get("name") in phase1_tool_names:
                    phase1_attempts += 1
                    if message.get("content") and "blocking_reason" in message["content"]:
                        phase1_blocked += 1
            gc_versions = store.get_artifact_versions(scenario_session_key, "graph_context")
            active_du = seed["active"] if isinstance(seed, dict) else None
            active_gc = store.get_active_artifact(scenario_session_key, "graph_context")
            return {
                "session_key": scenario_session_key,
                "replies": replies,
                "messages": messages,
                "active_du": active_du,
                "active_gc": active_gc,
                "gc_versions": gc_versions,
                "phase1_attempts": phase1_attempts,
                "phase1_blocked": phase1_blocked,
                "question_marks": question_marks,
            }
        except Exception as exc:
            raise RuntimeError(f"GC-only scenario {scenario_label} failed: {exc}") from exc

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== LIVE GC-ONLY EVAL {session_id} model={model_name} ===\n")
        log_fh.write("    seeds=EcoTaxa+EcoPart  scope=GraphContext-only\n\n")
        log_fh.flush()
        try:
            with stack:
                scenario_specs = [
                    {
                        "slug": "rich",
                        "label": "Contexte riche",
                        "seed_paths": [ECOTAXA, ECOPART],
                        "user_messages": [
                            (
                                "Le DU est déjà validé. Je veux une distribution verticale "
                                "de la biomasse des copépodes sur EcoTaxa + EcoPart, en mètres, "
                                "avec un histogramme vertical en Python, sortie png + csv. "
                                "Prépare le contexte scientifique."
                            ),
                            "Oui, c'est correct. Tu peux activer le contexte graphique.",
                        ],
                        "should_confirm_gc": True,
                    },
                    {
                        "slug": "poor",
                        "label": "Contexte pauvre",
                        "seed_paths": [ECOTAXA, ECOPART],
                        "user_messages": [
                            (
                                "Je veux faire un graphe de la campagne, "
                                "mais je n'ai pas encore fixé les unités ni le type de graphique."
                            )
                        ],
                        "should_confirm_gc": False,
                    },
                    {
                        "slug": "offtopic",
                        "label": "Hors sujet",
                        "seed_paths": [ECOTAXA, ECOPART],
                        "user_messages": [
                            "Parle-moi plutôt des copépodes en général, sans graphique."
                        ],
                        "should_confirm_gc": False,
                    },
                    {
                        "slug": "analysis-jump",
                        "label": "Saut vers analyse",
                        "seed_paths": [ECOTAXA, ECOPART],
                        "user_messages": [
                            "Fais directement le code Python pour l'analyse et le graphique."
                        ],
                        "should_confirm_gc": False,
                    },
                    {
                        "slug": "join",
                        "label": "Jointure implicite",
                        "seed_paths": [ECOTAXA, ECOPART],
                        "user_messages": [
                            (
                                "Je veux joindre EcoTaxa et EcoPart pour explorer la relation "
                                "entre organismes et particules en profondeur, mais la clé de jointure "
                                "n'est pas encore fixée."
                            )
                        ],
                        "should_confirm_gc": False,
                    },
                ]

                if scenario_slugs:
                    wanted = {slug.strip() for slug in scenario_slugs if slug.strip()}
                    scenario_specs = [spec for spec in scenario_specs if spec["slug"] in wanted]
                    if not scenario_specs:
                        raise ValueError(
                            f"No GC-only scenarios matched {sorted(wanted)!r}. "
                            "Available: rich, poor, offtopic, analysis-jump, join."
                        )

                scenario_states = []
                for spec in scenario_specs:
                    scenario_session_id = f"{session_id}-{spec['slug']}"
                    scenario_session_key = f"eval-user:{scenario_session_id}:copepod"
                    log_fh.write(f"--- SCENARIO: {spec['slug']} ---\n")
                    log_fh.flush()
                    state = _scenario_turn(
                        scenario_slug=spec["slug"],
                        scenario_label=spec["label"],
                        scenario_session_id=scenario_session_id,
                        scenario_session_key=scenario_session_key,
                        user_messages=spec["user_messages"],
                        seed_paths=spec["seed_paths"],
                        should_confirm_gc=spec["should_confirm_gc"],
                    )
                    scenario_states.append((spec, state))
                    first_reply = state["replies"][0] if state["replies"] else ""
                    second_reply = state["replies"][1] if len(state["replies"]) > 1 else ""

                    phase1_reopened = any(
                        m.get("role") == "tool"
                        and m.get("name") in phase1_tool_names
                        for m in state["messages"]
                    )
                    gc_draft_created = bool(state["gc_versions"])
                    gc_activated = bool(state["active_gc"])
                    plan_ready_emitted = any("[PLAN_READY]" in reply for reply in state["replies"])
                    analysis_refusal = (
                        "Plan Mode" in first_reply
                        or "plan mode" in first_reply.lower()
                        or "Je suis en Plan Mode" in first_reply
                    )
                    offtopic_reply = first_reply.lower()
                    targeted_question = (
                        "?" in first_reply
                        or _looks_like_targeted_context_question(first_reply)
                    ) and not gc_draft_created
                    if spec["slug"] == "rich" and len(state["replies"]) > 1:
                        gc_draft_created = gc_draft_created or "create_graph_context_draft" in "".join(
                            m.get("name", "") for m in state["messages"] if m.get("role") == "tool"
                        )

                    results.append(_result(
                        f"gc_only_{spec['slug']}_never_reopened_phase1",
                        not phase1_reopened,
                        f"Scenario {spec['slug']} did not reopen Phase 1.",
                        {"case_type": "edge", "scenario": spec["slug"], "phase1_attempts": state["phase1_attempts"]},
                    ))
                    if spec["slug"] == "poor" or spec["slug"] == "offtopic" or spec["slug"] == "join":
                        is_offtopic_ok = (
                            not _looks_like_self_introduction(first_reply)
                            and (targeted_question or "objectif scientifique" in offtopic_reply or "contexte" in offtopic_reply)
                            and first_reply.count("?") <= 2
                        )
                        is_poor_or_join_ok = (
                            (targeted_question or "objectif scientifique" in offtopic_reply or "quelle" in offtopic_reply)
                            and first_reply.count("?") <= 2
                        )
                        results.append(_result(
                            f"gc_only_{spec['slug']}_asked_single_targeted_question_when_missing_fields",
                            is_offtopic_ok if spec["slug"] == "offtopic" else is_poor_or_join_ok,
                            f"Scenario {spec['slug']} replied with a targeted question: {first_reply[:200]!r}",
                            {"case_type": "common", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] == "join":
                        join_starts_with_config = first_reply.lstrip().startswith("### Configuration du graphique")
                        results.append(_result(
                            "gc_only_join_did_not_start_configuration_before_join_strategy",
                            not join_starts_with_config,
                            f"Join scenario should clarify before drafting a configuration. First reply: {first_reply[:240]!r}",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] == "analysis-jump":
                        results.append(_result(
                            "gc_only_refused_direct_analysis_request_before_gc",
                            analysis_refusal and not state["phase1_attempts"],
                            f"Scenario analysis-jump refused direct analysis: {first_reply[:240]!r}",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] == "rich":
                        results.append(_result(
                            "gc_only_rich_created_graph_context_draft",
                            gc_draft_created,
                            "Scenario rich created a Graph Context draft.",
                            {"case_type": "common", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] in {"poor", "offtopic", "analysis-jump", "join"}:
                        results.append(_result(
                            f"gc_only_{spec['slug']}_created_graph_context_draft",
                            not gc_draft_created,
                            f"Scenario {spec['slug']} did not create a Graph Context draft.",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] == "rich":
                        results.append(_result(
                            "gc_only_rich_activated_graph_context",
                            gc_activated,
                            "Rich-context scenario activated the Graph Context after confirmation.",
                            {"case_type": "common", "scenario": spec["slug"]},
                        ))
                        results.append(_result(
                            "gc_only_plan_ready_after_gc_activation",
                            gc_activated and plan_ready_emitted,
                            "PLAN_READY was emitted only after Graph Context activation.",
                            {"case_type": "common", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] in {"poor", "offtopic", "analysis-jump", "join"}:
                        results.append(_result(
                            f"gc_only_{spec['slug']}_did_not_emit_plan_ready",
                            not plan_ready_emitted,
                            f"Scenario {spec['slug']} did not emit PLAN_READY.",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))
                        results.append(_result(
                            f"gc_only_{spec['slug']}_did_not_activate_graph_context",
                            not gc_activated,
                            f"Scenario {spec['slug']} did not activate Graph Context.",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))
                    if spec["slug"] == "join":
                        join_text = "\n".join(state["replies"]).lower()
                        results.append(_result(
                            "gc_only_reasks_for_join_strategy_when_implicit",
                            "jointure" in join_text or "join" in join_text or "clé" in join_text,
                            f"Join scenario asked for or discussed a join strategy: {join_text[:240]!r}",
                            {"case_type": "edge", "scenario": spec["slug"]},
                        ))

                all_llm_text = "\n".join(
                    reply for _, state in scenario_states for reply in state["replies"]
                ).lower()
                leaked = [term for term in forbidden_terms if term in all_llm_text]
                results.append(_result(
                    "gc_only_no_internal_terms_in_llm_text",
                    not leaked,
                    (
                        "No forbidden downstream terms in LLM text."
                        if not leaked
                        else f"LLM leaked internal terms: {leaked}"
                    ),
                    {"case_type": "edge", "leaked": leaked},
                ))

        except Exception as exc:
            import traceback
            log_fh.write(f"\n[CRASH] {type(exc).__name__}: {exc}\n")
            log_fh.write(traceback.format_exc())
            log_fh.flush()
            raise
        finally:
            passed_count = sum(1 for r in results if r["passed"])
            log_fh.write(f"\n=== SCORES {passed_count}/{len(results)} ===\n")
            for r in results:
                log_fh.write(f"  {'PASS' if r['passed'] else 'FAIL'} {r['name']}\n")
                if not r["passed"]:
                    log_fh.write(f"       {r['detail']}\n")
            log_fh.write(f"\nlog: {log_path}\n")
            log_fh.flush()

    passed_count = sum(1 for result in results if result["passed"])
    trace_url = _close_eval_trace(lf, eval_trace, results, push_scores=push_langfuse)
    _cleanup_old_logs(log_dir, "live_gc_only_eval_")
    print(f"eval log → {log_path}")
    report = {
        "dataset": DATASET_NAME,
        "mode": "live-gc-only",
        "model": model_name,
        "session_id": session_id,
        "session_key": session_key,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": trace_url,
    }
    return report


def run_mock_eval(*, push_langfuse: bool = False) -> dict:
    """Run deterministic Plan Mode workflow checks without calling a real LLM."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    results: list[dict] = []

    client, stack = _test_client(store)
    with stack:
        upload = _stage_fixture(session_id, ECOTAXA)
        uploaded_ecotaxa = _uploaded_path(session_id, upload["filename"])
        du_artifact = _data_understanding_artifact(tools, uploaded_ecotaxa)
        du_draft = tools["create_data_understanding_draft"](session_key, du_artifact)

        results.append(_result(
            "upload_ecotaxa_creates_data_understanding",
            du_draft["status"] == "draft"
            and du_draft["payload"]["files"][0]["source_type_guess"]["value"] == "likely_ecotaxa",
            f"Data Understanding draft {du_draft['version_id']} created after upload.",
            {"case_type": "common", "version_id": du_draft["version_id"]},
        ))
        du_coverage = (du_draft.get("payload") or {}).get("coverage_assessment") or {}
        results.append(_result(
            "data_understanding_coverage_is_sufficient",
            du_coverage.get("status") == "sufficient",
            f"Data Understanding coverage status is {du_coverage.get('status')!r}.",
            {"case_type": "common", "coverage": du_coverage},
        ))

        blocked = _post_analyse(client, session_id)
        results.append(_result(
            "analyse_blocked_before_active_artifacts",
            blocked.status_code == 409,
            f"Analyse before active artifacts returned HTTP {blocked.status_code}.",
            {"case_type": "edge"},
        ))

        missing_du_ref = tools["create_graph_context_draft"](
            session_key,
            {"objective": "Distribution verticale sans référence DU"},
        )
        results.append(_result(
            "graph_context_without_data_understanding_version_is_blocked",
            missing_du_ref.get("created") is False
            and "data_understanding_version_id" in missing_du_ref.get("blocking_reason", ""),
            "Graph Context draft without DU version reference is rejected by the tool.",
            {"case_type": "edge"},
        ))

        premature_gc = tools["create_graph_context_draft"](
            session_key,
            {
                "data_understanding_version_id": du_draft["version_id"],
                "objective": "Tentative de saut de validation",
                "columns": ["object_depth_min"],
                "filters": [],
                "units": {"depth": "m"},
                "chart_type": "static vertical distribution",
                "language": "Python",
                "output_artifacts": ["png"],
                "feasibility": "blocked",
                "blockers": ["Data Understanding not confirmed"],
            },
        )
        results.append(_result(
            "phase_gate_blocks_graph_context_before_data_understanding_confirmation",
            premature_gc.get("created") is False
            and "graph_context_draft_required" in premature_gc.get("blocking_reason", ""),
            "Graph Context creation is rejected until Data Understanding has been activated.",
            {"case_type": "edge"},
        ))

        early_plan_ready_events = list(chat_stream_events(
            [{
                "start": True,
                "end": True,
                "role": "assistant",
                "type": "message",
                "content": "Contexte scientifique validé trop tôt. [PLAN_READY]",
            }],
            user_turns=2,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(store, session_key),
        ))
        results.append(_result(
            "plan_ready_button_not_emitted_before_minimum_turns",
            not any(event.get("type") == "action_button" for event in early_plan_ready_events),
            "PLAN_READY marker before the minimum user turns does not emit the Analyse button.",
            {"case_type": "edge"},
        ))

        premature_plan_ready_events = list(chat_stream_events(
            [{
                "start": True,
                "end": True,
                "role": "assistant",
                "type": "message",
                "content": "Contexte scientifique validé trop tôt. [PLAN_READY]",
            }],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(store, session_key),
        ))
        results.append(_result(
            "backend_phase_gate_blocks_premature_plan_ready_button",
            not any(event.get("type") == "action_button" for event in premature_plan_ready_events),
            "Backend phase state prevents a premature PLAN_READY marker from exposing Analyse.",
            {"case_type": "edge"},
        ))

        du_active = tools["activate_data_understanding"](session_key, du_draft["version_id"])
        results.append(_result(
            "data_understanding_confirmation_activates_artifact",
            du_active.get("status") == "active"
            and tools["get_active_data_understanding"](session_key)["version_id"] == du_active["version_id"],
            f"Data Understanding active version is {du_active.get('version_id')}.",
            {"case_type": "common", "version_id": du_active.get("version_id")},
        ))

        graph_context = {
            "data_understanding_version_id": du_active["version_id"],
            "objective": "Distribution verticale EcoTaxa",
            "columns": ["object_depth_min", "object_depth_max"],
            "filters": [],
            "units": {"depth": "m"},
            "chart_type": "static vertical distribution",
            "language": "Python",
            "output_artifacts": ["png", "metadata"],
            "feasibility": "exploratory",
            "blockers": [],
        }
        gc_draft = tools["create_graph_context_draft"](session_key, graph_context)
        results.append(_result(
            "graph_context_draft_links_to_active_du",
            gc_draft["status"] == "draft"
            and gc_draft["payload"]["data_understanding_version_id"] == du_active["version_id"],
            f"Graph Context draft {gc_draft['version_id']} references active DU.",
            {"case_type": "common", "version_id": gc_draft["version_id"]},
        ))

        gc_active = tools["activate_graph_context"](session_key, gc_draft["version_id"])
        stream_events = list(chat_stream_events(
            [{
                "start": True,
                "end": True,
                "role": "assistant",
                "type": "message",
                "content": "Contexte scientifique validé. [PLAN_READY]",
            }],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(store, session_key),
        ))
        analyse = _post_analyse(client, session_id)
        results.append(_result(
            "plan_ready_after_graph_context_activation",
            gc_active.get("status") == "active"
            and stream_events[-1].get("label") == "Passer en Mode Analyse"
            and analyse.status_code == 200,
            f"Graph Context active, PLAN_READY button emitted, analyse returned HTTP {analyse.status_code}.",
            {"case_type": "common", "version_id": gc_active.get("version_id")},
        ))

        upload_ecopart = _stage_fixture(session_id, ECOPART)
        uploaded_ecopart = _uploaded_path(session_id, upload_ecopart["filename"])
        new_du_draft = tools["create_data_understanding_draft"](
            session_key,
            _data_understanding_artifact(tools, uploaded_ecopart),
        )
        active_du_after_upload = tools["get_active_data_understanding"](session_key)
        active_gc_after_upload = tools["get_active_graph_context"](session_key)
        results.append(_result(
            "upload_in_analyse_creates_draft_without_replan",
            new_du_draft["status"] == "draft"
            and active_du_after_upload["version_id"] == du_active["version_id"]
            and active_gc_after_upload["version_id"] == gc_active["version_id"],
            "Upload in Analyse created a new DU draft without changing active DU or GC.",
            {"case_type": "common", "new_draft_version_id": new_du_draft["version_id"]},
        ))

        mismatch_session_id = f"eval-edge-{uuid.uuid4().hex[:8]}"
        mismatch_session_key = f"eval-user:{mismatch_session_id}:copepod"
        old_du = store.create_artifact_version(
            mismatch_session_key,
            "data_understanding",
            {"files": [{"original_filename": "old.tsv"}]},
        )
        current_du = store.create_artifact_version(
            mismatch_session_key,
            "data_understanding",
            {"files": [{"original_filename": "current.tsv"}]},
        )
        stale_gc = store.create_artifact_version(
            mismatch_session_key,
            "graph_context",
            {"data_understanding_version_id": old_du["version_id"]},
        )
        store.activate_artifact_version(
            mismatch_session_key,
            "data_understanding",
            current_du["version_id"],
        )
        store.activate_artifact_version(
            mismatch_session_key,
            "graph_context",
            stale_gc["version_id"],
        )
        mismatch_response = _post_analyse(client, mismatch_session_id)
        results.append(_result(
            "analyse_blocked_when_graph_context_references_stale_data_understanding",
            mismatch_response.status_code == 409,
            f"Stale Graph Context linkage returned HTTP {mismatch_response.status_code}.",
            {"case_type": "edge"},
        ))

        generic_debug = client.get(
            "/session/artifacts/data-understanding",
            headers={"x-session-id": session_id, "x-agent-type": "generic"},
        )
        results.append(_result(
            "artifact_debug_routes_are_copepod_only",
            generic_debug.status_code == 404,
            f"Generic agent artifact debug route returned HTTP {generic_debug.status_code}.",
            {"case_type": "edge"},
        ))

    passed_count = sum(1 for result in results if result["passed"])
    report = {
        "dataset": DATASET_NAME,
        "mode": "mock",
        "session_id": session_id,
        "session_key": session_key,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": None,
    }
    if push_langfuse:
        report["langfuse_trace_url"] = _push_scores_to_langfuse(session_key, results)
    return report


def _make_eval_trace(session_key: str, session_id: str, model_name: str, tags: list[str]):
    """Create the top-level Langfuse trace for one live eval run."""
    if not should_enable_langfuse():
        return None, None
    try:
        validate_langfuse_configuration()
        from langfuse import Langfuse
        _configure_local_langfuse_host()
        lf = Langfuse()
        trace = lf.trace(
            name="copepod-eval/live",
            user_id="eval-user",
            session_id=session_key,
            tags=tags,
            input={"model": model_name, "file": ECOTAXA.name, "session_id": session_id},
        )
        os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = trace.id
        return lf, trace
    except Exception:
        return None, None


def _close_eval_trace(lf, trace, results: list[dict], push_scores: bool = False) -> str | None:
    if trace is None or not should_enable_langfuse():
        return None
    try:
        passed = sum(1 for r in results if r["passed"])
        trace.update(
            output={"passed": passed, "total": len(results)},
            metadata={"dataset": DATASET_NAME},
        )
        if push_scores:
            for result in results:
                trace.score(
                    name=result["name"],
                    value=1.0 if result["passed"] else 0.0,
                    data_type="BOOLEAN",
                    comment=result["detail"],
                )
        lf.flush()
        os.environ.pop("COPEPOD_EVAL_LF_TRACE_ID", None)
        return _browser_trace_url(trace.get_trace_url())
    except Exception:
        return None


def run_live_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    """Run the Plan Mode workflow with a real LLM driving the artifact tools."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"live-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    model_name = settings.LLM_MODEL
    completion_fn = completion_fn or _default_live_completion
    results: list[dict] = []
    tags = ["eval", "copepod", "plan-mode", "live"]

    lf, eval_trace = _make_eval_trace(session_key, session_id, model_name, tags)

    log_dir = ROOT / "logs" / "evals"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"live_eval_{session_id}.log"

    client, stack = _test_client(store)
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== LIVE EVAL {session_id} model={model_name} ===\n")
        log_fh.write(f"    file={ECOTAXA.name}  session={session_key}\n\n")
        log_fh.flush()
        try:
            with stack:
                upload = _stage_fixture(session_id, ECOTAXA)
                uploaded_ecotaxa_local, uploaded_ecotaxa_canonical = _uploaded_path_label(
                    session_id, upload["filename"]
                )
                tool_impls = _live_tool_impls(tools, session_key)
                messages: list[dict] = [
                    {
                        "role": "system",
                        "content": _build_eval_system_message(store, session_id),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"J'ai chargé un export EcoTaxa de la campagne Green Edge. "
                            f"Chemin réel à utiliser pour `inspect_file` : `{uploaded_ecotaxa_local}`. "
                            f"Chemin canonique du projet : `{uploaded_ecotaxa_canonical}`. "
                            "Je veux explorer comment les organismes planctoniques se répartissent en profondeur. "
                            "Commence par analyser le fichier."
                        ),
                    },
                ]
                base_metadata = {
                    "session_id": session_key,
                    "tags": tags,
                    "dataset": DATASET_NAME,
                }

                log_fh.write("--- PHASE 1: du-draft ---\n")
                log_fh.flush()
                du_span = eval_trace.span(name="phase/du-draft", input={"phase": "data-understanding-draft"}) if eval_trace else None
                first_reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "du-draft", "lf_phase_span": du_span},
                    log_fh=log_fh,
                )
                du_versions = store.get_artifact_versions(session_key, "data_understanding")
                du_draft = du_versions[-1] if du_versions else None
                results.append(_result(
                    "live_llm_created_data_understanding_draft",
                    du_draft is not None and du_draft.get("status") == "draft",
                    "LLM created a draft Data Understanding artifact during Phase 1.",
                    {"case_type": "live", "model": model_name, "reply": first_reply[:500]},
                ))
                results.append(_result(
                    "live_llm_waited_for_data_understanding_confirmation",
                    store.get_active_artifact(session_key, "data_understanding") is None
                    and store.get_artifact_versions(session_key, "graph_context") == [],
                    "LLM did not activate DU or create Graph Context before user confirmation.",
                    {"case_type": "live", "model": model_name},
                ))

                # --- edge cases: phase 1 quality & efficiency ---
                phase1_msgs = messages[2:]  # skip system + first user
                phase1_rounds = sum(1 for m in phase1_msgs if m.get("role") == "assistant")
                describe_calls = sum(
                    1
                    for m in phase1_msgs
                    if m.get("role") == "assistant"
                    for tc in (m.get("tool_calls") or [])
                    if (_tool_call_to_dict(tc).get("function") or {}).get("name") == "describe_column"
                )
                unmatched_count = 0
                for m in phase1_msgs:
                    if m.get("role") == "tool" and m.get("name") == "infer_column_roles":
                        unmatched_count = len(json.loads(m.get("content", "{}")).get("unmatched_columns", []))
                        break
                results.append(_result(
                    "live_describe_column_covered_all_unmatched",
                    describe_calls >= unmatched_count > 0,
                    f"describe_column called {describe_calls}× for {unmatched_count} unmatched columns.",
                    {"case_type": "edge", "describe_calls": describe_calls, "unmatched_count": unmatched_count},
                ))
                results.append(_result(
                    "live_phase1_efficient",
                    phase1_rounds <= 10,
                    f"Phase 1 completed in {phase1_rounds} rounds (limit: 10).",
                    {"case_type": "edge", "rounds": phase1_rounds},
                ))
                du_payload = (du_draft.get("payload") or {}) if du_draft else {}
                has_catalogue = (
                    "column_catalogue" in du_payload
                    and bool(du_payload["column_catalogue"])
                )
                results.append(_result(
                    "live_du_payload_has_column_catalogue",
                    has_catalogue,
                    f"DU artifact payload contains column_catalogue with {len(du_payload.get('column_catalogue') or [])} entries.",
                    {"case_type": "edge"},
                ))
                coverage_assessment = du_payload.get("coverage_assessment") or {}
                results.append(_result(
                    "live_du_payload_has_sufficient_coverage",
                    coverage_assessment.get("status") == "sufficient",
                    f"DU artifact coverage status is {coverage_assessment.get('status')!r}.",
                    {"case_type": "edge", "coverage": coverage_assessment},
                ))

                # --- unpredictable input: casual/ambiguous confirmation ---
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Oui, c'est correct. "
                            "Je veux explorer la distribution verticale des organismes par profondeur. "
                            "Vas-y pour la configuration du graphique."
                        ),
                    }
                )
                if du_span is not None:
                    du_span.end()

                log_fh.write("--- PHASE 2: gc-draft ---\n")
                log_fh.flush()
                gc_span = eval_trace.span(name="phase/gc-draft", input={"phase": "graph-context-draft"}) if eval_trace else None
                second_reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "gc-draft", "lf_phase_span": gc_span},
                    log_fh=log_fh,
                )
                active_du = store.get_active_artifact(session_key, "data_understanding")
                gc_versions = store.get_artifact_versions(session_key, "graph_context")
                gc_draft = gc_versions[-1] if gc_versions else None
                results.append(_result(
                    "live_llm_activated_data_understanding",
                    active_du is not None and active_du.get("version_id") == du_draft.get("version_id") if du_draft else False,
                    "LLM activated the confirmed Data Understanding.",
                    {"case_type": "live", "model": model_name},
                ))
                results.append(_result(
                    "live_llm_created_graph_context_draft_linked_to_active_du",
                    active_du is not None
                    and gc_draft is not None
                    and gc_draft.get("status") == "draft"
                    and gc_draft.get("payload", {}).get("data_understanding_version_id")
                    == active_du.get("version_id"),
                    "LLM created a Graph Context draft linked to active Data Understanding.",
                    {"case_type": "live", "model": model_name, "reply": second_reply[:500]},
                ))
                premature_events = list(chat_stream_events(
                    [{
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "message",
                        "content": second_reply,
                    }],
                    user_turns=3,
                    session_mode="plan",
                    plan_ready_allowed=_plan_ready_allowed(store, session_key),
                ))
                premature_button_emitted = any(event.get("type") == "action_button" for event in premature_events)
                premature_plan_ready_marker = "[PLAN_READY]" in second_reply
                results.append(_result(
                    "live_llm_did_not_emit_plan_ready_before_graph_context_confirmation",
                    not premature_plan_ready_marker,
                    "LLM text did not contain PLAN_READY before Graph Context confirmation.",
                    {"case_type": "live", "model": model_name, "reply": second_reply[:500]},
                ))
                results.append(_result(
                    "live_backend_blocked_premature_plan_ready_button",
                    not premature_button_emitted,
                    "Backend phase state prevented premature Analyse button exposure.",
                    {"case_type": "live", "model": model_name},
                ))
                results.append(_result(
                    "live_llm_waited_for_graph_context_confirmation",
                    store.get_active_artifact(session_key, "graph_context") is None
                    and not premature_button_emitted,
                    "LLM did not activate GC or expose Analyse before graph context confirmation.",
                    {"case_type": "live", "model": model_name},
                ))

                # --- edge case: GC artifact has all required fields ---
                gc_payload = (gc_draft.get("payload") or {}) if gc_draft else {}
                required_gc_fields = {
                    "data_understanding_version_id", "objective", "columns", "filters",
                    "units", "chart_type", "language", "output_artifacts", "feasibility", "blockers",
                }
                missing_gc_fields = required_gc_fields - gc_payload.keys()
                results.append(_result(
                    "live_gc_payload_has_all_required_fields",
                    not missing_gc_fields,
                    f"GC artifact has all required fields. Missing: {sorted(missing_gc_fields) or 'none'}.",
                    {"case_type": "edge", "missing": sorted(missing_gc_fields)},
                ))

                # --- unpredictable input: terse/ambiguous phase 3 confirmation ---
                messages.append(
                    {
                        "role": "user",
                        "content": "Ok, c'est bon pour moi.",
                    }
                )
                if gc_span is not None:
                    gc_span.end()

                log_fh.write("--- PHASE 3: plan-ready ---\n")
                log_fh.flush()
                pr_span = eval_trace.span(name="phase/plan-ready", input={"phase": "plan-ready"}) if eval_trace else None
                final_reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "plan-ready", "lf_phase_span": pr_span},
                    log_fh=log_fh,
                )
                active_gc = store.get_active_artifact(session_key, "graph_context")
                stream_events = list(chat_stream_events(
                    [{
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "message",
                        "content": final_reply,
                    }],
                    user_turns=3,
                    session_mode="plan",
                    plan_ready_allowed=_plan_ready_allowed(store, session_key),
                ))
                analyse = _post_analyse(client, session_id)
                results.append(_result(
                    "live_llm_activated_graph_context",
                    active_du is not None
                    and active_gc is not None
                    and active_gc.get("payload", {}).get("data_understanding_version_id")
                    == active_du.get("version_id"),
                    "LLM activated Graph Context linked to active Data Understanding.",
                    {"case_type": "live", "model": model_name},
                ))
                results.append(_result(
                    "live_plan_ready_enables_analyse_mode",
                    any(event.get("type") == "action_button" for event in stream_events)
                    and analyse.status_code == 200,
                    f"PLAN_READY emitted Analyse button and /session/mode returned HTTP {analyse.status_code}.",
                    {"case_type": "live", "model": model_name, "reply": final_reply[:500]},
                ))

                _FORBIDDEN_USER_TERMS = [
                    "data understanding", "graph context",
                    "version_id", "du-", "gc-",
                ]
                all_llm_text = "\n".join([first_reply, second_reply, final_reply]).lower()
                leaked = [t for t in _FORBIDDEN_USER_TERMS if t in all_llm_text]
                results.append(_result(
                    "live_no_internal_terms_in_llm_text",
                    not leaked,
                    (
                        "No internal artifact terms in LLM text."
                        if not leaked
                        else f"LLM leaked internal terms: {leaked}"
                    ),
                    {"case_type": "live", "model": model_name, "leaked": leaked},
                ))

                if pr_span is not None:
                    pr_span.end()

        except Exception as exc:
            import traceback
            log_fh.write(f"\n[CRASH] {type(exc).__name__}: {exc}\n")
            log_fh.write(traceback.format_exc())
            log_fh.flush()
            raise
        finally:
            passed_count = sum(1 for r in results if r["passed"])
            log_fh.write(f"\n=== SCORES {passed_count}/{len(results)} ===\n")
            for r in results:
                log_fh.write(f"  {'PASS' if r['passed'] else 'FAIL'} {r['name']}\n")
                if not r["passed"]:
                    log_fh.write(f"       {r['detail']}\n")
            log_fh.write(f"\nlog: {log_path}\n")
            log_fh.flush()

    passed_count = sum(1 for result in results if result["passed"])
    trace_url = _close_eval_trace(lf, eval_trace, results, push_scores=push_langfuse)
    _cleanup_old_logs(log_dir, "live_eval_")
    print(f"eval log → {log_path}")
    report = {
        "dataset": DATASET_NAME,
        "mode": "live",
        "model": model_name,
        "session_id": session_id,
        "session_key": session_key,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": trace_url,
    }
    return report


def _print_report(report: dict) -> None:
    print(f"{report['dataset']} ({report['mode']})")
    print()
    if report["mode"] == "trace-smoke":
        status = "PASS" if report["passed"] else "FAIL"
        print(f"{status} trace_smoke_prompt_returned_output")
        print(f"     {report['response']}")
        if report.get("langfuse_trace_url"):
            print(f"Langfuse trace: {report['langfuse_trace_url']}")
        return
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {result['name']}")
        print(f"     {result['detail']}")
    print()
    print(f"{report['passed_count']}/{report['total_count']} passed")
    if report.get("langfuse_trace_url"):
        print(f"Langfuse trace: {report['langfuse_trace_url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Copepod Plan Mode workflow evals.")
    parser.add_argument("--mock", action="store_true", help="Run deterministic no-LLM evals.")
    parser.add_argument("--live-gc-only", action="store_true", help="Run live LLM evals through Graph Context only.")
    parser.add_argument("--live-du-only", action="store_true", help="Run live LLM evals through Data Understanding only.")
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven evals.")
    parser.add_argument("--trace-smoke", action="store_true", help="Send one prompt and verify Langfuse trace/level/score.")
    parser.add_argument(
        "--prompt",
        default="Dis simplement que la trace Langfuse fonctionne.",
        help="Prompt for --trace-smoke.",
    )
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument(
        "--gc-scenarios",
        default="",
        help="Comma-separated GC-only scenario slugs to run (rich,poor,offtopic,analysis-jump,join).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    if args.trace_smoke:
        report = run_langfuse_trace_smoke(prompt=args.prompt)
    elif args.live_gc_only:
        scenario_slugs = [slug.strip() for slug in args.gc_scenarios.split(",") if slug.strip()]
        report = run_live_gc_only_eval(
            push_langfuse=args.push_langfuse,
            scenario_slugs=scenario_slugs or None,
        )
    elif args.live_du_only:
        report = run_live_du_only_eval(push_langfuse=args.push_langfuse)
    elif args.live:
        report = run_live_eval(push_langfuse=args.push_langfuse)
    else:
        report = run_mock_eval(push_langfuse=args.push_langfuse)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
