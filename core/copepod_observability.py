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


def trace_copepod_event(
    event_name: str,
    *,
    session_key: str,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Trace a copepod workflow event without making runtime behavior depend on Langfuse."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
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
