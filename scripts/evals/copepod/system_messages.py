from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_EVAL_CANONICAL_SESSION_ID = "eval-canonical"

_EVAL_ADDENDUM = """---
Eval context:
- When a file path appears in the eval prompt, use the exact local filesystem path shown there for tool calls. The `/app/static/...` label is informational only."""

_GC_ONLY_ADDENDUM = """---
GC-only eval context:
- An active Data Understanding already exists for this session.
- Do not call Phase 1 tools: `inspect_file`, `infer_column_roles`, `describe_column`, `summarize_understanding`, or `create_data_understanding_draft`."""


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
