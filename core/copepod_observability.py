from __future__ import annotations

import os
from typing import Any
from urllib.request import Request, urlopen


def _configure_local_langfuse_host() -> None:
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or ""
    if "://langfuse:3000" not in host:
        return
    try:
        req = Request("http://localhost:3001/api/public/projects", method="GET")
        urlopen(req, timeout=1)
    except Exception as exc:
        if getattr(exc, "code", None) not in {200, 401}:
            return
        os.environ["LANGFUSE_HOST"] = "http://localhost:3001"
        os.environ["LANGFUSE_BASE_URL"] = "http://localhost:3001"


def should_enable_langfuse() -> bool:
    """Return True when runtime tracing should be active.

    Tests disable Langfuse by default to avoid background consumers keeping the
    Python process alive after pytest finishes. Individual tests can opt back in
    with IDEA_ENABLE_LANGFUSE_IN_TESTS=1.
    """
    if os.getenv("IDEA_DISABLE_LANGFUSE") == "1":
        return False
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("IDEA_ENABLE_LANGFUSE_IN_TESTS") != "1":
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))


def trace_copepod_event(
    event_name: str,
    *,
    session_key: str,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Trace a copepod workflow event without making runtime behavior depend on Langfuse."""
    if not should_enable_langfuse():
        return
    try:
        from langfuse import Langfuse

        _configure_local_langfuse_host()
        lf = Langfuse()
        eval_trace_id = os.getenv("COPEPOD_EVAL_LF_TRACE_ID")
        if eval_trace_id:
            # Attach to the running eval trace instead of creating an orphan
            span = lf.span(
                trace_id=eval_trace_id,
                name=f"tool/{event_name}",
                input=input or {},
                output=output or {},
                metadata={**(metadata or {}), "session_key": session_key},
            )
        else:
            span = lf.span(
                name=f"copepod_{event_name}",
                session_id=session_key,
                input=input or {},
                output=output or {},
                metadata=metadata or {},
            )
        span.end()
    except Exception:
        return


def trace_copepod_tool_call(
    tool_name: str,
    *,
    session_key: str | None,
    input: dict[str, Any] | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Trace an Open Interpreter copepod Python helper call.

    This is best-effort by design: missing Langfuse config, import failures,
    serialization problems, or tracing errors must never affect tool execution.
    """
    if not should_enable_langfuse():
        return
    try:
        from langfuse import Langfuse

        _configure_local_langfuse_host()
        lf = Langfuse()
        round_index = (metadata or {}).get("round") or os.getenv("IDEA_RUNTIME_ROUND") or "unknown"
        span_name = f"round-{round_index}/tool/{tool_name}"
        span_metadata = {
            **(metadata or {}),
            "session_key": session_key,
            "observation_type": "copepod_runtime_tool_call",
            "tool_name": tool_name,
        }
        eval_trace_id = os.getenv("COPEPOD_EVAL_LF_TRACE_ID")
        if eval_trace_id:
            span = lf.span(
                trace_id=eval_trace_id,
                name=span_name,
                input=input or {},
                output=output,
                metadata=span_metadata,
            )
        else:
            span = lf.span(
                name=span_name,
                session_id=session_key,
                input=input or {},
                output=output,
                metadata=span_metadata,
            )
        span.end()
    except Exception:
        return
