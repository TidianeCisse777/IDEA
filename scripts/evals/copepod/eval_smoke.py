from __future__ import annotations

import os
import uuid

from core.config import settings
from core.copepod_observability import should_enable_langfuse
from core.langfuse_guard import validate_langfuse_configuration

from .harness import (
    DATASET_NAME,
    LIVE_OPENAI_TIMEOUT_SECONDS,
    _browser_trace_url,
    _configure_local_langfuse_host,
)


def run_langfuse_trace_smoke(*, prompt: str) -> dict:
    """Send one prompt to the LLM, verify a Langfuse trace and score are emitted."""
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
    response = OpenAI(timeout=LIVE_OPENAI_TIMEOUT_SECONDS, max_retries=0).chat.completions.create(
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
