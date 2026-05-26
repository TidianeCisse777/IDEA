from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
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
from core.session_store import InMemorySessionStore
from routers.file_routes import router as file_router
from routers.session_routes import router as session_router

import core.instruction_renderer.blocks.copepod_mode_plan  # noqa: F401
import core.instruction_renderer.blocks.copepod_tool_signatures  # noqa: F401
from core.copepod_plan_workflow import PLAN_READY


DATASET_NAME = "copepod-plan-mode-v1"
LIVE_OPENAI_TIMEOUT_SECONDS = float(os.getenv("COPEPOD_LIVE_OPENAI_TIMEOUT_SECONDS", "120"))
FIXTURES = Path(
    "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv"
)
ECOTAXA = FIXTURES / "ecotaxa_sample_50.tsv"
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


def _upload_fixture(client: TestClient, session_id: str, path: Path) -> dict:
    with path.open("rb") as handle:
        response = client.post(
            "/upload",
            files={"file": (path.name, handle, "text/tab-separated-values")},
            headers={"x-session-id": session_id, "x-agent-type": "copepod"},
        )
    if response.status_code != 200:
        raise AssertionError(f"Upload failed for {path.name}: {response.status_code} {response.text}")
    return response.json()


def _uploaded_path(session_id: str, filename: str) -> Path:
    return Path("static") / "eval-user" / session_id / "uploads" / filename


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
            "possible_joins_or_couplings": summary["possible_joins_or_couplings"],
            "missing_or_ambiguous_data": summary["missing_or_ambiguous_data"],
        },
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


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _configure_local_langfuse_host() -> None:
    """Use the host-mapped Langfuse URL when running from the local shell."""
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or ""
    if "://langfuse:3000" not in host:
        return
    try:
        req = Request("http://localhost:3001/api/public/projects", method="GET")
        urlopen(req, timeout=2)
    except Exception as exc:
        if getattr(exc, "code", None) not in {200, 401}:
            return
    os.environ["LANGFUSE_HOST"] = "http://localhost:3001"
    os.environ["LANGFUSE_BASE_URL"] = "http://localhost:3001"


def _compact_tool_result(name: str | None, result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if name == "inspect_file":
        cols = result.get("columns") or []
        slim_cols = [
            {k: v for k, v in col.items() if k != "sample_values"}
            for col in cols
        ]
        return {
            "metadata": result.get("metadata"),
            "columns": slim_cols,
            "source_type_guess": result.get("source_type_guess"),
        }
    if name in {
        "create_data_understanding_draft",
        "activate_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_data_understanding",
        "get_active_graph_context",
    }:
        return {
            "version_id": result.get("version_id"),
            "artifact_type": result.get("artifact_type"),
            "status": result.get("status"),
            "payload": result.get("payload"),
            "created_at": result.get("created_at"),
            "activated_at": result.get("activated_at"),
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


def _live_tool_impls(tools: dict[str, Any], session_key: str) -> dict[str, Callable[..., Any]]:
    session_scoped = {
        "create_data_understanding_draft",
        "activate_data_understanding",
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
    }

    def call_tool(name: str, arguments: dict) -> Any:
        if name in session_scoped:
            arguments = {**arguments, "session_key": session_key}
        if name == "describe_column" and not arguments.get("session_id"):
            arguments["session_id"] = session_key.split(":")[1]
        return tools[name](**arguments)

    return {name: (lambda _name=name, **kwargs: call_tool(_name, kwargs)) for name in {
        "inspect_file",
        "infer_column_roles",
        "describe_column",
        "summarize_understanding",
        "create_data_understanding_draft",
        "activate_data_understanding",
        "get_active_data_understanding",
        "create_graph_context_draft",
        "activate_graph_context",
        "get_active_graph_context",
    }}


def _run_llm_turn(
    *,
    messages: list[dict],
    tool_impls: dict[str, Callable[..., Any]],
    model: str,
    completion_fn: Callable[..., Any],
    metadata: dict,
    max_tool_rounds: int = 40,
    log_fh=None,
) -> str:
    phase = metadata.get("phase", "?")

    def _log(line: str):
        if log_fh is not None:
            log_fh.write(line + "\n")
            log_fh.flush()

    last_content = ""
    for round_index in range(max_tool_rounds):
        for attempt in range(2):
            try:
                response = completion_fn(
                    model=model,
                    messages=messages,
                    tools=_tool_specs(),
                    tool_choice="auto",
                    temperature=float(os.getenv("LLM_TEMPERATURE", settings.LLM_TEMPERATURE)),
                    metadata={**metadata, "round": round_index + 1},
                )
                break
            except Exception as exc:
                _log(f"  [ERROR] phase={phase} round={round_index+1} llm_exception={exc}")
                if attempt == 0 and "rate limit" in str(exc).lower():
                    time.sleep(12)
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
        max_tokens=4000,
    )
    message = _message_to_dict(_completion_message(response))

    if lf_phase_span is not None:
        try:
            usage = getattr(response, "usage", None)
            usage_details = None
            if usage is not None:
                usage_details = {
                    "input": getattr(usage, "prompt_tokens", 0) or 0,
                    "output": getattr(usage, "completion_tokens", 0) or 0,
                    "total": getattr(usage, "total_tokens", 0) or 0,
                }
            tool_calls_out = message.get("tool_calls") or []
            tool_names_out = [c.get("function", {}).get("name") for c in tool_calls_out]
            lf_phase_span.generation(
                name=f"round-{round_index}",
                model=model,
                input={"messages": messages[-2:] if messages else [], "tools_count": len(tools or [])},
                output={"tool_calls": tool_names_out, "content": message.get("content") or ""},
                usage_details=usage_details,
                level="DEFAULT",
                metadata={"phase": phase, "round": round_index, "tool_calls": tool_names_out},
            )
        except Exception:
            pass

    return response


def _live_eval_system_prompt(session_id: str) -> str:
    session_key = f"eval-user:{session_id}:copepod"
    return f"""You are IDEA Copepod Plan Mode under live evaluation.

Use this exact session key for artifact tools: `{session_key}`.

CRITICAL RULE: Steps a, b, d, e must be called ONE at a time. Step c is the only exception — call ALL describe_column in a single response.

Mandatory workflow:
1. First assistant turn — call tools in this exact order:
   a. Call `inspect_file` alone. Wait for result.
   b. Call `infer_column_roles` with the columns from step a. Wait for result.
   c. Call `describe_column` for ALL columns listed in `unmatched_columns` — all in ONE response (multiple tool calls at once). Do not skip any unmatched column. Wait for all results.
   d. Call `summarize_understanding` alone with: `inspect_report` (step a), `role_report` (step b), `column_definitions` (ALL describe_column results from step c). Wait for result.
   e. Call `create_data_understanding_draft` alone with the summary. Wait for result.
   Then show a short Data Understanding summary and stop. Do not activate DU. Do not create Graph Context.
2. After the user confirms Data Understanding — call tools sequentially:
   a. Call `activate_data_understanding`. Wait for result.
   b. Call `get_active_data_understanding`. Wait for result.
   c. Call `create_graph_context_draft` linked to the active DU version_id. Wait for result.
   Then show a short Graph Context summary and stop. Do not activate GC. Do not emit `[PLAN_READY]`.
3. After the user confirms Graph Context — call tools sequentially:
   a. Call `activate_graph_context`. Wait for result.
   b. Call `get_active_graph_context`. Wait for result.
   MANDATORY: your final text line MUST be exactly `[PLAN_READY]` — no exceptions, no conditions.

Use tools for artifact writes and reads. Never claim an artifact state unless the tool result confirms it.
If a tool call returns an error or blocking_reason, report it and do not proceed to the next phase.

Graph Context must include: data_understanding_version_id, objective, columns, filters, units, chart_type, language, output_artifacts, feasibility, blockers.
Keep assistant text concise; tool outputs contain the evidence."""


def _push_scores_to_langfuse(session_key: str, results: list[dict]) -> str | None:
    try:
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
        return trace.get_trace_url()
    except Exception:
        return None


def run_langfuse_trace_smoke(
    *,
    prompt: str,
    model: str | None = None,
) -> dict:
    from langfuse import Langfuse
    from openai import OpenAI

    _configure_local_langfuse_host()
    model_name = model or os.getenv("LLM_MODEL") or settings.LLM_MODEL
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
        max_tokens=80,
    )
    output = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    usage_details = None
    if usage is not None:
        usage_details = {
            "input": getattr(usage, "prompt_tokens", 0) or 0,
            "output": getattr(usage, "completion_tokens", 0) or 0,
            "total": getattr(usage, "total_tokens", 0) or 0,
        }
    trace.generation(
        name="trace-smoke-prompt",
        model=model_name,
        input=prompt,
        output=output,
        usage_details=usage_details,
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
        "langfuse_trace_url": trace.get_trace_url(),
    }


