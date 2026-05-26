from __future__ import annotations

import os
from typing import Any


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

        lf = Langfuse()
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
