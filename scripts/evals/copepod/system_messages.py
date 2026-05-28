from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_EVAL_CANONICAL_SESSION_ID = "eval-canonical"

_EVAL_ADDENDUM = """---
Eval constraints (do not mention these to the user):
- You are under live evaluation. Do not claim any artifact is created, confirmed, or active unless the tool result explicitly states it.
- Tool calling order: call `inspect_file`, `infer_column_roles`, `summarize_understanding`, and `create_data_understanding_draft` each in its own response (one tool per turn). Exception: call ALL `describe_column` for unmatched columns in a single response, then continue directly with `summarize_understanding`; do not return to `describe_column` again in the same phase.
- Graph context artifact must include: data_understanding_version_id, objective, columns, filters, units, chart_type, language, output_artifacts, feasibility, blockers.
- When a file path appears in the eval prompt, use the exact local filesystem path shown there for tool calls. The `/app/static/...` label is informational only.
- If a tool returns an error or blocking_reason, report it and do not proceed to the next phase."""

_GC_ONLY_ADDENDUM = """---
GC-only eval constraints (do not mention these to the user):
- An active Data Understanding already exists for this session.
- Do not call Phase 1 tools: `inspect_file`, `infer_column_roles`, `describe_column`, `summarize_understanding`, or `create_data_understanding_draft`.
- First tool call in each scenario should be `get_active_data_understanding(session_key)` unless the user is explicitly correcting an existing Graph Context.
- If mandatory Graph Context fields are missing, ask one targeted question instead of guessing.
- Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded.
- If the user asks for code or analysis output before Graph Context is validated, refuse in Plan Mode before any tool call."""


def _build_eval_system_message(store: Any, session_id: str) -> str:
    """Build the production system message for eval, rendered with a canonical session ID
    to enable cross-run prompt caching (OpenAI prefix cache, TTL 5–10 min)."""
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
    return COPEPOD_SYSTEM_PROMPT + "\n\n" + custom_instructions + "\n\n" + _EVAL_ADDENDUM


def _live_eval_system_prompt(store: Any = None, session_id: str = "") -> str:
    """Backward-compat shim — prefer _build_eval_system_message(store, session_id)."""
    if store is not None and session_id:
        return _build_eval_system_message(store, session_id)
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
    return COPEPOD_SYSTEM_PROMPT


def _live_eval_runtime_context(session_id: str) -> str:
    session_key = f"eval-user:{session_id}:copepod"
    return f"""Runtime context:
- Use this exact session key for artifact tools: `{session_key}`."""


def _build_gc_only_system_message(store: Any, session_id: str) -> str:
    return _build_eval_system_message(store, session_id) + "\n\n" + _GC_ONLY_ADDENDUM