def run_mock_eval(*, push_langfuse: bool = False) -> dict:
    """Run deterministic Plan Mode workflow checks without calling a real LLM."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    results: list[dict] = []

    client, stack = _test_client(store)
    with stack:
        upload = _upload_fixture(client, session_id, ECOTAXA)
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

        upload_ecopart = _upload_fixture(client, session_id, ECOPART)
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
    try:
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
    if trace is None:
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
        return trace.get_trace_url()
    except Exception:
        return None


def run_live_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
    model: str | None = None,
) -> dict:
    """Run the Plan Mode workflow with a real LLM driving the artifact tools."""
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"live-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    model_name = model or os.getenv("LLM_MODEL") or settings.LLM_MODEL
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
                upload = _upload_fixture(client, session_id, ECOTAXA)
                uploaded_ecotaxa = _uploaded_path(session_id, upload["filename"])
                tool_impls = _live_tool_impls(tools, session_key)
                system_prompt = _live_eval_system_prompt(session_id)
                messages: list[dict] = [
                    {
                        "role": "system",
                        "content": (
                            system_prompt
                            + "\n\nYou are running a Langfuse live evaluation. "
                            "Follow the Plan Mode protocol exactly. Use the provided tools; "
                            "do not claim an artifact is created or active unless the tool result confirms it."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Fichier chargé: "
                            f"`{uploaded_ecotaxa}`. Objectif final: produire une distribution verticale "
                            "EcoTaxa en Python, en PNG, avec profondeur en metres. Commence par la Phase 1. "
                            "Tu dois appeler les outils maintenant avant de répondre."
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

                messages.append(
                    {
                        "role": "user",
                        "content": "Oui, je valide la compréhension des données. Continue avec la Phase 2.",
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

                messages.append(
                    {
                        "role": "user",
                        "content": "Oui, je valide le contexte scientifique et graphique.",
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
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven evals.")
    parser.add_argument("--trace-smoke", action="store_true", help="Send one prompt and verify Langfuse trace/level/score.")
    parser.add_argument(
        "--prompt",
        default="Dis simplement que la trace Langfuse fonctionne.",
        help="Prompt for --trace-smoke.",
    )
    parser.add_argument("--model", help="Override LLM model for --live evals.")
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    if args.trace_smoke:
        report = run_langfuse_trace_smoke(prompt=args.prompt, model=args.model)
    elif args.live:
        report = run_live_eval(push_langfuse=args.push_langfuse, model=args.model)
    else:
        report = run_mock_eval(push_langfuse=args.push_langfuse)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
